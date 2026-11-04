"""Symmetric encryption for secrets that must live in the database (e.g. SSO client secrets).

Fernet = AES-128-CBC + HMAC-SHA256 with authenticated timestamps. The key comes from
HACKEDULER_ENCRYPTION_KEY, or is derived from HACKEDULER_SECRET_KEY with domain separation when unset.
Encrypted values are never returned by any API.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    raw = s.encryption_key.strip()
    if raw:
        try:
            if len(base64.urlsafe_b64decode(raw.encode())) == 32:
                return Fernet(raw.encode())
        except Exception:  # noqa: BLE001 - not a Fernet key; derive from it instead
            pass
        material = raw.encode()
    else:
        # NOTE: label kept from the original name so secrets already encrypted stay readable.
        material = b"orp-encryption-v1:" + s.secret_key.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str, ttl: int | None = None) -> str:
    """Raises ValueError if the token is invalid, tampered with, or older than ``ttl`` seconds."""
    try:
        return _fernet().decrypt(token.encode(), ttl=ttl).decode()
    except (InvalidToken, ValueError) as e:
        raise ValueError("invalid or expired encrypted value") from e
