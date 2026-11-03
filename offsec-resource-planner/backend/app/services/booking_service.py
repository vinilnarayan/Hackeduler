"""Booking lifecycle service.

Concurrency strategy (see docs/ARCHITECTURE.md):
 1. Every operation that creates or moves a reservation first takes a row lock
    (``SELECT ... FOR UPDATE``) on the affected ``security_resources`` row(s),
    in a deterministic order. This serialises all reservation changes for a
    resource, so the availability check and the lock insert are atomic.
 2. As a second, independent guarantee, ``booking_resource_locks`` has a partial
    UNIQUE index on (resource_id, work_date) for active, non-forced locks. Even if
    (1) were bypassed, PostgreSQL rejects the second overlapping reservation and
    we translate the IntegrityError into a clean 409 response.
 3. Old reservations are released and new ones inserted in the SAME transaction,
    so a reschedule/reassignment either fully commits or leaves the original
    reservation untouched.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import ServiceError, bad_request, conflict, forbidden, not_found
from ..models import (
    ActivityType,
    Booking,
    BookingChangeRequest,
    BookingResourceLock,
    BookingStatus,
    BookingStatusHistory,
    LockStatus,
    SecurityResource,
    User,
)
from . import audit, conflicts, notifications, settings_service
from .availability import (
    UNAVAILABLE_MESSAGE,
    SchedulePlan,
    ScheduleIssue,
    alternative_resources,
    now_utc,
    plan_schedule,
    suggest_next_start,
    total_duration,
)
from .calendar_engine import SchedulingError

FORCE_WARNING = (
    "Warning: This allocation conflicts with an existing booking or resource restriction. "
    "Proceeding may impact another scheduled assessment. Please confirm that you have reviewed "
    "the conflict and have authorization to proceed."
)


@dataclass
class ForceOptions:
    confirm: bool
    reason: str


@dataclass
class BookingInput:
    application_name: str
    application_version: str
    activity_type_id: uuid.UUID
    pci_dss_scope: bool
    resource_id: uuid.UUID
    start_date: date
    poc_name: str
    poc_email: str
    additional_comments: str | None = None
    additional_days: int = 0


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def lock_resources(db: Session, resource_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityResource]:
    out = {}
    for rid in sorted(set(resource_ids), key=str):
        r = db.scalars(
            select(SecurityResource).where(SecurityResource.id == rid).with_for_update().execution_options(populate_existing=True)
        ).first()
        if r is None:
            raise not_found("Resource")
        out[rid] = r
    return out


def lock_booking(db: Session, booking_id: uuid.UUID) -> Booking:
    b = db.scalars(
        select(Booking).where(Booking.id == booking_id).with_for_update(of=Booking).execution_options(populate_existing=True)
    ).unique().first()
    if b is None:
        raise not_found("Booking")
    return b


def _set_status(db: Session, b: Booking, new: str, actor: User | None, reason: str | None = None) -> None:
    db.add(BookingStatusHistory(id=uuid.uuid4(), booking_id=b.id, from_status=b.status, to_status=new,
                                changed_by=actor.id if actor else None, reason=reason))
    b.status = new


def _release_locks(db: Session, booking_id: uuid.UUID) -> None:
    db.execute(
        update(BookingResourceLock)
        .where(BookingResourceLock.booking_id == booking_id, BookingResourceLock.lock_status.in_(LockStatus.ACTIVE))
        .values(lock_status=LockStatus.RELEASED, updated_at=now_utc())
    )


def _active_lock_dates(db: Session, booking_id: uuid.UUID) -> list[date]:
    return list(db.scalars(
        select(BookingResourceLock.work_date)
        .where(BookingResourceLock.booking_id == booking_id, BookingResourceLock.lock_status.in_(LockStatus.ACTIVE))
        .order_by(BookingResourceLock.work_date)
    ))


def _write_locks(db: Session, b: Booking, plan: SchedulePlan, status: str, forced: bool, expires_at) -> None:
    forced_dates = set(plan.conflict_dates) if forced else set()
    for d in plan.work_dates:
        db.add(BookingResourceLock(id=uuid.uuid4(), booking_id=b.id, resource_id=plan.resource.id, work_date=d,
                                   lock_status=status, is_forced=d in forced_dates, expires_at=expires_at))
    try:
        db.flush()
    except IntegrityError as e:
        if "uq_lock_resource_day_active" in str(e.orig):
            raise conflict(UNAVAILABLE_MESSAGE, "resource_unavailable") from None
        raise


def _pending_expiry(db: Session):
    if settings_service.get_setting(db, "pending_expiry_enabled"):
        return now_utc() + timedelta(hours=int(settings_service.get_setting(db, "pending_expiry_hours")))
    return None


def _is_expired(db: Session, b: Booking) -> bool:
    return bool(b.status == BookingStatus.PENDING and b.expires_at and b.expires_at <= now_utc()
                and settings_service.get_setting(db, "pending_expiry_enabled"))


def _clean_text(value: str | None, field: str, *, required: bool = True, max_len: int = 255) -> str | None:
    v = (value or "").strip()
    if required and not v:
        raise bad_request(f"{field} is required.")
    if len(v) > max_len:
        raise bad_request(f"{field} must be at most {max_len} characters.")
    return v or None


def _get_activity(db: Session, activity_type_id: uuid.UUID, *, must_be_active: bool = True) -> ActivityType:
    a = db.get(ActivityType, activity_type_id)
    if a is None:
        raise bad_request("Unknown activity type.")
    if must_be_active and not a.is_active:
        raise bad_request("The selected activity type is not available for new bookings.")
    return a


def ensure_force_allowed(actor: User, force: ForceOptions | None, *, booking_id=None) -> None:
    """Force Allocate is ADMIN-ONLY. Enforced here in the service layer in addition to the admin router."""
    if force is None:
        return
    if not actor.is_admin:
        audit.record_detached("force_allocate.denied", actor, entity_type="booking", entity_id=booking_id,
                              booking_id=booking_id, reason="Non-admin attempted Force Allocate")
        raise forbidden("Force Allocate is restricted to administrators.")
    if not force.confirm:
        raise bad_request("Explicit confirmation is required to force allocate.", "confirmation_required",
                          {"warning": FORCE_WARNING})
    if not (force.reason or "").strip():
        raise bad_request("An override reason is required to force allocate.", "override_reason_required",
                          {"warning": FORCE_WARNING})
    if len(force.reason) > 2000:
        raise bad_request("Override reason is too long.")


def _issues_json(issues: list[ScheduleIssue], *, include_booking_ids: bool) -> list[dict]:
    out = []
    for i in issues:
        d = {"type": i.type, "message": i.message, "dates": i.dates}
        if include_booking_ids:
            d["booking_ids"] = i.booking_ids
        out.append(d)
    return out


def _plan_json(plan: SchedulePlan) -> dict:
    return {"resource_id": str(plan.resource.id), "start_date": plan.start_date.isoformat(),
            "end_date": plan.end_date.isoformat() if plan.end_date else None, "duration_days": plan.duration_days,
            "work_dates": [d.isoformat() for d in plan.work_dates]}


def _evaluate(db: Session, plan: SchedulePlan, actor: User, force: ForceOptions | None, extra: list[ScheduleIssue] | None = None) -> bool:
    """Return True if the allocation proceeds as a Force Allocate; raise if blocked."""
    issues = plan.issues + (extra or [])
    if not issues:
        return False
    if force is not None and actor.is_admin:
        return True
    if actor.is_admin:
        conflicting = []
        for bid in plan.conflicting_booking_ids:
            cb = db.get(Booking, bid)
            if cb:
                conflicting.append({"id": str(cb.id), "application_name": cb.application_name, "status": cb.status,
                                    "start_date": cb.start_date.isoformat(), "end_date": cb.end_date.isoformat(),
                                    "poc_name": cb.poc_name, "poc_email": cb.poc_email})
        raise conflict(
            issues[0].message, "override_required",
            {"requires_force": True, "warning": FORCE_WARNING, "issues": _issues_json(issues, include_booking_ids=True),
             "conflicting_bookings": conflicting, "plan": _plan_json(plan)},
        )
    first = issues[0]
    msg = UNAVAILABLE_MESSAGE if first.type == "overlapping_booking" else first.message
    raise conflict(msg, "resource_unavailable", {"issues": _issues_json(issues, include_booking_ids=False)})


def _record_force(db: Session, admin: User, b: Booking, plan: SchedulePlan, force: ForceOptions,
                  issues: list[ScheduleIssue], previous_allocation: dict | None) -> list[str]:
    b.is_force_allocated = True
    affected_pocs = []
    new_alloc = {"resource_id": str(plan.resource.id), "resource_code": plan.resource.code,
                 "start_date": plan.start_date.isoformat(), "end_date": plan.end_date.isoformat() if plan.end_date else None,
                 "work_dates": [d.isoformat() for d in plan.work_dates]}
    span = (plan.work_dates[0], plan.work_dates[-1]) if plan.work_dates else (plan.start_date, plan.start_date)
    for cid in plan.conflicting_booking_ids:
        cb = db.get(Booking, cid)
        if cb is None:
            continue
        overlap = sorted(d for d in plan.conflict_dates)
        desc = (f"Force Allocate of booking {b.id} overlaps booking {cb.id} on "
                f"{', '.join(d.isoformat() for d in overlap)}. Neither booking was modified. Reason: {force.reason}")
        conflicts.open_conflict(db, b, "overlapping_booking", desc, admin, conflicting_booking_id=cb.id,
                                start=overlap[0] if overlap else None, end=overlap[-1] if overlap else None,
                                source_ref=f"force:{b.id}:{cb.id}:{b.version}", notify_poc=False)
        cb.needs_review = True
        affected_pocs.append(cb.poc_email)
        if cb.status == BookingStatus.APPROVED:
            notifications.notify_impacted(db, cb, (
                f"Another assessment has been allocated by an administrator to the same resource on "
                f"{', '.join(d.isoformat() for d in overlap)}. Your booking has not been changed and is under review."))
    for issue in issues:
        if issue.type == "overlapping_booking":
            continue
        ctype = {"inactive_resource": "inactive_resource", "schedule_changed": "manual_override"}.get(issue.type, "manual_override")
        conflicts.open_conflict(db, b, ctype, f"Force Allocate overrode restriction: {issue.message}", admin,
                                start=span[0], end=span[1], source_ref=f"force:{b.id}:{issue.type}:{b.version}", notify_poc=False)
    conflicts.open_conflict(
        db, b, "manual_override",
        f"Manual override (Force Allocate) by {admin.email}. Reason: {force.reason}", admin,
        start=span[0], end=span[1], source_ref=f"force:{b.id}:override:{b.version}", notify_poc=False,
    )
    audit.record(
        db, "booking.force_allocated", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
        previous={"allocation": previous_allocation},
        new={"allocation": new_alloc, "issues": _issues_json(issues, include_booking_ids=True),
             "conflicting_booking_ids": [str(x) for x in plan.conflicting_booking_ids],
             "affected_dates": [d.isoformat() for d in plan.conflict_dates], "affected_poc_emails": affected_pocs,
             "warning_acknowledged": FORCE_WARNING},
        reason=force.reason,
    )
    return affected_pocs


# --------------------------------------------------------------------------------------
# expiry / completion (also called by the worker)
# --------------------------------------------------------------------------------------

def expire_stale_pending(db: Session, resource_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    if not settings_service.get_setting(db, "pending_expiry_enabled"):
        return []
    q = select(Booking).where(Booking.status == BookingStatus.PENDING, Booking.expires_at.is_not(None),
                              Booking.expires_at <= now_utc())
    if resource_id is not None:
        q = q.where(Booking.resource_id == resource_id)
    ids = []
    for b in db.scalars(q.with_for_update(of=Booking, skip_locked=True)).unique().all():
        _release_locks(db, b.id)
        _set_status(db, b, BookingStatus.EXPIRED, None, "Pending reservation expired without review")
        audit.record(db, "booking.expired", None, entity_type="booking", entity_id=b.id, booking_id=b.id,
                     previous={"status": BookingStatus.PENDING}, new={"status": BookingStatus.EXPIRED})
        notifications.notify_expired(db, b)
        ids.append(b.id)
    return ids


def complete_past_bookings(db: Session) -> list[uuid.UUID]:
    today = settings_service.org_today(db)
    q = select(Booking).where(Booking.status == BookingStatus.APPROVED, Booking.end_date < today)
    ids = []
    for b in db.scalars(q.with_for_update(of=Booking, skip_locked=True)).unique().all():
        _set_status(db, b, BookingStatus.COMPLETED, None, "Assessment window ended")
        audit.record(db, "booking.completed", None, entity_type="booking", entity_id=b.id, booking_id=b.id,
                     previous={"status": BookingStatus.APPROVED}, new={"status": BookingStatus.COMPLETED})
        ids.append(b.id)
    return ids


# --------------------------------------------------------------------------------------
# availability preview
# --------------------------------------------------------------------------------------

def preview(db: Session, actor: User, resource_id: uuid.UUID, activity_type_id: uuid.UUID, start: date,
            additional_days: int = 0, exclude_booking_id: uuid.UUID | None = None) -> dict[str, Any]:
    activity = _get_activity(db, activity_type_id)
    try:
        duration = total_duration(activity, additional_days)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)
    resource = db.get(SecurityResource, resource_id)
    if resource is None:
        raise not_found("Resource")
    if not actor.is_admin and not resource.is_active:
        raise not_found("Resource")
    plan = plan_schedule(db, resource, start, duration, exclude_booking_id=exclude_booking_id)
    issues = list(plan.issues)
    today = settings_service.org_today(db)
    if start < today:
        issues.insert(0, ScheduleIssue("past_date", "The start date cannot be in the past."))
    result: dict[str, Any] = {
        "available": not issues,
        "resource_id": str(resource.id),
        "resource_display_name": resource.display_name,
        "activity_type_id": str(activity.id),
        "activity_name": activity.name,
        "duration_days": duration,
        "start_date": start.isoformat(),
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
        "work_dates": [d.isoformat() for d in plan.work_dates],
        "issues": _issues_json(issues, include_booking_ids=actor.is_admin),
        "reason": None,
        "message": "The resource is available for the requested dates.",
        "suggested_start_date": None,
        "alternative_resources": [],
    }
    if issues:
        first = issues[0]
        result["reason"] = first.type
        result["message"] = UNAVAILABLE_MESSAGE if first.type == "overlapping_booking" else first.message
        nxt = suggest_next_start(db, resource, duration, max(start, today) + timedelta(days=1 if start >= today else 0),
                                 exclude_booking_id)
        result["suggested_start_date"] = nxt.isoformat() if nxt else None
        if start >= today:
            result["alternative_resources"] = [
                {"id": str(r.id), "display_name": r.display_name} for r in alternative_resources(db, resource.id, start, duration)
            ]
    return result


# --------------------------------------------------------------------------------------
# requester submission
# --------------------------------------------------------------------------------------

def _validate_input(inp: BookingInput) -> None:
    inp.application_name = _clean_text(inp.application_name, "Application Name")
    inp.application_version = _clean_text(inp.application_version, "Application Version", max_len=100)
    inp.poc_name = _clean_text(inp.poc_name, "POC Name")
    inp.poc_email = _clean_text(inp.poc_email, "POC Email", max_len=254)
    inp.additional_comments = _clean_text(inp.additional_comments, "Additional Comments", required=False, max_len=4000)


def submit_booking(db: Session, actor: User, inp: BookingInput) -> Booking:
    _validate_input(inp)
    activity = _get_activity(db, inp.activity_type_id)
    try:
        duration = total_duration(activity, inp.additional_days)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)
    if inp.start_date < settings_service.org_today(db):
        raise bad_request("The start date cannot be in the past.", "past_date")

    resource = lock_resources(db, [inp.resource_id])[inp.resource_id]  # serialises reservations on this resource
    if not resource.is_active and not actor.is_admin:
        raise conflict(f"{resource.display_name} is not accepting bookings.", "resource_unavailable")
    expire_stale_pending(db, resource.id)
    plan = plan_schedule(db, resource, inp.start_date, duration)   # re-validated server-side, never trusted from client
    _evaluate(db, plan, actor, None)

    expires_at = _pending_expiry(db)
    b = Booking(
        id=uuid.uuid4(), requester_id=actor.id, resource_id=resource.id, activity_type_id=activity.id,
        activity_name_snapshot=activity.name, base_duration_snapshot=activity.base_duration_days,
        additional_days=inp.additional_days, duration_days=duration, application_name=inp.application_name,
        application_version=inp.application_version, pci_dss_scope=inp.pci_dss_scope, poc_name=inp.poc_name,
        poc_email=inp.poc_email, additional_comments=inp.additional_comments, start_date=plan.start_date,
        end_date=plan.end_date, status=BookingStatus.PENDING, source="requester", expires_at=expires_at,
        submitted_at=now_utc(),
    )
    db.add(b)
    db.flush()
    db.add(BookingStatusHistory(id=uuid.uuid4(), booking_id=b.id, from_status=None, to_status=BookingStatus.PENDING,
                                changed_by=actor.id, reason="Submitted"))
    _write_locks(db, b, plan, LockStatus.PENDING, False, expires_at)
    db.refresh(b)
    audit.record(db, "booking.submitted", actor, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 new=audit.booking_snapshot(b))
    notifications.notify_submitted(db, b)
    return b


# --------------------------------------------------------------------------------------
# admin direct creation
# --------------------------------------------------------------------------------------

def admin_create_booking(db: Session, admin: User, inp: BookingInput, *, initial_status: str = BookingStatus.APPROVED,
                         duration_override: int | None = None, end_date_override: date | None = None,
                         force: ForceOptions | None = None, reason: str | None = None) -> Booking:
    if not admin.is_admin:
        raise forbidden()
    ensure_force_allowed(admin, force)
    if initial_status not in (BookingStatus.APPROVED, BookingStatus.PENDING):
        raise bad_request("Initial status must be approved or pending_approval.")
    _validate_input(inp)
    activity = _get_activity(db, inp.activity_type_id)
    if duration_override is not None:
        if duration_override <= 0:
            raise bad_request("Duration must be a positive integer.")
        duration = duration_override
    else:
        try:
            duration = total_duration(activity, inp.additional_days)
        except SchedulingError as e:
            raise bad_request(e.message, e.code)
    resource = lock_resources(db, [inp.resource_id])[inp.resource_id]
    expire_stale_pending(db, resource.id)
    try:
        plan = plan_schedule(db, resource, inp.start_date, duration, explicit_end_date=end_date_override)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)
    forced = _evaluate(db, plan, admin, force)

    approved = initial_status == BookingStatus.APPROVED
    expires_at = None if approved else _pending_expiry(db)
    b = Booking(
        id=uuid.uuid4(), requester_id=admin.id, resource_id=resource.id, activity_type_id=activity.id,
        activity_name_snapshot=activity.name, base_duration_snapshot=activity.base_duration_days,
        additional_days=inp.additional_days, duration_days=plan.duration_days,
        duration_overridden=duration_override is not None or end_date_override is not None,
        application_name=inp.application_name, application_version=inp.application_version,
        pci_dss_scope=inp.pci_dss_scope, poc_name=inp.poc_name, poc_email=inp.poc_email,
        additional_comments=inp.additional_comments, start_date=plan.start_date, end_date=plan.end_date,
        status=initial_status, source="admin", expires_at=expires_at, submitted_at=now_utc(),
        approved_by=admin.id if approved else None, approved_at=now_utc() if approved else None,
    )
    db.add(b)
    db.flush()
    db.add(BookingStatusHistory(id=uuid.uuid4(), booking_id=b.id, from_status=None, to_status=initial_status,
                                changed_by=admin.id, reason=reason or "Created by administrator"))
    _write_locks(db, b, plan, LockStatus.CONFIRMED if approved else LockStatus.PENDING, forced, expires_at)
    db.refresh(b)
    if forced:
        _record_force(db, admin, b, plan, force, plan.issues, previous_allocation=None)
    audit.record(db, "booking.admin_created", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 new=audit.booking_snapshot(b), reason=reason or (force.reason if force else None))
    if approved:
        notifications.notify_approved(db, b)
    return b


# --------------------------------------------------------------------------------------
# approve / reject / cancel
# --------------------------------------------------------------------------------------

def approve(db: Session, admin: User, booking_id: uuid.UUID, force: ForceOptions | None = None) -> Booking:
    if not admin.is_admin:
        raise forbidden()
    ensure_force_allowed(admin, force, booking_id=booking_id)
    b = lock_booking(db, booking_id)
    if b.status != BookingStatus.PENDING:
        raise conflict(f"Only pending bookings can be approved (current status: {BookingStatus.LABELS[b.status]}).", "invalid_state")
    if _is_expired(db, b):
        raise conflict("This request has expired and its reservation has been released.", "booking_expired")
    resource = lock_resources(db, [b.resource_id])[b.resource_id]
    locked = _active_lock_dates(db, b.id)

    # Revalidate against the CURRENT calendar - never trust the state at submission time.
    plan = plan_schedule(db, resource, b.start_date, b.duration_days, exclude_booking_id=b.id)
    extra: list[ScheduleIssue] = []
    if plan.work_dates != locked:
        extra.append(ScheduleIssue(
            "schedule_changed",
            f"The working calendar changed after submission (holiday/leave). The reserved dates no longer match a "
            f"{b.duration_days}-working-day schedule (recalculated end date: {plan.end_date}). Modify the booking to "
            f"recalculate before approving.",
            dates=sorted({d.isoformat() for d in set(plan.work_dates) ^ set(locked)}),
        ))
    forced = _evaluate(db, plan, admin, force, extra)
    prev = audit.booking_snapshot(b)
    db.execute(
        update(BookingResourceLock)
        .where(BookingResourceLock.booking_id == b.id, BookingResourceLock.lock_status == LockStatus.PENDING)
        .values(lock_status=LockStatus.CONFIRMED, expires_at=None, updated_at=now_utc())
    )
    _set_status(db, b, BookingStatus.APPROVED, admin, "Approved")
    b.approved_by, b.approved_at, b.expires_at = admin.id, now_utc(), None
    db.flush()
    if forced:
        _record_force(db, admin, b, plan, force, plan.issues + extra,
                      previous_allocation={"resource_id": str(b.resource_id), "work_dates": [d.isoformat() for d in locked]})
    audit.record(db, "booking.approved", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=prev, new=audit.booking_snapshot(b), reason=force.reason if forced else None)
    notifications.notify_approved(db, b)
    return b


def reject(db: Session, admin: User, booking_id: uuid.UUID, reason: str) -> Booking:
    if not admin.is_admin:
        raise forbidden()
    reason = _clean_text(reason, "Rejection reason", max_len=2000)
    b = lock_booking(db, booking_id)
    if b.status != BookingStatus.PENDING:
        raise conflict("Only pending bookings can be rejected.", "invalid_state")
    prev = audit.booking_snapshot(b)
    _release_locks(db, b.id)
    _set_status(db, b, BookingStatus.REJECTED, admin, reason)
    b.rejected_by, b.rejected_at, b.rejection_reason, b.expires_at = admin.id, now_utc(), reason, None
    db.flush()
    audit.record(db, "booking.rejected", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=prev, new=audit.booking_snapshot(b), reason=reason)
    notifications.notify_rejected(db, b)
    return b


def cancel(db: Session, actor: User, booking_id: uuid.UUID, reason: str) -> Booking:
    reason = _clean_text(reason, "Cancellation reason", max_len=2000)
    b = lock_booking(db, booking_id)
    if not actor.is_admin:
        if b.requester_id != actor.id:
            raise not_found("Booking")  # do not reveal existence of other requesters' bookings
        if b.status != BookingStatus.PENDING or not settings_service.get_setting(db, "requester_direct_cancel_pending"):
            raise forbidden("This booking can only be cancelled by an administrator. Submit a cancellation request instead.")
    if b.status not in BookingStatus.ACTIVE:
        raise conflict("Only pending or approved bookings can be cancelled.", "invalid_state")
    was_approved = b.status == BookingStatus.APPROVED
    prev = audit.booking_snapshot(b)
    _release_locks(db, b.id)
    _set_status(db, b, BookingStatus.CANCELLED, actor, reason)
    b.cancelled_by, b.cancelled_at, b.cancellation_reason, b.expires_at = actor.id, now_utc(), reason, None
    db.flush()
    audit.record(db, "booking.cancelled", actor, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=prev, new=audit.booking_snapshot(b), reason=reason)
    if was_approved:
        notifications.notify_cancelled(db, b, reason)
    return b


# --------------------------------------------------------------------------------------
# admin modification / reassignment / reschedule
# --------------------------------------------------------------------------------------

SCHEDULE_FIELDS = {"resource_id", "start_date", "activity_type_id", "additional_days", "duration_days", "end_date", "recalculate"}
DETAIL_FIELDS = {"application_name", "application_version", "pci_dss_scope", "poc_name", "poc_email", "additional_comments"}


def modify(db: Session, admin: User, booking_id: uuid.UUID, changes: dict[str, Any], reason: str,
           force: ForceOptions | None = None) -> Booking:
    if not admin.is_admin:
        raise forbidden()
    reason = _clean_text(reason, "Reason for change", max_len=2000)
    ensure_force_allowed(admin, force, booking_id=booking_id)
    unknown = set(changes) - SCHEDULE_FIELDS - DETAIL_FIELDS
    if unknown:
        raise bad_request(f"Unsupported field(s): {', '.join(sorted(unknown))}")
    b = lock_booking(db, booking_id)
    if b.status not in BookingStatus.ACTIVE:
        raise conflict("Only pending or approved bookings can be modified.", "invalid_state")
    before = audit.booking_snapshot(b)
    old_alloc = {"resource_id": str(b.resource_id), "resource_code": b.resource.code,
                 "start_date": b.start_date.isoformat(), "end_date": b.end_date.isoformat(),
                 "work_dates": [d.isoformat() for d in _active_lock_dates(db, b.id)]}
    forced = False
    plan = None

    if SCHEDULE_FIELDS & set(changes):
        new_rid = changes.get("resource_id") or b.resource_id
        resources = lock_resources(db, [b.resource_id, new_rid])
        for rid in resources:
            expire_stale_pending(db, rid)
        resource = resources[new_rid]
        activity = b.activity_type
        activity_changed = "activity_type_id" in changes and changes["activity_type_id"] != b.activity_type_id
        if activity_changed:
            activity = _get_activity(db, changes["activity_type_id"])
        additional = changes.get("additional_days", 0 if activity_changed else b.additional_days)
        end_override = changes.get("end_date")
        if changes.get("duration_days") is not None:
            if changes["duration_days"] <= 0:
                raise bad_request("Duration must be a positive integer.")
            duration, overridden = changes["duration_days"], True
        elif end_override is not None:
            duration, overridden = b.duration_days, True
        elif activity_changed or "additional_days" in changes or changes.get("recalculate"):
            try:
                duration, overridden = total_duration(activity, additional), False
            except SchedulingError as e:
                raise bad_request(e.message, e.code)
        else:
            duration, overridden = b.duration_days, b.duration_overridden
        start = changes.get("start_date") or b.start_date
        try:
            plan = plan_schedule(db, resource, start, duration, exclude_booking_id=b.id, explicit_end_date=end_override)
        except SchedulingError as e:
            raise bad_request(e.message, e.code)
        forced = _evaluate(db, plan, admin, force)

        # release the old reservation and create the new one in ONE transaction
        _release_locks(db, b.id)
        db.flush()
        lock_status = LockStatus.CONFIRMED if b.status == BookingStatus.APPROVED else LockStatus.PENDING
        _write_locks(db, b, plan, lock_status, forced, b.expires_at if lock_status == LockStatus.PENDING else None)
        b.resource_id = resource.id
        b.activity_type_id = activity.id
        b.activity_name_snapshot = activity.name
        b.base_duration_snapshot = activity.base_duration_days
        b.additional_days = additional
        b.duration_days = plan.duration_days
        b.duration_overridden = overridden
        b.start_date = plan.start_date
        b.end_date = plan.end_date

    for f in DETAIL_FIELDS & set(changes):
        v = changes[f]
        if f == "pci_dss_scope":
            if not isinstance(v, bool):
                raise bad_request("PCI DSS Scope must be Yes or No.")
        elif f == "additional_comments":
            v = _clean_text(v, "Additional Comments", required=False, max_len=4000)
        else:
            v = _clean_text(v, f.replace("_", " ").title(), max_len=254)
        setattr(b, f, v)

    db.flush()
    db.refresh(b)
    after = audit.booking_snapshot(b)
    changed = {k for k in after if before.get(k) != after.get(k)} - {"version", "needs_review", "is_force_allocated", "resource_code"}
    if not changed and not forced:
        raise bad_request("No changes were supplied.", "no_changes")
    b.version += 1

    categories = {
        "booking.reassigned": {"resource_id"},
        "booking.rescheduled": {"start_date", "end_date"},
        "booking.activity_changed": {"activity_type_id", "activity_name_snapshot", "base_duration_snapshot",
                                     "additional_days", "duration_days", "duration_overridden"},
        "booking.details_changed": DETAIL_FIELDS,
    }
    for action, fields in categories.items():
        touched = changed & fields
        if touched:
            extra_prev = {"resource_code": before.get("resource_code")} if action == "booking.reassigned" else {}
            extra_new = {"resource_code": after.get("resource_code")} if action == "booking.reassigned" else {}
            audit.record(db, action, admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                         previous={**{k: before[k] for k in touched}, **extra_prev},
                         new={**{k: after[k] for k in touched}, **extra_new}, reason=reason)
    audit.record(db, "booking.modified", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=before, new=audit.booking_snapshot(b), reason=reason)
    if forced and plan is not None:
        _record_force(db, admin, b, plan, force, plan.issues, previous_allocation=old_alloc)

    if b.status == BookingStatus.APPROVED and changed:
        labels = {"resource_id": "Resource", "start_date": "Start date", "end_date": "End date",
                  "activity_name_snapshot": "Activity type", "duration_days": "Duration (working days)",
                  "application_name": "Application name", "application_version": "Application version",
                  "pci_dss_scope": "PCI DSS scope", "poc_name": "POC name", "poc_email": "POC email",
                  "additional_comments": "Comments"}
        lines = []
        for k in sorted(changed):
            if k not in labels:
                continue
            if k == "resource_id":
                lines.append(f"- Resource: {db.get(SecurityResource, uuid.UUID(before['resource_id'])).display_name} -> {b.resource.display_name}")
            else:
                lines.append(f"- {labels[k]}: {before.get(k)} -> {after.get(k)}")
        notifications.notify_modified(db, b, "\n".join(lines) or "Booking details updated.", reason)
        if "poc_email" in changed and before.get("poc_email"):
            notifications.enqueue(db, "booking_modified_poc", [before["poc_email"]],
                                  notifications.booking_context(b, **{"Change Summary": "\n".join(lines), "Reason": reason}), b.id)
    return b


# --------------------------------------------------------------------------------------
# requester change requests (cancellation / reschedule)
# --------------------------------------------------------------------------------------

def request_change(db: Session, actor: User, booking_id: uuid.UUID, request_type: str, reason: str,
                   proposed_start: date | None = None, proposed_resource_id: uuid.UUID | None = None) -> dict:
    reason = _clean_text(reason, "Reason", max_len=2000)
    b = lock_booking(db, booking_id)
    if b.requester_id != actor.id and not actor.is_admin:
        raise not_found("Booking")
    if b.status not in BookingStatus.ACTIVE:
        raise conflict("Only pending or approved bookings can be changed.", "invalid_state")
    if request_type not in ("cancel", "reschedule"):
        raise bad_request("Invalid request type.")
    if request_type == "cancel" and b.status == BookingStatus.PENDING and settings_service.get_setting(db, "requester_direct_cancel_pending"):
        cancel(db, actor, b.id, reason)
        return {"mode": "cancelled", "booking_id": str(b.id)}
    preview_result = None
    if request_type == "reschedule":
        if proposed_start is None:
            raise bad_request("A proposed start date is required.")
        if proposed_start < settings_service.org_today(db):
            raise bad_request("The proposed start date cannot be in the past.")
        target = proposed_resource_id or b.resource_id
        r = db.get(SecurityResource, target)
        if r is None or not r.is_active:
            raise bad_request("The proposed resource is not available.")
        plan = plan_schedule(db, r, proposed_start, b.duration_days, exclude_booking_id=b.id)
        preview_result = {"available": plan.ok, "end_date": plan.end_date.isoformat() if plan.end_date else None,
                          "issues": _issues_json(plan.issues, include_booking_ids=False)}
    existing = db.scalar(select(BookingChangeRequest.id).where(BookingChangeRequest.booking_id == b.id,
                                                               BookingChangeRequest.status == "pending"))
    if existing:
        raise conflict("A change request for this booking is already awaiting review.", "duplicate_request")
    cr = BookingChangeRequest(id=uuid.uuid4(), booking_id=b.id, request_type=request_type, requested_by=actor.id,
                              reason=reason, proposed_start_date=proposed_start, proposed_resource_id=proposed_resource_id)
    db.add(cr)
    db.flush()
    audit.record(db, f"booking.{request_type}_requested", actor, entity_type="booking_change_request", entity_id=cr.id,
                 booking_id=b.id, new={"request_type": request_type, "proposed_start_date": proposed_start,
                                       "proposed_resource_id": proposed_resource_id}, reason=reason)
    summary = "Cancellation" if request_type == "cancel" else f"Reschedule to start {proposed_start}"
    notifications.notify_change_request(db, b, summary, reason)
    return {"mode": "requested", "change_request_id": str(cr.id), "booking_id": str(b.id), "preview": preview_result}


def decide_change_request(db: Session, admin: User, cr_id: uuid.UUID, approve_it: bool, note: str | None,
                          force: ForceOptions | None = None) -> BookingChangeRequest:
    if not admin.is_admin:
        raise forbidden()
    ensure_force_allowed(admin, force)
    cr = db.scalars(select(BookingChangeRequest).where(BookingChangeRequest.id == cr_id)
                    .with_for_update(of=BookingChangeRequest)).unique().first()
    if cr is None:
        raise not_found("Change request")
    if cr.status != "pending":
        raise conflict("This change request has already been decided.", "invalid_state")
    note = _clean_text(note, "Decision note", required=not approve_it, max_len=2000)
    if approve_it:
        if cr.request_type == "cancel":
            cancel(db, admin, cr.booking_id, f"Requester cancellation request approved. Requester reason: {cr.reason}"
                   + (f" | Admin note: {note}" if note else ""))
        else:
            changes: dict[str, Any] = {"start_date": cr.proposed_start_date}
            if cr.proposed_resource_id:
                changes["resource_id"] = cr.proposed_resource_id
            modify(db, admin, cr.booking_id, changes,
                   f"Requester reschedule request approved. Requester reason: {cr.reason}" + (f" | Admin note: {note}" if note else ""),
                   force)
    cr.status = "approved" if approve_it else "rejected"
    cr.decided_by, cr.decided_at, cr.decision_note = admin.id, now_utc(), note
    db.flush()
    audit.record(db, f"change_request.{cr.status}", admin, entity_type="booking_change_request", entity_id=cr.id,
                 booking_id=cr.booking_id, previous={"status": "pending"}, new={"status": cr.status}, reason=note)
    if not approve_it:
        b = db.get(Booking, cr.booking_id)
        kind = "cancellation" if cr.request_type == "cancel" else "reschedule"
        notifications.enqueue(db, "change_request_declined", notifications.poc_recipients(db, b),
                              notifications.booking_context(b, **{"Change Summary": f"Your {kind} request was not approved. The booking remains unchanged.",
                                                                  "Reason": note}), b.id)
    return cr
