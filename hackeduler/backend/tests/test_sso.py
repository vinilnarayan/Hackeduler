"""OpenID Connect SSO tests against an in-process fake identity provider.

The fake IdP signs real RS256 ID tokens, publishes a JWKS, and its token endpoint
verifies client credentials and the PKCE code_verifier - so these tests exercise
the full Authorization Code + PKCE flow end to end.
"""
import base64
import hashlib
import json
import secrets
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, SSOProvider, User
from app.services import sso

from .conftest import PASSWORD, Api

ISSUER = "https://idp.test/tenant"
CLIENT_ID = "hackeduler-client"
CLIENT_SECRET = "s3cr3t-value-xyz"


class FakeIdP:
    def __init__(self):
        self.keys = {}
        self.kid = self.rotate()
        self.codes: dict[str, dict] = {}
        self.userinfo: dict = {}
        self.token_status = 200

    def rotate(self) -> str:
        kid = "k" + secrets.token_hex(3)
        self.keys[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = kid
        return kid

    def jwks(self):
        out = []
        for kid, k in self.keys.items():
            j = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(k.public_key()))
            j.update({"kid": kid, "use": "sig", "alg": "RS256"})
            out.append(j)
        return {"keys": out}

    def mint(self, claims: dict, *, kid=None, key=None, alg="RS256", headers=None) -> str:
        kid = kid or self.kid
        return jwt.encode(claims, key or self.keys[kid], algorithm=alg, headers={"kid": kid, **(headers or {})})

    def base_claims(self, nonce, **over):
        now = int(time.time())
        c = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "user-123", "iat": now, "exp": now + 300, "nonce": nonce,
             "email": "alice@corp.example", "name": "Alice Example", "groups": ["offsec-requesters"]}
        c.update(over)
        return {k: v for k, v in c.items() if v is not None}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/tenant/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": "https://idp.test/authorize",
                "token_endpoint": "https://idp.test/token", "jwks_uri": "https://idp.test/jwks",
                "userinfo_endpoint": "https://idp.test/userinfo", "end_session_endpoint": "https://idp.test/logout",
                "id_token_signing_alg_values_supported": ["RS256"], "code_challenge_methods_supported": ["S256"]})
        if path == "/jwks":
            return httpx.Response(200, json=self.jwks())
        if path == "/userinfo":
            return httpx.Response(200, json=self.userinfo)
        if path == "/token":
            form = parse_qs(request.content.decode())
            f = {k: v[0] for k, v in form.items()}
            entry = self.codes.pop(f.get("code", ""), None)
            if self.token_status != 200 or entry is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if f.get("client_id") != CLIENT_ID or f.get("client_secret") != CLIENT_SECRET:
                return httpx.Response(401, json={"error": "invalid_client"})
            challenge = base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
            if challenge != entry["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE mismatch"})
            if f.get("redirect_uri") != entry["redirect_uri"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "redirect_uri"})
            return httpx.Response(200, json={"id_token": entry["id_token"], "access_token": "at-1", "token_type": "Bearer"})
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch):
    fake = FakeIdP()
    sso.clear_caches()
    monkeypatch.setattr(sso, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    yield fake
    sso.clear_caches()


def provider_payload(**over):
    p = {"slug": "corp", "display_name": "Sign in with Corp", "provider_type": "entra", "issuer": ISSUER,
         "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "email_claim": "email,preferred_username",
         "groups_claim": "groups", "admin_groups": ["offsec-admins"], "enabled": True}
    p.update(over)
    return p


@pytest.fixture
def provider(admin, idp):
    r = admin.post("/api/admin/sso/providers", json=provider_payload())
    assert r.status_code == 201, r.text
    return r.json()


def sso_login(idp: FakeIdP, client: TestClient | None = None, *, claims=None, token=None, tamper_state=False, next_path=None):
    from app.main import app

    client = client or TestClient(app)
    url = "/api/auth/sso/corp/login" + (f"?next={next_path}" if next_path else "")
    r = client.get(url, follow_redirects=False)
    assert r.status_code == 302
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    code = secrets.token_urlsafe(8)
    id_token = token(q) if token else idp.mint(idp.base_claims(q["nonce"], **(claims or {})))
    idp.codes[code] = {"challenge": q["code_challenge"], "redirect_uri": q["redirect_uri"], "id_token": id_token}
    state = "wrong" if tamper_state else q["state"]
    r2 = client.get(f"/api/auth/sso/corp/callback?code={code}&state={state}", follow_redirects=False)
    return client, r2


def err(resp) -> str | None:
    loc = resp.headers.get("location", "")
    q = parse_qs(urlparse(loc).query)
    return q.get("sso_error", [None])[0]


# ---------------------------------------------------------------- admin configuration
def test_secret_is_write_only_and_encrypted(admin, provider):
    assert "client_secret" not in provider and provider["has_client_secret"] is True
    assert CLIENT_SECRET not in json.dumps(admin.get("/api/admin/sso/providers").json())
    db = SessionLocal()
    row = db.get(SSOProvider, uuid.UUID(provider["id"]))
    assert row.client_secret_encrypted and CLIENT_SECRET not in row.client_secret_encrypted
    audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "sso_provider")).all()
    assert audits and all(CLIENT_SECRET not in json.dumps([a.new_value, a.previous_value]) for a in audits)
    db.close()
    assert provider["redirect_uri"].endswith("/api/auth/sso/corp/callback")
    # patching other fields keeps the secret; clearing removes it (and then the provider can't stay enabled)
    r = admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"display_name": "Corp SSO"})
    assert r.json()["has_client_secret"] is True
    r = admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"clear_client_secret": True})
    assert r.status_code == 422
    r = admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"clear_client_secret": True, "enabled": False})
    assert r.status_code == 200 and r.json()["has_client_secret"] is False


