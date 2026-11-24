from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..errors import ServiceError, bad_request
from ..models import SSOProvider, User
from ..schemas import LoginIn, PasswordChange, ProductRef, UserOut
from ..security import (
    create_session_token,
    decode_session_token,
    hash_password,
    limiter,
    validate_password_strength,
    verify_password,
)
from ..services import audit, settings_service
from ..services.availability import now_utc
from .common import commit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User, provider_name: str | None = None) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role_name, is_active=u.is_active,
                   last_login_at=u.last_login_at, has_password=u.password_hash is not None,
                   sso_provider_id=u.sso_provider_id, sso_provider_name=provider_name,
                   last_login_method=u.last_login_method, deleted_at=u.deleted_at,
                   product_id=u.product_id, product_name=u.product.name if u.product else None,
                   products=[ProductRef(id=p.id, name=p.name) for p in u.products],
                   extra_product_ids=[p.id for p in u.extra_products if p.id != u.product_id],
                   implementation_id=u.implementation_id,
                   implementation_name=u.implementation.name if u.implementation else None,
                   resource_id=u.resource_id, resource_name=u.resource.display_name if u.resource else None,
                   is_lead=bool(u.is_lead and u.is_resource))


def set_session_cookies(response: Response, user: User, sso_slug: str | None = None, act: User | None = None) -> str:
    s = get_settings()
    token, csrf = create_session_token(user.id, user.token_version, sso=sso_slug,
                                       act=(act.id, act.token_version, act.email) if act else None)
    max_age = s.act_as_minutes * 60 if act else s.session_hours * 3600
    response.set_cookie(s.session_cookie_name, token, max_age=max_age, httponly=True, secure=s.cookie_secure,
                        samesite="lax", path="/")
    response.set_cookie(s.csrf_cookie_name, csrf, max_age=max_age, httponly=False, secure=s.cookie_secure,
                        samesite="strict", path="/")
    return csrf


def local_login_mode(db: Session) -> str:
    return "all" if get_settings().force_local_login else settings_service.get_setting(db, "local_login_mode")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Local password sign-in, subject to the admin-configured policy (all | admins_only | disabled)."""
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"login:{ip}", s.login_rate_limit_per_minute) or not limiter.allow(
        f"login-user:{body.email.lower()}", s.login_rate_limit_per_minute
    ):
        raise ServiceError(429, "rate_limited", "Too many login attempts. Please wait a minute and try again.")
    mode = local_login_mode(db)
    if mode == "disabled":
        raise ServiceError(403, "local_login_disabled", "Password sign-in is disabled. Please sign in with SSO.")
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower(), User.deleted_at.is_(None))).first()
    ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        audit.record_detached("auth.login_failed", None, entity_type="user", entity_id=body.email.lower(),
                              reason="Invalid credentials or inactive account")
        raise ServiceError(401, "invalid_credentials", "Invalid email or password.")
    if mode == "admins_only" and not user.is_admin:
        audit.record_detached("auth.login_failed", user, entity_type="user", entity_id=user.id,
                              reason="Password sign-in restricted to administrators")
        raise ServiceError(403, "local_login_disabled", "Password sign-in is restricted. Please sign in with SSO.")
    user.last_login_at = now_utc()
    user.last_login_method = "password"
    audit.record(db, "auth.login", user, entity_type="user", entity_id=user.id, new={"method": "password"})
    commit(db)
    csrf = set_session_cookies(response, user)
    return {"user": user_out(user), "csrf_token": csrf}


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ends the local session. If the session came from an SSO provider with single logout enabled,
    the response includes ``sso_logout_url`` for the browser to visit (RP-initiated logout)."""
    from ..services import sso

    s = get_settings()
    claims = decode_session_token(request.cookies.get(s.session_cookie_name, "")) or {}
    if claims.get("act"):  # signing out while acting only ends the acting session; the target's sessions are untouched
        return _end_acting(request, response, user, db)
    logout_url = None
    if claims.get("sso"):
        p = db.scalars(select(SSOProvider).where(SSOProvider.slug == claims["sso"])).first()
        if p is not None:
            logout_url = sso.logout_url(db, p)
    user.token_version += 1  # revoke all existing sessions for this user
    audit.record(db, "auth.logout", user, entity_type="user", entity_id=user.id,
                 new={"sso": claims.get("sso"), "single_logout": bool(logout_url)})
    commit(db)
    response.delete_cookie(s.session_cookie_name, path="/")
    response.delete_cookie(s.csrf_cookie_name, path="/")
    return {"ok": True, "sso_logout_url": logout_url}


@router.get("/me")
def me(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = get_settings()
    claims = decode_session_token(request.cookies.get(s.session_cookie_name, "")) or {}
    provider = db.get(SSOProvider, user.sso_provider_id) if user.sso_provider_id else None
    acting = None
    if claims.get("act"):
        a = getattr(request.state, "acting_admin", None)
        acting = {"admin_name": a.full_name if a else None, "admin_email": a.email if a else claims.get("ae"),
                  "expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat()}
    return {"user": user_out(user, provider.display_name if provider else None),
            "csrf_token": request.cookies.get(s.csrf_cookie_name), "auth_method": claims.get("amr", "pwd"),
            "acting_as": acting}


@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if getattr(request.state, "acting_admin", None) is not None:
        raise ServiceError(403, "forbidden", "Passwords cannot be changed while acting as another user.")
    if user.password_hash is None:
        raise bad_request("This account signs in with SSO and has no local password.", "sso_account")
    if not verify_password(body.current_password, user.password_hash):
        raise ServiceError(401, "invalid_credentials", "Current password is incorrect.")
    err = validate_password_strength(body.new_password)
    if err:
        raise bad_request(err)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit.record(db, "auth.password_changed", user, entity_type="user", entity_id=user.id)
    commit(db)
    set_session_cookies(response, user)
    return {"ok": True}


# ---------------------------------------------------------------- admin "Act as"
@router.post("/act-as/exit")
def act_as_exit(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ends an 'Act as' session and puts the administrator back in their own session."""
    if getattr(request.state, "acting_admin", None) is None:
        raise bad_request("You are not acting as another user.")
    return _end_acting(request, response, user, db)


def _end_acting(request: Request, response: Response, target: User, db: Session):
    admin = request.state.acting_admin
    audit.record(db, "admin.act_as_ended", target, entity_type="user", entity_id=target.id,
                 new={"admin": admin.email, "target": target.email})
    commit(db)
    csrf = set_session_cookies(response, admin)
    return {"ok": True, "acting_ended": True, "user": user_out(admin), "csrf_token": csrf}


@router.post("/act-as/{user_id}")
def act_as_start(user_id: uuid.UUID, response: Response, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """An administrator starts acting as another (non-admin) user. Time-limited; every action is audited with the real admin."""
    target = db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise ServiceError(404, "not_found", "User not found.")
    if target.id == admin.id:
        raise bad_request("You cannot act as yourself.")
    if not target.is_active:
        raise bad_request("This user is disabled.")
    if target.is_admin:
        raise bad_request("You cannot act as another administrator.")
    audit.record(db, "admin.act_as_started", admin, entity_type="user", entity_id=target.id,
                 new={"admin": admin.email, "target": target.email, "target_role": target.role_name,
                      "minutes": get_settings().act_as_minutes})
    commit(db)
    csrf = set_session_cookies(response, target, act=admin)
    return {"user": user_out(target), "csrf_token": csrf}
