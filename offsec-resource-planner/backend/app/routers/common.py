from __future__ import annotations

from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import ServiceError, conflict
from ..services.availability import UNAVAILABLE_MESSAGE


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        if "uq_lock_resource_day_active" in str(e.orig):
            raise conflict(UNAVAILABLE_MESSAGE, "resource_unavailable") from None
        raise conflict("The change conflicts with existing data.", "integrity_error") from None


def parse_range(start: date | None, end: date | None, default_days: int = 31) -> tuple[date, date]:
    from datetime import timedelta

    if start is None:
        start = date.today().replace(day=1)
    if end is None:
        end = start + timedelta(days=default_days)
    if end < start:
        raise ServiceError(422, "validation_error", "end must be on or after start")
    return start, end