@pytest.mark.parametrize("bad", [
    {"issuer": "http://idp.example.com"},                       # plain http
    {"issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0"},  # unreplaced placeholder
    {"scopes": "email profile"},                                # no openid
    {"client_secret": None, "enabled": True},                   # enabled without secret
    {"extra_auth_params": {"redirect_uri": "https://evil"}},    # reserved param
    {"email_claim": "email; drop"},
    {"slug": "Bad Slug"},
    {"default_role": "admin"},                                  # admin default without restriction
])
def test_provider_validation(admin, idp, bad):
    body = provider_payload(**bad)
    body = {k: v for k, v in body.items() if v is not None}
    assert admin.post("/api/admin/sso/providers", json=body).status_code == 422


def test_requester_cannot_manage_sso(req1, provider):
    assert req1.get("/api/admin/sso/providers").status_code == 403
    assert req1.post("/api/admin/sso/providers", json=provider_payload(slug="x")).status_code == 403
    assert req1.patch(f"/api/admin/sso/providers/{provider['id']}", json={"enabled": False}).status_code == 403
    assert req1.post(f"/api/admin/sso/providers/{provider['id']}/test").status_code == 403
    assert req1.put("/api/admin/sso/settings", json={"local_login_mode": "all"}).status_code == 403


def test_connection_test(admin, provider):
    r = admin.post(f"/api/admin/sso/providers/{provider['id']}/test").json()
    assert r["ok"] is True, r
    names = {c["name"] for c in r["checks"]}
    assert {"Discovery document", "Issuer matches", "Signing keys (JWKS)"} <= names
    assert r["metadata"]["token_endpoint"] == "https://idp.test/token"
    assert admin.get(f"/api/admin/sso/providers/{provider['id']}").json()["last_test_ok"] is True


def test_public_provider_list(admin, provider):
    from app.main import app

    c = TestClient(app)
    body = c.get("/api/auth/sso/providers").json()
    assert body["providers"] == [{"slug": "corp", "display_name": "Sign in with Corp", "provider_type": "entra"}]
    assert "client" not in json.dumps(body) and "issuer" not in json.dumps(body)
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"enabled": False})
    assert c.get("/api/auth/sso/providers").json()["providers"] == []
    r = c.get("/api/auth/sso/corp/login", follow_redirects=False)
    assert err(r) == "provider_unavailable"


