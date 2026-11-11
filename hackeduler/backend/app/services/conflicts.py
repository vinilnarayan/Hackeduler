"""Scheduling conflict detection and flagging.

Policy: changes to holidays, leave or resource status NEVER move, cancel or
reassign bookings. Instead the affected bookings are flagged (needs_review) and
a ``booking_conflicts`` row is opened for an admin to resolve.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Booking, BookingConflict, BookingResourceLock, BookingStatus, LockStatus, User
from . import audit, notifications


def _existing_open(db: Session, booking_id: uuid.UUID, source_ref: str | None, conflict_type: str) -> BookingConflict | None:
    q = select(BookingConflict).where(
        BookingConflict.booking_id == booking_id,
        BookingConflict.status == "open",
        BookingConflict.conflict_type == conflict_type,
    )
    q = q.where(BookingConflict.source_ref == source_ref) if source_ref else q.where(BookingConflict.source_ref.is_(None))
    return db.scalars(q).first()


def open_conflict(
    db: Session,
    booking: Booking,
    conflict_type: str,
    description: str,
    actor: User | None,
    *,
    conflicting_booking_id: uuid.UUID | None = None,
    start: date | None = None,
    end: date | None = None,
    source_ref: str | None = None,
    notify_poc: bool = True,
) -> BookingConflict | None:
    if source_ref and _existing_open(db, booking.id, source_ref, conflict_type):
        return None
    c = BookingConflict(
        id=uuid.uuid4(),
        booking_id=booking.id,
        conflicting_booking_id=conflicting_booking_id,
        resource_id=booking.resource_id,
        conflict_type=conflict_type,
        description=description,
        conflict_start_date=start,
        conflict_end_date=end,
        source_ref=source_ref,
    )
    db.add(c)
    booking.needs_review = True
    audit.record(
        db, "conflict.flagged", actor, entity_type="booking_conflict", entity_id=c.id, booking_id=booking.id,
        new={"conflict_type": conflict_type, "description": description,
             "conflicting_booking_id": conflicting_booking_id, "start": start, "end": end},
    )
    if notify_poc and booking.status == BookingStatus.APPROVED:
        notifications.notify_impacted(db, booking, description)
    return c


def bookings_locking_dates(db: Session, dates: set[date], resource_id: uuid.UUID | None = None) -> dict[uuid.UUID, list[date]]:
    """Active bookings holding reservations on any of ``dates``."""
    if not dates:
        return {}
    q = (
        select(BookingResourceLock.booking_id, BookingResourceLock.work_date)
        .join(Booking, Booking.id == BookingResourceLock.booking_id)
        .where(
            BookingResourceLock.work_date.in_(list(dates)),
            BookingResourceLock.lock_status.in_(LockStatus.ACTIVE),
            Booking.status.in_(BookingStatus.ACTIVE),
        )
    )
    if resource_id is not None:
        q = q.where(BookingResourceLock.resource_id == resource_id)
    out: dict[uuid.UUID, list[date]] = {}
    for bid, d in db.execute(q).all():
        out.setdefault(bid, []).append(d)
    return out


def bookings_spanning_dates(db: Session, dates: set[date], resource_id: uuid.UUID | None = None) -> list[Booking]:
    """Active bookings whose [start, end] range includes any of ``dates`` (used when a non-working day is removed)."""
    if not dates:
        return []
    lo, hi = min(dates), max(dates)
    q = select(Booking).where(Booking.status.in_(BookingStatus.ACTIVE), Booking.start_date <= hi, Booking.end_date >= lo)
    if resource_id is not None:
        q = q.where(Booking.uses_resource(resource_id))
    return [b for b in db.scalars(q).unique() if any(b.start_date <= d <= b.end_date for d in dates)]


def flag_new_non_working(
    db: Session, dates: set[date], conflict_type: str, label: str, source_ref: str, actor: User | None,
    resource_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """A holiday/leave now covers ``dates``: flag every active booking reserving those dates."""
    affected = bookings_locking_dates(db, dates, resource_id)
    for bid, ds in affected.items():
        b = db.get(Booking, bid)
        ds = sorted(ds)
        desc = (
            f"{label} now falls on reserved working day(s) {', '.join(d.isoformat() for d in ds)}. "
            "The booking has not been changed; review whether it must be extended, rescheduled or reassigned."
        )
        open_conflict(db, b, conflict_type, desc, actor, start=ds[0], end=ds[-1], source_ref=source_ref)
    return list(affected.keys())


def flag_removed_non_working(
    db: Session, dates: set[date], conflict_type: str, label: str, source_ref: str, actor: User | None,
    resource_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """A holiday/leave was removed: bookings spanning those dates may now finish earlier."""
    ids = []
    for b in bookings_spanning_dates(db, dates, resource_id):
        ds = sorted(d for d in dates if b.start_date <= d <= b.end_date)
        desc = (
            f"{label} was removed/changed; {', '.join(d.isoformat() for d in ds)} may now be working day(s) within this "
            "booking. The booking has not been changed; review whether its schedule should be recalculated."
        )
        if open_conflict(db, b, conflict_type, desc, actor, start=ds[0], end=ds[-1], source_ref=source_ref, notify_poc=False):
            ids.append(b.id)
    return ids


def flag_inactive_resource(db: Session, resource, from_date: date, actor: User | None) -> list[uuid.UUID]:
    """Flag every active booking on ``resource`` that runs on or after ``from_date`` (the deactivation date).

    Bookings are never moved or cancelled; admins reassign/reschedule via the conflict workflow.
    """
    q = select(Booking).where(
        Booking.uses_resource(resource.id), Booking.status.in_(BookingStatus.ACTIVE), Booking.end_date >= from_date
    )
    ids = []
    for b in db.scalars(q).unique():
        desc = (f"{resource.display_name} ({resource.engineer_name}) is inactive from {from_date.strftime('%d %b %Y')}, "
                f"but this booking runs {b.start_date.strftime('%d %b %Y')} – {b.end_date.strftime('%d %b %Y')}. "
                "The booking has not been changed; reassign it to another resource or reschedule it.")
        if open_conflict(db, b, "inactive_resource", desc, actor, start=max(b.start_date, from_date), end=b.end_date,
                         source_ref=f"resource:{resource.id}:inactive:{from_date.isoformat()}"):
            ids.append(b.id)
    return ids


def resolve(db: Session, conflict: BookingConflict, actor: User, note: str) -> None:
    prev = {"status": conflict.status}
    conflict.status = "resolved"
    conflict.resolution_note = note
    conflict.resolved_by = actor.id
    from .availability import now_utc

    conflict.resolved_at = now_utc()
    db.flush()
    audit.record(db, "conflict.resolved", actor, entity_type="booking_conflict", entity_id=conflict.id,
                 booking_id=conflict.booking_id, previous=prev, new={"status": "resolved"}, reason=note)
    for bid in {conflict.booking_id, conflict.conflicting_booking_id} - {None}:
        still_open = db.scalar(
            select(BookingConflict.id).where(
                BookingConflict.status == "open",
                (BookingConflict.booking_id == bid) | (BookingConflict.conflicting_booking_id == bid),
            ).limit(1)
        )
        if not still_open:
            b = db.get(Booking, bid)
            if b is not None:
                b.needs_review = False
