"""FastAPI dependencies for authentication and role-based authorisation.

``require_admin`` is applied at ROUTER level to every /api/admin/* route, so no
admin endpoint can be added without it. Denied attempts are audited.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import ServiceError
from .models import User
from .security import csrf_valid, decode_session_token
from .services import audit

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    s = get_settings()
    token = request.cookies.get(s.session_cookie_name)
    claims = decode_session_token(token) if token else None
    if not claims:
        raise ServiceError(401, "not_authenticated", "Authentication required.")
    try:
        user = db.get(User, uuid.UUID(claims["sub"]))
    except ValueError:
        user = None
    if user is None or not user.is_active or user.deleted_at is not None or user.token_version != claims["tv"]:
        raise ServiceError(401, "not_authenticated", "Session is no longer valid. Please sign in again.")
    if request.method in UNSAFE_METHODS:
        if not csrf_valid(request.headers.get("X-CSRF-Token"), request.cookies.get(s.csrf_cookie_name), claims["csrf"]):
            raise ServiceError(403, "csrf_failed", "CSRF validation failed. Refresh the page and try again.")
    request.state.user = user
    return user


def require_admin(request: Request, user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        is_force = "force" in request.url.path or request.headers.get("X-Force-Allocate")
        audit.record_detached(
            "authorization.denied", user, entity_type="endpoint", entity_id=f"{request.method} {request.url.path}",
            reason="Force Allocate attempt by non-admin" if is_force else "Non-admin attempted to access an admin endpoint",
        )
        raise ServiceError(403, "forbidden", "Administrator privileges are required.")
    return user