# ---------------------------------------------------------------- login flow
def test_authorization_request_has_state_nonce_and_pkce(provider):
    from app.main import app

    c = TestClient(app)
    r = c.get("/api/auth/sso/corp/login", follow_redirects=False)
    loc = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert loc.netloc == "idp.test" and loc.path == "/authorize"
    assert q["response_type"] == "code" and q["client_id"] == CLIENT_ID and q["code_challenge_method"] == "S256"
    assert len(q["state"]) >= 32 and len(q["nonce"]) >= 32 and q["code_challenge"]
    assert "client_secret" not in q
    tx = r.cookies.get("hackeduler_sso_tx")
    assert tx and q["state"] not in tx  # transaction cookie is encrypted
    assert "httponly" in r.headers["set-cookie"].lower()


def test_first_login_provisions_requester(idp, provider):
    c, r = sso_login(idp)
    assert r.status_code == 302 and r.headers["location"] == "/"
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "alice@corp.example" and me["user"]["role"] == "requester"
    assert me["user"]["has_password"] is False and me["auth_method"] == "sso"
    assert me["user"]["sso_provider_name"] == "Sign in with Corp"
    # the session works for protected, CSRF-protected endpoints
    csrf = c.cookies.get("hackeduler_csrf")
    assert c.get("/api/bookings/mine").status_code == 200
    assert c.post("/api/bookings/00000000-0000-4000-8000-000000000000/cancel", json={"reason": "x"},
                  headers={"X-CSRF-Token": csrf}).status_code == 404
    db = SessionLocal()
    actions = {a.action for a in db.scalars(select(AuditLog)).all()}
    assert {"auth.sso_login", "user.sso_provisioned"} <= actions
    db.close()
    # second login re-uses the same account
    c2, _ = sso_login(idp)
    assert c2.get("/api/auth/me").json()["user"]["id"] == me["user"]["id"]


def test_admin_group_maps_to_admin(idp, provider):
    c, _ = sso_login(idp, claims={"groups": ["offsec-admins"], "sub": "admin-sub", "email": "boss@corp.example"})
    assert c.get("/api/auth/me").json()["user"]["role"] == "admin"
    assert c.get("/api/admin/sso/providers").status_code == 200


def test_role_sync_on_login(idp, provider):
    c, _ = sso_login(idp, claims={"groups": ["offsec-admins"]})
    assert c.get("/api/auth/me").json()["user"]["role"] == "admin"
    c2, _ = sso_login(idp, claims={"groups": ["offsec-requesters"]})
    assert c2.get("/api/auth/me").json()["user"]["role"] == "requester"
    assert c.get("/api/auth/me").status_code == 401  # old admin session revoked on demotion
    db = SessionLocal()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.role_synced")) is not None
    db.close()


def test_last_admin_is_never_demoted(idp, admin, provider, data):
    # the only admin links their account via SSO but the IdP does not put them in the admin group
    db = SessionLocal()
    db.get(User, data["users"]["admin"].id).is_active = True
    db.commit()
    db.close()
    c, r = sso_login(idp, claims={"email": "admin@test.local", "sub": "adm", "groups": []})
    assert r.headers["location"] == "/"
    me = c.get("/api/auth/me").json()["user"]
    assert me["role"] == "admin"  # protected from lockout


def test_requester_group_restriction(admin, idp, provider):
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"requester_groups": ["offsec-requesters"]})
    _, r = sso_login(idp, claims={"groups": ["finance"]})
    assert err(r) == "group_not_allowed"
    _, r = sso_login(idp, claims={"groups": ["offsec-requesters"]})
    assert r.headers["location"] == "/"


def test_domain_restriction(admin, idp, provider):
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"allowed_email_domains": ["Corp.Example"]})
    _, r = sso_login(idp, claims={"email": "eve@evil.example", "sub": "eve"})
    assert err(r) == "domain_not_allowed"
    _, r = sso_login(idp)
    assert r.headers["location"] == "/"


def test_email_claim_fallback_and_unverified_email(idp, provider):
    c, r = sso_login(idp, claims={"email": None, "preferred_username": "Bob@Corp.Example", "sub": "bob"})
    assert c.get("/api/auth/me").json()["user"]["email"] == "bob@corp.example"
    _, r = sso_login(idp, claims={"email_verified": False, "sub": "unv", "email": "unv@corp.example"})
    assert err(r) == "email_missing"
    _, r = sso_login(idp, claims={"email": None, "sub": "noemail"})
    assert err(r) == "email_missing"


