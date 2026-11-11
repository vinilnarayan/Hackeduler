"""OpenID Connect single sign-on (Authorization Code flow + PKCE).

Security properties
-------------------
* ``state`` (CSRF), ``nonce`` (replay) and the PKCE ``code_verifier`` are generated
  per login and kept in an ENCRYPTED, HttpOnly, 10-minute transaction cookie, so
  a callback can only be completed in the browser that started the login.
* The ID token signature is verified against the provider's JWKS. Only asymmetric
  algorithms are accepted (no ``none`` / HS*). ``iss``, ``aud``, ``exp``, ``iat``,
  ``nonce`` and (for multi-audience tokens) ``azp`` are checked.
* Roles come from IdP group/role claims mapped in the admin screen. The last
  active admin is never demoted by a role sync (lockout protection).
* An existing account is linked by email only if it has never been linked to an
  SSO identity, preventing one IdP identity from taking over another's account.
* Every success and failure is audited; tokens are never logged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ROLE_ADMIN_ID, ROLE_REQUESTER_ID, SSOProvider, User
from . import audit, crypto, settings_service
from .availability import now_utc

TX_TTL_SECONDS = 600
METADATA_TTL = 3600
JWKS_TTL = 3600
ALLOWED_ALGS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
RESERVED_AUTH_PARAMS = {"client_id", "redirect_uri", "response_type", "state", "nonce", "code_challenge",
                        "code_challenge_method", "scope", "client_secret"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_metadata_cache: dict[str, tuple[float, dict]] = {}
_jwks_cache: dict[str, tuple[float, dict]] = {}


class SSOError(Exception):
    """``code`` is shown to the user (mapped to a friendly message); ``detail`` goes to the audit log only."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class Identity:
    subject: str
    email: str
    name: str
    groups: list[str]
    claims: dict
    groups_present: bool = False  # False when the token carries no groups claim at all


# --------------------------------------------------------------------------------------
# HTTP + metadata
# --------------------------------------------------------------------------------------

def http_client() -> httpx.Client:
    """Factory (monkeypatched in tests). Redirects are not followed for token/JWKS calls."""
    return httpx.Client(timeout=get_settings().sso_http_timeout, follow_redirects=False,
                        headers={"User-Agent": "Hackeduler-SSO/1.0", "Accept": "application/json"})


def clear_caches() -> None:
    _metadata_cache.clear()
    _jwks_cache.clear()


def url_allowed(url: str | None) -> bool:
    """HTTPS required; plain HTTP is only allowed for localhost outside production."""
    if not url:
        return False
    u = urlparse(url)
    if u.scheme == "https" and u.netloc:
        return True
    if u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1") and not get_settings().is_production:
        return True
    return False


def discovery_url(p: SSOProvider) -> str:
    return p.discovery_url or p.issuer.rstrip("/") + "/.well-known/openid-configuration"


