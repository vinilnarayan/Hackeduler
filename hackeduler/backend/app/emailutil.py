"""POC emails: a booking can notify several people. They are stored in the one ``poc_email`` text column as a
normalised ``a@x.com, b@y.com`` list, so no schema change is needed."""
from __future__ import annotations

import re

from pydantic import EmailStr, TypeAdapter

MAX_POC_EMAILS = 10
_email = TypeAdapter(EmailStr)


def split_emails(value: str | None) -> list[str]:
    """Split a stored/typed list on commas, semicolons and whitespace (no validation)."""
    return [p for p in re.split(r"[,;\s]+", value or "") if p]


def normalize_poc_emails(value: str) -> str:
    """Validate every address and return them de-duplicated as ``a@x.com, b@y.com``."""
    parts = split_emails(value)
    if not parts:
        raise ValueError("Enter at least one email address.")
    if len(parts) > MAX_POC_EMAILS:
        raise ValueError(f"Enter at most {MAX_POC_EMAILS} email addresses.")
    out: list[str] = []
    for p in parts:
        try:
            addr = _email.validate_python(p)
        except Exception:
            raise ValueError(f"'{p}' is not a valid email address.") from None
        if addr.lower() not in (o.lower() for o in out):
            out.append(addr)
    return ", ".join(out)