def test_state_mismatch_and_missing_transaction(idp, provider):
    _, r = sso_login(idp, tamper_state=True)
    assert err(r) == "state_mismatch"
    from app.main import app

    fresh = TestClient(app)  # callback in a browser that never started the login
    r = fresh.get("/api/auth/sso/corp/callback?code=abc&state=xyz", follow_redirects=False)
    assert err(r) == "session_expired"


def _tok(idp, **kw):
    def make(q):
        claims = idp.base_claims(q["nonce"])
        claims.update(kw.pop("claims", {}))
        if kw.get("alg") == "HS256":
            return jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": idp.kid})
        if kw.get("alg") == "none":
            return jwt.encode(claims, None, algorithm="none")
        if kw.get("foreign_key"):
            other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            return idp.mint(claims, key=other)
        return idp.mint(claims)
    return make


@pytest.mark.parametrize("variant", [
    {"claims": {"aud": "someone-else"}},
    {"claims": {"iss": "https://attacker.test"}},
    {"claims": {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}},
    {"claims": {"nonce": "replayed"}},
    {"claims": {"aud": [CLIENT_ID, "other"], "azp": "other"}},
    {"alg": "HS256"},
    {"alg": "none"},
    {"foreign_key": True},
])
def test_invalid_id_tokens_rejected(idp, provider, variant):
    c, r = sso_login(idp, token=_tok(idp, **dict(variant)))
    assert err(r) == "invalid_token", variant
    assert c.get("/api/auth/me").status_code == 401


def test_token_exchange_failure(admin, idp, provider):
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"client_secret": "wrong-secret"})
    _, r = sso_login(idp)
    assert err(r) == "token_exchange_failed"
    db = SessionLocal()
    a = db.scalar(select(AuditLog).where(AuditLog.action == "auth.sso_login_failed"))
    assert a and a.new_value["code"] == "token_exchange_failed" and "wrong-secret" not in json.dumps(a.new_value)
    db.close()


def test_idp_error_callback(provider):
    from app.main import app

    c = TestClient(app)
    c.get("/api/auth/sso/corp/login", follow_redirects=False)
    r = c.get("/api/auth/sso/corp/callback?error=access_denied&error_description=User+cancelled", follow_redirects=False)
    assert err(r) == "idp_error"


def test_key_rotation_refreshes_jwks(idp, provider):
    sso_login(idp)               # caches the JWKS
    idp.rotate()                 # IdP starts signing with a new key
    c, r = sso_login(idp)
    assert r.headers["location"] == "/"


def test_userinfo_merge_requires_matching_sub(admin, idp, provider):
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"fetch_userinfo": True})
    idp.userinfo = {"sub": "user-123", "groups": ["offsec-admins"]}
    c, _ = sso_login(idp, claims={"groups": None})
    assert c.get("/api/auth/me").json()["user"]["role"] == "admin"
    idp.userinfo = {"sub": "someone-else", "groups": ["offsec-admins"]}
    c, _ = sso_login(idp, claims={"groups": None, "sub": "u2", "email": "u2@corp.example"})
    assert c.get("/api/auth/me").json()["user"]["role"] == "requester"


def test_nested_group_claim(admin, idp, provider):
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"groups_claim": "realm_access.roles"})
    c, _ = sso_login(idp, claims={"groups": None, "realm_access": {"roles": ["offsec-admins"]}})
    assert c.get("/api/auth/me").json()["user"]["role"] == "admin"


def test_open_redirect_is_blocked(idp, provider):
    _, r = sso_login(idp, next_path="//evil.example/x")
    assert r.headers["location"] == "/"
    _, r = sso_login(idp, next_path="/my-bookings")
    assert r.headers["location"] == "/my-bookings"


# ---------------------------------------------------------------- provisioning & linking
def test_no_auto_provision_requires_preprovisioned_account(admin, idp, provider):
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"auto_provision": False})
    _, r = sso_login(idp)
    assert err(r) == "not_provisioned"
    # admin pre-provisions an SSO-only account (no password)
    r = admin.post("/api/admin/users", json={"email": "alice@corp.example", "full_name": "Alice", "role": "requester"})
    assert r.status_code == 201 and r.json()["has_password"] is False
    c, r = sso_login(idp)
    assert r.headers["location"] == "/"
    assert c.get("/api/auth/me").json()["user"]["sso_provider_name"] == "Sign in with Corp"