def _get_json(url: str) -> dict:
    if not url_allowed(url):
        raise SSOError("provider_unavailable", f"URL not allowed (HTTPS required): {url}")
    try:
        with http_client() as c:
            r = c.get(url)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise SSOError("provider_unavailable", f"GET {url} failed: {type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise SSOError("provider_unavailable", f"GET {url} returned HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError as e:
        raise SSOError("provider_unavailable", f"GET {url} did not return JSON") from e
    if not isinstance(data, dict):
        raise SSOError("provider_unavailable", f"GET {url} returned unexpected JSON")
    return data


def resolve_metadata(p: SSOProvider, *, force: bool = False) -> dict:
    """Discovery document merged with manual endpoint overrides (overrides win)."""
    cache_key = f"{p.id}:{p.updated_at.isoformat() if p.updated_at else ''}"
    hit = _metadata_cache.get(cache_key)
    if hit and not force and hit[0] > time.time():
        return hit[1]
    md: dict[str, Any] = {}
    discovery_error = None
    try:
        md = _get_json(discovery_url(p))
    except SSOError as e:
        discovery_error = e
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint", "end_session_endpoint"):
        override = getattr(p, field)
        if override:
            md[field] = override
    missing = [f for f in ("authorization_endpoint", "token_endpoint", "jwks_uri") if not md.get(f)]
    if missing:
        if discovery_error:
            raise discovery_error
        raise SSOError("provider_unavailable", f"Provider metadata is missing: {', '.join(missing)}")
    for f in ("authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint", "end_session_endpoint"):
        if md.get(f) and not url_allowed(md[f]):
            raise SSOError("provider_unavailable", f"{f} must use HTTPS: {md[f]}")
    md["_discovery_ok"] = discovery_error is None
    _metadata_cache[cache_key] = (time.time() + METADATA_TTL, md)
    return md


def _jwks(uri: str, *, force: bool = False) -> dict:
    hit = _jwks_cache.get(uri)
    if hit and not force and hit[0] > time.time():
        return hit[1]
    data = _get_json(uri)
    if not isinstance(data.get("keys"), list):
        raise SSOError("provider_unavailable", "JWKS document has no 'keys' array")
    _jwks_cache[uri] = (time.time() + JWKS_TTL, data)
    return data


def _signing_key(uri: str, kid: str | None, alg: str):
    for attempt in (False, True):  # refresh once to pick up key rotation
        keys = [k for k in _jwks(uri, force=attempt)["keys"] if k.get("use", "sig") == "sig"]
        cands = [k for k in keys if kid and k.get("kid") == kid] if kid else keys
        if not kid and len(keys) != 1:
            cands = []
        if cands:
            try:
                return jwt.PyJWK(cands[0], algorithm=alg).key
            except jwt.PyJWTError as e:
                raise SSOError("invalid_token", f"Unusable signing key: {e}") from e
    raise SSOError("invalid_token", f"No signing key found for kid={kid!r}")


# --------------------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------------------

def public_base_url(db: Session) -> str:
    return (settings_service.get_setting(db, "public_base_url") or get_settings().app_base_url).rstrip("/")


def redirect_uri(db: Session, p: SSOProvider) -> str:
    return f"{public_base_url(db)}/api/auth/sso/{p.slug}/callback"


def safe_next(next_path: str | None) -> str:
    """Only same-origin relative paths are allowed after login (no open redirect)."""
    if not next_path or not next_path.startswith("/") or next_path.startswith("//") or "\\" in next_path:
        return "/"
    if any(ch in next_path for ch in "\r\n\t"):
        return "/"
    return next_path[:500]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def begin_login(db: Session, p: SSOProvider, next_path: str | None = None) -> tuple[str, str]:
    """Return (authorization URL, encrypted transaction cookie value)."""
    md = resolve_metadata(p)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    tx = crypto.encrypt(json.dumps({"slug": p.slug, "state": state, "nonce": nonce, "cv": verifier,
                                    "next": safe_next(next_path)}))
    params = {k: str(v) for k, v in (p.extra_auth_params or {}).items() if k not in RESERVED_AUTH_PARAMS}
    params.update({
        "response_type": "code",
        "client_id": p.client_id,
        "redirect_uri": redirect_uri(db, p),
        "scope": p.scopes,
        "state": state,
        "nonce": nonce,
    })
    if p.use_pkce:
        params["code_challenge"] = _b64url(hashlib.sha256(verifier.encode()).digest())
        params["code_challenge_method"] = "S256"
    sep = "&" if "?" in md["authorization_endpoint"] else "?"
    return md["authorization_endpoint"] + sep + urlencode(params), tx


def logout_url(db: Session, p: SSOProvider) -> str | None:
    if not p.rp_initiated_logout:
        return None
    try:
        md = resolve_metadata(p)
    except SSOError:
        return None
    ep = md.get("end_session_endpoint")
    if not ep:
        return None
    sep = "&" if "?" in ep else "?"
    return ep + sep + urlencode({"client_id": p.client_id, "post_logout_redirect_uri": f"{public_base_url(db)}/"})


# --------------------------------------------------------------------------------------
# Callback
# --------------------------------------------------------------------------------------

def read_tx(tx_cookie: str | None, slug: str, state: str | None) -> dict:
    if not tx_cookie:
        raise SSOError("session_expired", "Missing SSO transaction cookie")
    try:
        tx = json.loads(crypto.decrypt(tx_cookie, ttl=TX_TTL_SECONDS))
    except ValueError as e:
        raise SSOError("session_expired", "SSO transaction cookie invalid or expired") from e
    if tx.get("slug") != slug:
        raise SSOError("state_mismatch", "Transaction was started for a different provider")
    if not state or not hmac.compare_digest(str(tx.get("state")), state):
        raise SSOError("state_mismatch", "State parameter does not match")
    return tx


def exchange_code(db: Session, p: SSOProvider, md: dict, code: str, verifier: str) -> dict:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(db, p),
            "client_id": p.client_id}
    if p.use_pkce:
        data["code_verifier"] = verifier
    auth = None
    try:
        secret = crypto.decrypt(p.client_secret_encrypted) if p.client_secret_encrypted else None
    except ValueError as e:
        # The key that encrypted the secret is not the key in use now (HACKEDULER_ENCRYPTION_KEY / SECRET_KEY changed).
        raise SSOError("token_exchange_failed",
                       "The stored client secret cannot be decrypted (the encryption key changed since it was saved). "
                       "Re-enter the client secret under Admin > Single Sign-On.") from e
    if p.token_auth_method == "client_secret_post" and secret:
        data["client_secret"] = secret
    elif p.token_auth_method == "client_secret_basic" and secret:
        from urllib.parse import quote

        auth = httpx.BasicAuth(quote(p.client_id, safe=""), quote(secret, safe=""))
    try:
        with http_client() as c:
            r = c.post(md["token_endpoint"], data=data, auth=auth)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise SSOError("token_exchange_failed", f"Token endpoint error: {type(e).__name__}") from e
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or not isinstance(body, dict) or not body.get("id_token"):
        err = body.get("error") if isinstance(body, dict) else None
        desc = body.get("error_description") if isinstance(body, dict) else None
        raise SSOError("token_exchange_failed", f"HTTP {r.status_code} {err or ''} {str(desc or '')[:300]}".strip())
    return body


