"""Password hashing, session tokens and CSRF.

Sessions: a signed JWT in an HttpOnly, SameSite=Lax cookie (Secure in production).
The token carries only the user id, a token_version (for server-side revocation
on logout / password change / deactivation) and the CSRF token it is bound to.
The user's ROLE is NOT trusted from the token - it is reloaded from the database
on every request, so client-side role manipulation has no effect.

CSRF: double-submit. A non-HttpOnly cookie holds a random token that the SPA
echoes in the ``X-CSRF-Token`` header on unsafe methods. The value must match
both the cookie and the value bound inside the signed session token.
"""
from __future__ import annotations

import hmac
import secrets
import time
import uuid
from collections import defaultdict, deque
from threading import Lock

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import get_settings

_ph = PasswordHasher()
_DUMMY_HASH = _ph.hash("timing-equaliser-not-a-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_password_strength(pw: str) -> str | None:
    if len(pw) < 12:
        return "Password must be at least 12 characters."
    classes = sum([any(c.islower() for c in pw), any(c.isupper() for c in pw), any(c.isdigit() for c in pw),
                   any(not c.isalnum() for c in pw)])
    if classes < 3:
        return "Password must contain at least three of: lowercase, uppercase, digit, symbol."
    return None


def create_session_token(user_id: uuid.UUID, token_version: int, sso: str | None = None) -> tuple[str, str]:
    s = get_settings()
    csrf = secrets.token_urlsafe(32)
    now = int(time.time())
    claims = {"sub": str(user_id), "tv": token_version, "csrf": csrf, "iat": now, "exp": now + s.session_hours * 3600,
              "iss": "orp", "amr": "sso" if sso else "pwd"}
    if sso:
        claims["sso"] = sso
    return jwt.encode(claims, s.secret_key, algorithm="HS256"), csrf


def decode_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"], issuer="orp",
                          options={"require": ["sub", "exp", "tv", "csrf"]})
    except jwt.PyJWTError:
        return None


def csrf_valid(header: str | None, cookie: str | None, bound: str | None) -> bool:
    if not header or not cookie or not bound:
        return False
    return hmac.compare_digest(header, cookie) and hmac.compare_digest(header, bound)


class SlidingWindowLimiter:
    """Simple in-process rate limiter. For multi-instance deployments use a shared store (e.g. Redis)."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50_000:  # bound memory
                for k in list(self._hits)[:10_000]:
                    if not self._hits[k]:
                        del self._hits[k]
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()