def test_existing_local_user_is_linked_by_email(idp, provider, data):
    c, r = sso_login(idp, claims={"email": "req1@test.local", "sub": "req1-sub"})
    me = c.get("/api/auth/me").json()["user"]
    assert me["id"] == str(data["users"]["req1"].id) and me["has_password"] is True


def test_identity_conflict_prevents_takeover(idp, provider, data):
    sso_login(idp, claims={"email": "req1@test.local", "sub": "req1-sub"})
    # a DIFFERENT IdP subject asserting the same email must not take over the linked account
    _, r = sso_login(idp, claims={"email": "req1@test.local", "sub": "attacker-sub"})
    assert err(r) == "identity_conflict"


def test_disabled_account_cannot_sign_in(admin, idp, provider):
    c, _ = sso_login(idp)
    uid = c.get("/api/auth/me").json()["user"]["id"]
    admin.patch(f"/api/admin/users/{uid}", json={"is_active": False})
    _, r = sso_login(idp)
    assert err(r) == "account_disabled"


def test_sso_only_account_cannot_use_password(idp, provider):
    from app.main import app

    sso_login(idp)
    r = TestClient(app).post("/api/auth/login", json={"email": "alice@corp.example", "password": "anything-at-all"})
    assert r.status_code == 401


# ---------------------------------------------------------------- sign-in policy
def _pwd_login(email):
    from app.main import app

    return TestClient(app).post("/api/auth/login", json={"email": email, "password": PASSWORD})


def test_password_policy_requires_working_sso(admin, idp):
    r = admin.put("/api/admin/sso/settings", json={"local_login_mode": "admins_only"})
    assert r.status_code == 422  # no enabled provider yet


def test_admins_only_policy(admin, idp, provider):
    r = admin.put("/api/admin/sso/settings", json={"local_login_mode": "admins_only"})
    assert r.status_code == 200 and r.json()["effective_local_login_mode"] == "admins_only"
    assert _pwd_login("req1@test.local").status_code == 403
    assert _pwd_login("admin@test.local").status_code == 200   # break-glass admin
    # the only enabled provider can't be disabled/deleted while password login is restricted
    assert admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"enabled": False}).status_code == 422
    assert admin.delete(f"/api/admin/sso/providers/{provider['id']}").status_code == 422


def test_disable_password_login_requires_admin_sso_proof(admin, idp, provider, monkeypatch):
    assert admin.put("/api/admin/sso/settings", json={"local_login_mode": "disabled"}).status_code == 422
    c, _ = sso_login(idp, claims={"groups": ["offsec-admins"], "sub": "boss", "email": "boss@corp.example"})
    sso_admin = Api.__new__(Api)
    sso_admin.c, sso_admin.csrf = c, c.cookies.get("hackeduler_csrf")
    r = sso_admin.put("/api/admin/sso/settings", json={"local_login_mode": "disabled"})
    assert r.status_code == 200, r.text
    assert _pwd_login("admin@test.local").status_code == 403
    assert _pwd_login("req1@test.local").status_code == 403
    # break-glass environment override
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "force_local_login", True)
    assert _pwd_login("admin@test.local").status_code == 200


def test_rp_initiated_logout(admin, idp, provider):
    admin.patch(f"/api/admin/sso/providers/{provider['id']}", json={"rp_initiated_logout": True})
    c, _ = sso_login(idp)
    r = c.post("/api/auth/logout", headers={"X-CSRF-Token": c.cookies.get("hackeduler_csrf")})
    url = r.json()["sso_logout_url"]
    assert url.startswith("https://idp.test/logout?") and "post_logout_redirect_uri" in url
    assert c.get("/api/auth/me").status_code == 401


def test_admin_unlink_and_password_management(admin, idp, provider):
    c, _ = sso_login(idp)
    uid = c.get("/api/auth/me").json()["user"]["id"]
    assert admin.patch(f"/api/admin/users/{uid}", json={"unlink_sso": True}).status_code == 422  # would be unusable
    r = admin.patch(f"/api/admin/users/{uid}", json={"unlink_sso": True, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["sso_provider_id"] is None and r.json()["has_password"] is True