def validate_id_token(p: SSOProvider, md: dict, id_token: str, nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as e:
        raise SSOError("invalid_token", f"Malformed ID token: {e}") from e
    alg = header.get("alg")
    if alg not in ALLOWED_ALGS:
        raise SSOError("invalid_token", f"Disallowed ID token algorithm: {alg!r}")
    key = _signing_key(md["jwks_uri"], header.get("kid"), alg)
    base_iss = p.issuer.rstrip("/")
    try:
        claims = jwt.decode(
            id_token, key, algorithms=[alg], audience=p.client_id, issuer=[base_iss, base_iss + "/"],
            leeway=p.clock_skew_seconds, options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise SSOError("invalid_token", f"ID token rejected: {type(e).__name__}: {e}") from e
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != p.client_id:
        raise SSOError("invalid_token", "azp does not match client_id for multi-audience token")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SSOError("invalid_token", "Nonce mismatch (possible replay)")
    return claims


def fetch_userinfo(md: dict, access_token: str | None, subject: str) -> dict:
    if not md.get("userinfo_endpoint") or not access_token:
        return {}
    try:
        with http_client() as c:
            r = c.get(md["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"})
        info = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return {}
    if not isinstance(info, dict) or info.get("sub") != subject:
        return {}  # OIDC Core 5.3.2: userinfo sub MUST match the ID token sub
    return info


def _claim(claims: dict, path: str) -> Any:
    """Supports dotted paths for nested claims, e.g. Keycloak 'realm_access.roles'."""
    cur: Any = claims
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def extract_identity(p: SSOProvider, claims: dict) -> Identity:
    email = None
    for c in [x.strip() for x in p.email_claim.split(",") if x.strip()]:
        v = _claim(claims, c)
        if isinstance(v, str) and EMAIL_RE.match(v.strip()):
            email = v.strip().lower()
            break
    if not email:
        raise SSOError("email_missing", f"No valid email in claim(s) '{p.email_claim}'")
    if claims.get("email_verified") is False and "email" in p.email_claim:
        raise SSOError("email_missing", "The identity provider reports the email address as unverified")
    name = _claim(claims, p.name_claim)
    if not isinstance(name, str) or not name.strip():
        name = email.split("@")[0]
    raw = _claim(claims, p.groups_claim) if p.groups_claim else None
    # Entra ID "groups overage": >200 groups -> claim replaced by a _claim_names pointer; treat as absent
    overage = isinstance(claims.get("_claim_names"), dict) and p.groups_claim in claims["_claim_names"]
    present = raw is not None and not overage
    if isinstance(raw, str):
        groups = [g for g in re.split(r"[\s,]+", raw) if g]
    elif isinstance(raw, list):
        groups = [str(g) for g in raw if isinstance(g, (str, int))]
    else:
        groups = []
    return Identity(subject=str(claims["sub"]), email=email, name=name.strip()[:200], groups=groups, claims=claims,
                    groups_present=present)


def _norm(values) -> set[str]:
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def decide_role(p: SSOProvider, ident: Identity) -> str:
    """Return 'admin' | 'requester' or raise if the identity is not allowed in."""
    domains = _norm(p.allowed_email_domains)
    if domains and ident.email.rsplit("@", 1)[1] not in domains:
        raise SSOError("domain_not_allowed", f"Email domain of {ident.email} is not allowed")
    groups = _norm(ident.groups)
    admin_groups = _norm(p.admin_groups)
    requester_groups = _norm(p.requester_groups)
    if groups & admin_groups:
        return "admin"
    if requester_groups and not (groups & requester_groups):
        raise SSOError("group_not_allowed", f"{ident.email} is not a member of an allowed group")
    return p.default_role


def _active_admin_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role_id == ROLE_ADMIN_ID, User.is_active.is_(True))) or 0


