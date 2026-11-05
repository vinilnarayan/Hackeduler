"""Append-only audit trail.

Audit events are written in the SAME transaction as the change they describe, so
an audited change and its audit record commit or roll back together. Failed
operations / denied authorisation attempts are recorded via ``record_detached``
which uses its own short transaction (the business transaction is rolled back).
"""
from __future__ import annotations

import enum
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..context import client_ip_var, request_id_var
from ..models import AuditLog, Booking, User

log = logging.getLogger(__name__)

BOOKING_SNAPSHOT_FIELDS = (
    "status", "resource_id", "requires_resource", "product_id", "implementation_id", "activity_type_id", "activity_name_snapshot", "base_duration_snapshot",
    "additional_days", "duration_days", "duration_overridden", "application_name", "application_version",
    "pci_dss_scope", "poc_name", "poc_email", "additional_comments", "start_date", "end_date",
    "is_force_allocated", "needs_review", "rejection_reason", "cancellation_reason", "version",
)


def jsonable(v: Any) -> Any:
    if isinstance(v, (uuid.UUID, Decimal)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [jsonable(x) for x in v]
    return v


def booking_snapshot(b: Booking) -> dict[str, Any]:
    snap = {f: jsonable(getattr(b, f)) for f in BOOKING_SNAPSHOT_FIELDS}
    if b.resource is not None and b.resource.id == b.resource_id:
        snap["resource_code"] = b.resource.code
    return snap


def record(
    db: Session,
    action: str,
    actor: User | None,
    *,
    entity_type: str,
    entity_id: Any = None,
    booking_id: uuid.UUID | None = None,
    previous: Any = None,
    new: Any = None,
    reason: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        id=uuid.uuid4(),
        booking_id=booking_id,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        action=action,
        previous_value=jsonable(previous),
        new_value=jsonable(new),
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else "system",
        actor_role=actor.role_name if actor else "system",
        reason=reason,
        request_id=request_id_var.get(),
        ip_address=client_ip_var.get(),
    )
    db.add(entry)
    return entry


def record_detached(action: str, actor: User | None, **kw) -> None:
    """Write an audit entry in an independent transaction (for failures/denials)."""
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        record(db, action, actor, **kw)
        db.commit()
    except Exception:  # never let audit failure mask the original error
        db.rollback()
        log.exception("failed to write detached audit entry %s", action)
    finally:
        db.close()
