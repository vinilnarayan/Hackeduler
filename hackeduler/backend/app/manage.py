"""Small admin CLI.

    python -m app.manage create-admin <email> [<password>]   # create (or reset) a local administrator
    python -m app.manage count-users                         # prints the number of non-deleted users

create-admin never touches other data. If the account exists it is re-activated, made admin,
and its password reset.
"""
from __future__ import annotations

import secrets
import sys
import uuid

from sqlalchemy import func, select

from .db import SessionLocal
from .models import ROLE_ADMIN_ID, User
from .security import hash_password, validate_password_strength
from .services import audit


def create_admin(email: str, password: str | None) -> None:
    password = password or secrets.token_urlsafe(14) + "!A1"
    err = validate_password_strength(password)
    if err:
        sys.exit(err)
    db = SessionLocal()
    try:
        u = db.scalars(select(User).where(func.lower(User.email) == email.lower(), User.deleted_at.is_(None))).first()
        action = "user.admin_reset_cli" if u else "user.admin_created_cli"
        if u is None:
            u = User(id=uuid.uuid4(), email=email.lower(), full_name="Administrator", password_hash=hash_password(password),
                     role_id=ROLE_ADMIN_ID)
            db.add(u)
        else:
            u.password_hash, u.role_id, u.is_active = hash_password(password), ROLE_ADMIN_ID, True
            u.token_version += 1
        db.flush()
        audit.record(db, action, None, entity_type="user", entity_id=u.id, new={"email": u.email})
        db.commit()
        print(f"Administrator: {u.email}\nPassword:      {password}")
    finally:
        db.close()


def count_users() -> None:
    db = SessionLocal()
    try:
        print(db.scalar(select(func.count()).select_from(User).where(User.deleted_at.is_(None))) or 0)
    finally:
        db.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "create-admin":
        create_admin(args[1], args[2] if len(args) > 2 else None)
    elif args == ["count-users"]:
        count_users()
    else:
        sys.exit(__doc__)
