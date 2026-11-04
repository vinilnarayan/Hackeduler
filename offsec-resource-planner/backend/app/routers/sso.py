"""SSO endpoints.

Public (unauthenticated):
    GET  /api/auth/sso/providers          enabled providers + sign-in policy for the login page
    GET  /api/auth/sso/{slug}/login       starts the OIDC Authorization Code + PKCE flow (302 to IdP)
    GET  /api/auth/sso/{slug}/callback    redirect URI registered at the IdP

Admin (router-level require_admin):
    GET/PUT          /api/admin/sso/settings
    GET              /api/admin/sso/presets
    GET/POST         /api/admin/sso/providers
    GET/PATCH/DELETE /api/admin/sso/providers/{id}
    POST             /api/admin/sso/providers/{id}/test
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..errors import ServiceError, bad_request, conflict, not_found
from ..models import SSOProvider, User
from ..security import limiter
from ..services import audit, crypto, settings_service, sso
from .common import commit

public = APIRouter(prefix="/api/auth/sso", tags=["sso"])
admin = APIRouter(prefix="/api/admin/sso", tags=["admin-sso"], dependencies=[Depends(require_admin)])

TX_COOKIE = "orp_sso_tx"
CLAIM_RE = re.compile(r"^[A-Za-z0-9_:./\-]+(,[A-Za-z0-9_:./\-]+)*$")
PARAM_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,60}$")

PRESETS: dict[str, dict[str, Any]] = {
    "entra": {
        "label": "Microsoft Entra ID (Azure AD)",
        "display_name": "Sign in with Microsoft",
        "issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
        "scopes": "openid email profile",
        "email_claim": "email,preferred_username,upn",
        "name_claim": "name",
        "groups_claim": "groups",
        "token_auth_method": "client_secret_post",
        "rp_initiated_logout": True,
        "help": "App registrations → New registration → Web redirect URI = the Redirect URI below. Certificates & secrets → new client secret. "
                "Token configuration → Add groups claim (Security groups, ID token) and use group Object IDs in the mappings, "
                "or define App roles and set the groups claim to 'roles'. Use your tenant ID (not 'common') in the issuer.",
    },
    "okta": {
        "label": "Okta",
        "display_name": "Sign in with Okta",
        "issuer": "https://<your-org>.okta.com/oauth2/default",
        "scopes": "openid email profile groups",
        "email_claim": "email",
        "name_claim": "name",
        "groups_claim": "groups",
        "token_auth_method": "client_secret_basic",
        "rp_initiated_logout": True,
        "help": "Applications → Create App Integration → OIDC / Web Application. Sign-in redirect URI = the Redirect URI below. "
                "Add a 'groups' claim to the authorization server (filter e.g. Matches regex .*).",
    },
    "google": {
        "label": "Google Workspace",
        "display_name": "Sign in with Google",
        "issuer": "https://accounts.google.com",
        "scopes": "openid email profile",
        "email_claim": "email",
        "name_claim": "name",
        "groups_claim": "",
        "token_auth_method": "client_secret_post",
        "extra_auth_params": {"hd": "<your-domain.com>"},
        "rp_initiated_logout": False,
        "help": "Google Cloud console → APIs & Services → Credentials → OAuth client ID (Web). Google does not send group claims: "
                "restrict access with 'Allowed email domains' and manage admin roles in the app (turn off role sync).",
    },
    "keycloak": {
        "label": "Keycloak",
        "display_name": "Sign in with Keycloak",
        "issuer": "https://<host>/realms/<realm>",
        "scopes": "openid email profile",
        "email_claim": "email",
        "name_claim": "name",
        "groups_claim": "realm_access.roles",
        "token_auth_method": "client_secret_basic",
        "rp_initiated_logout": True,
        "help": "Clients → Create client (OpenID Connect, Client authentication ON). Valid redirect URI = the Redirect URI below. "
                "Realm roles appear in 'realm_access.roles'; for groups add a Group Membership mapper and use 'groups'.",
    },
    "generic": {
        "label": "Generic OpenID Connect",
        "display_name": "Sign in with SSO",
        "issuer": "https://<issuer>",
        "scopes": "openid email profile",
        "email_claim": "email",
        "name_claim": "name",
        "groups_claim": "groups",
        "token_auth_method": "client_secret_post",
        "rp_initiated_logout": False,
        "help": "Any OpenID Connect provider supporting the Authorization Code flow. Endpoints are discovered from "
                "<issuer>/.well-known/openid-configuration unless overridden.",
    },
}


# =============================================================== schemas
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProviderBase(_Strict):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    provider_type: Literal["entra", "okta", "google", "keycloak", "generic"] | None = None
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    issuer: str | None = Field(default=None, min_length=8, max_length=500)
    discovery_url: str | None = Field(default=None, max_length=500)
    authorization_endpoint: str | None = Field(default=None, max_length=500)
    token_endpoint: str | None = Field(default=None, max_length=500)
    jwks_uri: str | None = Field(default=None, max_length=500)
    userinfo_endpoint: str | None = Field(default=None, max_length=500)
    end_session_endpoint: str | None = Field(default=None, max_length=500)
    client_id: str | None = Field(default=None, min_length=1, max_length=300)
    client_secret: str | None = Field(default=None, max_length=1000, description="Write-only; never returned")
    clear_client_secret: bool | None = None
    token_auth_method: Literal["client_secret_post", "client_secret_basic", "none"] | None = None
    scopes: str | None = Field(default=None, max_length=500)
    extra_auth_params: dict[str, str] | None = None
    use_pkce: bool | None = None
    fetch_userinfo: bool | None = None
    rp_initiated_logout: bool | None = None
    email_claim: str | None = Field(default=None, max_length=200)
    name_claim: str | None = Field(default=None, max_length=100)
    groups_claim: str | None = Field(default=None, max_length=100)
    admin_groups: list[str] | None = Field(default=None, max_length=200)
    requester_groups: list[str] | None = Field(default=None, max_length=200)
    allowed_email_domains: list[str] | None = Field(default=None, max_length=100)
    auto_provision: bool | None = None
    default_role: Literal["requester", "admin"] | None = None
    sync_role_on_login: bool | None = None
    link_existing_by_email: bool | None = None
    clock_skew_seconds: int | None = Field(default=None, ge=0, le=600)


class ProviderCreate(ProviderBase):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    display_name: str = Field(min_length=1, max_length=80)
    issuer: str = Field(min_length=8, max_length=500)
    client_id: str = Field(min_length=1, max_length=300)


class SettingsIn(_Strict):
    local_login_mode: Literal["all", "admins_only", "disabled"] | None = None
    public_base_url: str | None = Field(default=None, max_length=300)
    sso_auto_redirect: bool | None = None


FIELDS = [f for f in ProviderBase.model_fields if f not in ("client_secret", "clear_client_secret")]


def provider_out(db: Session, p: SSOProvider) -> dict:
    out = {f: getattr(p, f) for f in FIELDS}
    out.update({
        "id": str(p.id), "slug": p.slug, "has_client_secret": bool(p.client_secret_encrypted),
        "redirect_uri": sso.redirect_uri(db, p), "last_tested_at": p.last_tested_at.isoformat() if p.last_tested_at else None,
        "last_test_ok": p.last_test_ok,
        "linked_users": db.scalar(select(func.count()).select_from(User).where(User.sso_provider_id == p.id)) or 0,
    })
    return out


def _audit_view(p: SSOProvider) -> dict:
    v = {f: audit.jsonable(getattr(p, f)) for f in FIELDS}
    v["has_client_secret"] = bool(p.client_secret_encrypted)
    return v


def _validate(p: SSOProvider) -> None:
    for f in ("issuer", "discovery_url", "authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint",
              "end_session_endpoint"):
        v = getattr(p, f)
        if v and not sso.url_allowed(v):
            raise bad_request(f"{f.replace('_', ' ').capitalize()} must be an https:// URL.")
        if v and ("<" in v or ">" in v):
            raise bad_request(f"Replace the placeholder in {f.replace('_', ' ')} with your real value.")
    if "openid" not in (p.scopes or "").split():
        raise bad_request("Scopes must include 'openid'.")
    if not CLAIM_RE.match(p.email_claim or ""):
        raise bad_request("Email claim must be a claim name (or comma-separated fallbacks).")
    for f in ("name_claim", "groups_claim"):
        v = getattr(p, f)
        if v and not CLAIM_RE.match(v):
            raise bad_request(f"{f.replace('_', ' ').capitalize()} is not a valid claim name.")
    for k, v in (p.extra_auth_params or {}).items():
        if not PARAM_RE.match(k) or k in sso.RESERVED_AUTH_PARAMS:
            raise bad_request(f"Extra authorization parameter '{k}' is not allowed.")
        if len(v) > 300 or "<" in v:
            raise bad_request(f"Invalid value for extra parameter '{k}'.")
    for f in ("admin_groups", "requester_groups", "allowed_email_domains"):
        vals = getattr(p, f) or []
        if any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in vals):
            raise bad_request(f"{f.replace('_', ' ').capitalize()} contains an invalid value.")
        setattr(p, f, sorted({x.strip().lower() if f == "allowed_email_domains" else x.strip() for x in vals}))
    if p.enabled and p.token_auth_method != "none" and not p.client_secret_encrypted:
        raise bad_request("A client secret is required before the provider can be enabled.")
    if p.default_role == "admin" and not p.requester_groups and not p.allowed_email_domains:
        raise bad_request("Default role 'admin' requires an allowed-group or allowed-domain restriction.")


def effective_local_mode(db: Session) -> str:
    return "all" if get_settings().force_local_login else settings_service.get_setting(db, "local_login_mode")


def _enabled_count(db: Session, exclude: uuid.UUID | None = None) -> int:
    q = select(func.count()).select_from(SSOProvider).where(SSOProvider.enabled.is_(True))
    if exclude:
        q = q.where(SSOProvider.id != exclude)
    return db.scalar(q) or 0


# =============================================================== public endpoints
@public.get("/providers")
def public_providers(db: Session = Depends(get_db)):
    rows = db.scalars(select(SSOProvider).where(SSOProvider.enabled.is_(True)).order_by(SSOProvider.sort_order, SSOProvider.display_name)).all()
    mode = effective_local_mode(db)
    return {
        "providers": [{"slug": p.slug, "display_name": p.display_name, "provider_type": p.provider_type} for p in rows],
        "local_login_mode": mode,
        "auto_redirect": bool(settings_service.get_setting(db, "sso_auto_redirect")) and mode == "disabled" and len(rows) == 1,
    }


def _login_redirect(code: str) -> RedirectResponse:
    r = RedirectResponse(f"/login?sso_error={quote(code)}", status_code=302)
    r.delete_cookie(TX_COOKIE, path="/api/auth/sso")
    return r


def _enabled_provider(db: Session, slug: str) -> SSOProvider | None:
    return db.scalars(select(SSOProvider).where(SSOProvider.slug == slug, SSOProvider.enabled.is_(True))).first()


@public.get("/{slug}/login")
def sso_login(slug: str, request: Request, next: str | None = Query(default=None, max_length=500), db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"sso:{ip}", get_settings().login_rate_limit_per_minute * 3):
        return _login_redirect("rate_limited")
    p = _enabled_provider(db, slug)
    if p is None:
        return _login_redirect("provider_unavailable")
    try:
        url, tx = sso.begin_login(db, p, next)
    except sso.SSOError as e:
        audit.record_detached("auth.sso_login_failed", None, entity_type="sso_provider", entity_id=slug,
                              new={"code": e.code, "detail": e.detail[:500]})
        return _login_redirect(e.code)
    s = get_settings()
    r = RedirectResponse(url, status_code=302)
    r.set_cookie(TX_COOKIE, tx, max_age=sso.TX_TTL_SECONDS, httponly=True, secure=s.cookie_secure, samesite="lax",
                 path="/api/auth/sso")
    return r


@public.get("/{slug}/callback")
def sso_callback(slug: str, request: Request, code: str | None = Query(default=None, max_length=4096),
                 state: str | None = Query(default=None, max_length=512), error: str | None = Query(default=None, max_length=200),
                 error_description: str | None = Query(default=None, max_length=1000), db: Session = Depends(get_db)):
    from .auth import set_session_cookies

    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"sso:{ip}", get_settings().login_rate_limit_per_minute * 3):
        return _login_redirect("rate_limited")
    p = _enabled_provider(db, slug)
    try:
        if p is None:
            raise sso.SSOError("provider_unavailable", f"Provider '{slug}' is not enabled")
        if error:
            raise sso.SSOError("idp_error", f"{error}: {error_description or ''}"[:500])
        if not code:
            raise sso.SSOError("idp_error", "Callback without authorization code")
        user, next_path = sso.complete_login(db, p, code, state or "", request.cookies.get(TX_COOKIE))
        commit(db)
    except (sso.SSOError, ServiceError) as e:
        db.rollback()
        code_ = e.code if isinstance(e, sso.SSOError) else "login_failed"
        detail = e.detail if isinstance(e, sso.SSOError) else e.message
        audit.record_detached("auth.sso_login_failed", None, entity_type="sso_provider", entity_id=slug,
                              new={"code": code_, "detail": (detail or "")[:500]})
        return _login_redirect(code_)
    r = RedirectResponse(next_path, status_code=302)
    r.delete_cookie(TX_COOKIE, path="/api/auth/sso")
    set_session_cookies(r, user, sso_slug=p.slug)
    return r


# =============================================================== admin endpoints
@admin.get("/settings")
def get_sso_settings(db: Session = Depends(get_db)):
    return {
        "local_login_mode": settings_service.get_setting(db, "local_login_mode"),
        "effective_local_login_mode": effective_local_mode(db),
        "force_local_login_env": get_settings().force_local_login,
        "public_base_url": settings_service.get_setting(db, "public_base_url"),
        "effective_public_base_url": sso.public_base_url(db),
        "sso_auto_redirect": settings_service.get_setting(db, "sso_auto_redirect"),
        "enabled_providers": _enabled_count(db),
    }


@admin.put("/settings")
def put_sso_settings(body: SettingsIn, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    data = body.model_dump(exclude_unset=True)
    if "public_base_url" in data and data["public_base_url"]:
        data["public_base_url"] = data["public_base_url"].rstrip("/")
    mode = data.get("local_login_mode")
    if mode in ("admins_only", "disabled") and _enabled_count(db) == 0:
        raise bad_request("Enable and test at least one SSO provider before restricting password sign-in.")
    if mode == "disabled" and not (admin_user.sso_provider_id and (admin_user.last_login_method or "").startswith("sso:")):
        raise bad_request("To disable password sign-in completely, first sign in yourself with SSO as an administrator "
                          "(this proves admins can still get in). 'Admins only' keeps a break-glass path.")
    changes = {}
    for k, v in data.items():
        try:
            old, new = settings_service.set_setting(db, k, v, admin_user.id)
        except ValueError as e:
            raise bad_request(str(e))
        if old != new:
            changes[k] = (old, new)
    if changes:
        audit.record(db, "sso.settings_updated", admin_user, entity_type="settings", entity_id="sso",
                     previous={k: c[0] for k, c in changes.items()}, new={k: c[1] for k, c in changes.items()})
    commit(db)
    return get_sso_settings(db)


@admin.get("/presets")
def presets():
    return PRESETS


@admin.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    rows = db.scalars(select(SSOProvider).order_by(SSOProvider.sort_order, SSOProvider.display_name)).all()
    return [provider_out(db, p) for p in rows]


@admin.get("/providers/{provider_id}")
def get_provider(provider_id: uuid.UUID, db: Session = Depends(get_db)):
    p = db.get(SSOProvider, provider_id)
    if p is None:
        raise not_found("SSO provider")
    return provider_out(db, p)


def _apply(p: SSOProvider, data: dict) -> list[str]:
    changed = []
    secret = data.pop("client_secret", None)
    clear = data.pop("clear_client_secret", None)
    for k, v in data.items():
        if k in ("discovery_url", "authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint",
                 "end_session_endpoint") and v == "":
            v = None
        if getattr(p, k) != v:
            setattr(p, k, v)
            changed.append(k)
    if clear:
        if p.client_secret_encrypted:
            changed.append("client_secret")
        p.client_secret_encrypted = None
    elif secret:
        p.client_secret_encrypted = crypto.encrypt(secret)
        changed.append("client_secret")
    return changed


@admin.post("/providers", status_code=201)
def create_provider(body: ProviderCreate, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    if db.scalar(select(SSOProvider.id).where(SSOProvider.slug == body.slug)):
        raise conflict("A provider with that identifier already exists.", "duplicate")
    data = body.model_dump(exclude_unset=True)
    p = SSOProvider(id=uuid.uuid4(), slug=data.pop("slug"), enabled=False, extra_auth_params={}, admin_groups=[],
                    requester_groups=[], allowed_email_domains=[], provider_type="generic", sort_order=0,
                    token_auth_method="client_secret_post", scopes="openid email profile", use_pkce=True,
                    fetch_userinfo=False, rp_initiated_logout=False, email_claim="email", name_claim="name",
                    groups_claim="groups", auto_provision=True, default_role="requester", sync_role_on_login=True,
                    link_existing_by_email=True, clock_skew_seconds=120)
    _apply(p, data)
    _validate(p)
    db.add(p)
    db.flush()
    audit.record(db, "sso.provider_created", admin_user, entity_type="sso_provider", entity_id=p.id, new=_audit_view(p))
    commit(db)
    db.refresh(p)
    return provider_out(db, p)


@admin.patch("/providers/{provider_id}")
def update_provider(provider_id: uuid.UUID, body: ProviderBase, db: Session = Depends(get_db),
                    admin_user: User = Depends(require_admin)):
    p = db.get(SSOProvider, provider_id)
    if p is None:
        raise not_found("SSO provider")
    before = _audit_view(p)
    data = body.model_dump(exclude_unset=True)
    if data.get("enabled") is False and p.enabled and effective_local_mode(db) != "all" and _enabled_count(db, exclude=p.id) == 0:
        raise bad_request("This is the only enabled provider and password sign-in is restricted. "
                          "Set password sign-in to 'All users' first to avoid locking everyone out.")
    changed = _apply(p, data)
    _validate(p)
    if changed:
        p.last_test_ok = None if set(changed) - {"display_name", "sort_order", "enabled"} else p.last_test_ok
        db.flush()
        after = _audit_view(p)
        action = "sso.provider_updated"
        if changed == ["enabled"]:
            action = "sso.provider_enabled" if p.enabled else "sso.provider_disabled"
        audit.record(db, action, admin_user, entity_type="sso_provider", entity_id=p.id, previous=before,
                     new={**after, "changed_fields": changed})
    commit(db)
    db.refresh(p)
    return provider_out(db, p)


@admin.delete("/providers/{provider_id}")
def delete_provider(provider_id: uuid.UUID, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    p = db.get(SSOProvider, provider_id)
    if p is None:
        raise not_found("SSO provider")
    if p.enabled and effective_local_mode(db) != "all" and _enabled_count(db, exclude=p.id) == 0:
        raise bad_request("Cannot delete the only enabled provider while password sign-in is restricted.")
    sso_only = db.scalar(select(func.count()).select_from(User).where(User.sso_provider_id == p.id, User.password_hash.is_(None),
                                                                      User.is_active.is_(True))) or 0
    before = _audit_view(p)
    db.execute(update(User).where(User.sso_provider_id == p.id).values(sso_provider_id=None, sso_subject=None))
    db.delete(p)
    audit.record(db, "sso.provider_deleted", admin_user, entity_type="sso_provider", entity_id=provider_id, previous=before,
                 new={"unlinked_sso_only_users": sso_only})
    commit(db)
    sso.clear_caches()
    return {"ok": True, "unlinked_sso_only_users": sso_only}


@admin.post("/providers/{provider_id}/test")
def test_provider(provider_id: uuid.UUID, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    p = db.get(SSOProvider, provider_id)
    if p is None:
        raise not_found("SSO provider")
    result = sso.test_provider(db, p)
    audit.record(db, "sso.provider_tested", admin_user, entity_type="sso_provider", entity_id=p.id,
                 new={"ok": result["ok"], "checks": [{k: c[k] for k in ("name", "ok", "level")} for c in result["checks"]]})
    commit(db)
    return result


