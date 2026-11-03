from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import ServiceError, bad_request
from ..models import User
from ..schemas import LoginIn, PasswordChange, UserOut
from ..security import (
    create_session_token,
    hash_password,
    limiter,
    validate_password_strength,
    verify_password,
)
from ..services import audit
from ..services.availability import now_utc
from .common import commit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role_name, is_active=u.is_active,
                   last_login_at=u.last_login_at)


def _set_session(response: Response, user: User) -> str:
    s = get_settings()
    token, csrf = create_session_token(user.id, user.token_version)
    max_age = s.session_hours * 3600
    response.set_cookie(s.session_cookie_name, token, max_age=max_age, httponly=True, secure=s.cookie_secure,
                        samesite="lax", path="/")
    response.set_cookie(s.csrf_cookie_name, csrf, max_age=max_age, httponly=False, secure=s.cookie_secure,
                        samesite="strict", path="/")
    return csrf


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"login:{ip}", s.login_rate_limit_per_minute) or not limiter.allow(
        f"login-user:{body.email.lower()}", s.login_rate_limit_per_minute
    ):
        raise ServiceError(429, "rate_limited", "Too many login attempts. Please wait a minute and try again.")
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        audit.record_detached("auth.login_failed", None, entity_type="user", entity_id=body.email.lower(),
                              reason="Invalid credentials or inactive account")
        raise ServiceError(401, "invalid_credentials", "Invalid email or password.")
    user.last_login_at = now_utc()
    audit.record(db, "auth.login", user, entity_type="user", entity_id=user.id)
    commit(db)
    csrf = _set_session(response, user)
    return {"user": user_out(user), "csrf_token": csrf}


@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = get_settings()
    user.token_version += 1  # revoke all existing sessions for this user
    audit.record(db, "auth.logout", user, entity_type="user", entity_id=user.id)
    commit(db)
    response.delete_cookie(s.session_cookie_name, path="/")
    response.delete_cookie(s.csrf_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: User = Depends(get_current_user)):
    return {"user": user_out(user), "csrf_token": request.cookies.get(get_settings().csrf_cookie_name)}


@router.post("/change-password")
def change_password(body: PasswordChange, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise ServiceError(401, "invalid_credentials", "Current password is incorrect.")
    err = validate_password_strength(body.new_password)
    if err:
        raise bad_request(err)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit.record(db, "auth.password_changed", user, entity_type="user", entity_id=user.id)
    commit(db)
    _set_session(response, user)
    return {"ok": True}