def provision_user(db: Session, p: SSOProvider, ident: Identity) -> tuple[User, dict]:
    role = decide_role(p, ident)
    role_id = ROLE_ADMIN_ID if role == "admin" else ROLE_REQUESTER_ID
    info: dict[str, Any] = {"provisioned": False, "linked": False, "role_changed": None}

    user = db.scalars(select(User).where(User.sso_provider_id == p.id, User.sso_subject == ident.subject)).first()
    if user is None:
        existing = db.scalars(select(User).where(func.lower(User.email) == ident.email, User.deleted_at.is_(None))).first()
        if existing is not None:
            if not p.link_existing_by_email:
                raise SSOError("identity_conflict", f"An account for {ident.email} exists but email linking is disabled")
            if existing.sso_provider_id is not None or existing.sso_subject is not None:
                raise SSOError("identity_conflict", f"{ident.email} is already linked to a different SSO identity")
            existing.sso_provider_id, existing.sso_subject = p.id, ident.subject
            user = existing
            info["linked"] = True
        elif p.auto_provision:
            user = User(id=uuid.uuid4(), email=ident.email, full_name=ident.name, password_hash=None, role_id=role_id,
                        sso_provider_id=p.id, sso_subject=ident.subject)
            db.add(user)
            db.flush()
            db.refresh(user)
            info["provisioned"] = True
        else:
            raise SSOError("not_provisioned", f"No account exists for {ident.email} and auto-provisioning is off")

    if not user.is_active:
        raise SSOError("account_disabled", f"Account {user.email} is disabled")

    # Role sync is only trustworthy when the IdP is actually configured to tell us about roles:
    # admin groups must be mapped AND the token must contain the groups claim. A missing claim
    # (not configured at the IdP, or Entra group overage) must never demote anyone.
    sync = p.sync_role_on_login and not info["provisioned"]
    if sync and not _norm(p.admin_groups):
        sync, info["role_sync_skipped"] = False, "no admin groups mapped - role managed in the app"
    elif sync and not ident.groups_present:
        sync, info["role_sync_skipped"] = False, f"token has no '{p.groups_claim}' claim - role kept"
    if sync and user.role_id != role_id:
        if user.role_id == ROLE_ADMIN_ID and _active_admin_count(db) <= 1:
            info["role_sync_skipped"] = "last active admin would be demoted"
        else:
            info["role_changed"] = {"from": user.role_name, "to": role}
            user.role_id = role_id
            user.token_version += 1  # invalidate sessions issued under the old role
    if ident.name and user.full_name != ident.name:
        user.full_name = ident.name
    if user.email.lower() != ident.email:
        # identity is keyed on (provider, sub); keep the email in sync unless it collides
        if not db.scalar(select(User.id).where(func.lower(User.email) == ident.email, User.id != user.id,
                                               User.deleted_at.is_(None))):
            user.email = ident.email
    user.last_login_at = now_utc()
    user.last_login_method = f"sso:{p.slug}"
    db.flush()
    db.refresh(user)
    return user, info


def complete_login(db: Session, p: SSOProvider, code: str, state: str, tx_cookie: str | None) -> tuple[User, str]:
    tx = read_tx(tx_cookie, p.slug, state)
    md = resolve_metadata(p)
    tokens = exchange_code(db, p, md, code, tx["cv"])
    claims = validate_id_token(p, md, tokens["id_token"], tx["nonce"])
    if p.fetch_userinfo:
        info = fetch_userinfo(md, tokens.get("access_token"), str(claims["sub"]))
        claims = {**info, **claims}
    ident = extract_identity(p, claims)
    user, info = provision_user(db, p, ident)
    if info.get("role_changed"):
        audit.record(db, "user.role_synced", user, entity_type="user", entity_id=user.id,
                     previous={"role": info["role_changed"]["from"]}, new={"role": info["role_changed"]["to"]},
                     reason=f"Role synchronised from {p.display_name} group claims")
    if info.get("provisioned"):
        audit.record(db, "user.sso_provisioned", user, entity_type="user", entity_id=user.id,
                     new={"email": user.email, "role": user.role_name, "provider": p.slug})
    audit.record(db, "auth.sso_login", user, entity_type="user", entity_id=user.id,
                 new={"provider": p.slug, "subject": ident.subject, "email": ident.email, "role": user.role_name,
                      "groups_claim_present": ident.groups_present, "groups_received": ident.groups[:50],
                      "groups_matched": sorted(_norm(ident.groups) & (_norm(p.admin_groups) | _norm(p.requester_groups))),
                      **{k: v for k, v in info.items() if v}})
    return user, tx.get("next") or "/"


# --------------------------------------------------------------------------------------
# Admin connection test
# --------------------------------------------------------------------------------------

def test_provider(db: Session, p: SSOProvider) -> dict:
    result: dict[str, Any] = {"ok": False, "checks": [], "metadata": {}, "redirect_uri": redirect_uri(db, p)}

    def check(name: str, ok: bool, detail: str = "", level: str | None = None):
        result["checks"].append({"name": name, "ok": ok, "level": level or ("ok" if ok else "error"), "detail": detail})

    try:
        md = resolve_metadata(p, force=True)
        check("Discovery document", md.get("_discovery_ok", False),
              discovery_url(p) if md.get("_discovery_ok") else "Not reachable – using manual endpoint overrides",
              None if md.get("_discovery_ok") else "warning")
        result["metadata"] = {k: md.get(k) for k in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri",
                                                    "userinfo_endpoint", "end_session_endpoint")}
        if md.get("issuer"):
            same = md["issuer"].rstrip("/") == p.issuer.rstrip("/")
            check("Issuer matches", same, f"configured {p.issuer} / discovered {md['issuer']}")
        jw = _jwks(md["jwks_uri"], force=True)
        n = len([k for k in jw["keys"] if k.get("use", "sig") == "sig"])
        check("Signing keys (JWKS)", n > 0, f"{n} signing key(s)")
        algs = md.get("id_token_signing_alg_values_supported")
        if algs:
            ok_algs = [a for a in algs if a in ALLOWED_ALGS]
            check("Asymmetric ID token signing", bool(ok_algs), ", ".join(algs))
        if p.use_pkce and md.get("code_challenge_methods_supported") is not None:
            check("PKCE S256 supported", "S256" in md["code_challenge_methods_supported"],
                  ", ".join(md["code_challenge_methods_supported"]), None if "S256" in md["code_challenge_methods_supported"] else "warning")
        if p.token_auth_method != "none":
            check("Client secret configured", bool(p.client_secret_encrypted), "" if p.client_secret_encrypted else "Set the client secret")
        if "openid" not in p.scopes.split():
            check("Scopes include 'openid'", False)
        if not url_allowed(result["redirect_uri"]):
            check("Redirect URI uses HTTPS", False, result["redirect_uri"], "warning")
        result["ok"] = all(c["ok"] or c["level"] == "warning" for c in result["checks"])
    except SSOError as e:
        check("Provider reachable", False, e.detail or e.code)
    p.last_tested_at = now_utc()
    p.last_test_ok = result["ok"]
    return result
