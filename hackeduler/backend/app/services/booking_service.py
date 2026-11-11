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

from sqlalchemy import func, select, update
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
    Implementation,
    LockStatus,
    Product,
    SecurityResource,
    User,
)
from . import audit, conflicts, initiation, notifications, settings_service
from .availability import (
    UNAVAILABLE_MESSAGE,
    horizon_end,
    load_holidays,
    working_weekdays,
    SchedulePlan,
    ScheduleIssue,
    alternative_resources,
    now_utc,
    plan_schedule,
    suggest_next_start,
    total_duration,
)
from .calendar_engine import SchedulingError, WorkCalendar, compute_work_dates

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
    poc_name: str
    poc_email: str
    resource_id: uuid.UUID | None = None   # None = assign automatically (or no resource needed)
    start_date: date | None = None         # optional only for activities that need no resource
    additional_comments: str | None = None
    additional_days: int = 0
    product_id: uuid.UUID | None = None
    implementation_id: uuid.UUID | None = None


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def lock_resources(db: Session, resource_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityResource]:
    out = {}
    for rid in sorted(set(resource_ids), key=str):
        r = db.scalars(
            select(SecurityResource).where(SecurityResource.id == rid).with_for_update().execution_options(populate_existing=True)
        ).first()
        if r is None or r.deleted_at is not None:
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


def _resourceless_dates(db: Session, start: date | None, duration: int | None) -> tuple[date | None, date | None, int | None]:
    """Dates for an activity that needs no security resource: organisation calendar only (no leave)."""
    if start is None:
        return None, None, duration
    if duration is None:
        return start, start, None
    cal = WorkCalendar(holidays=load_holidays(db, start, horizon_end(start, duration)), working_weekdays=working_weekdays(db))
    try:
        dates = compute_work_dates(cal, start, duration)
    except SchedulingError as e:
        raise bad_request(e.message.replace("The selected resource is unavailable", "The organisation is closed"), e.code)
    return start, dates[-1], duration


def auto_candidates(db: Session, start: date, duration: int, exclude_booking_id: uuid.UUID | None = None) -> list[SchedulePlan]:
    """Every active resource that can take the booking, best first:
    earliest finish, then lightest current workload, then resource number."""
    resources = list(db.scalars(select(SecurityResource).where(SecurityResource.is_active.is_(True),
                                                               SecurityResource.deleted_at.is_(None))))
    if not resources:
        return []
    load = dict(db.execute(
        select(BookingResourceLock.resource_id, func.count())
        .where(BookingResourceLock.lock_status.in_(LockStatus.ACTIVE),
               BookingResourceLock.work_date.between(start - timedelta(days=30), start + timedelta(days=90)))
        .group_by(BookingResourceLock.resource_id)).all())
    plans = []
    for r in resources:
        try:
            p = plan_schedule(db, r, start, duration, exclude_booking_id=exclude_booking_id)
        except SchedulingError:
            continue
        if p.ok:
            plans.append(p)
    plans.sort(key=lambda p: (p.end_date, load.get(p.resource.id, 0), p.resource.sequence_no))
    return plans


def earliest_any_resource(db: Session, duration: int, after: date) -> date | None:
    best = None
    for r in db.scalars(select(SecurityResource).where(SecurityResource.is_active.is_(True), SecurityResource.deleted_at.is_(None))):
        d = suggest_next_start(db, r, duration, after)
        if d and (best is None or d < best):
            best = d
    return best


def resolve_product(db: Session, actor: User, product_id: uuid.UUID | None, implementation_id: uuid.UUID | None,
                    *, for_admin: bool) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Requesters always book under their own product; the implementation must belong to it."""
    if not for_admin:
        if product_id and product_id != actor.product_id:
            raise forbidden("You can only book for your own product.")
        product_id = actor.product_id
        implementation_id = implementation_id or actor.implementation_id
    if implementation_id and not product_id:
        impl = db.get(Implementation, implementation_id)
        product_id = impl.product_id if impl else None
    if product_id:
        prod = db.get(Product, product_id)
        if prod is None or (not prod.is_active and not for_admin):
            raise bad_request("Unknown or inactive product.")
    if implementation_id:
        impl = db.get(Implementation, implementation_id)
        if impl is None or impl.product_id != product_id:
            raise bad_request("The implementation does not belong to the selected product.")
        if not impl.is_active and not for_admin:
            raise bad_request("The selected implementation is inactive.")
    return product_id, implementation_id


def _clean_text(value: str | None, field: str, *, required: bool = True, max_len: int = 255) -> str | None:
    v = (value or "").strip()
    if required and not v:
        raise bad_request(f"{field} is required.")
    if len(v) > max_len:
        raise bad_request(f"{field} must be at most {max_len} characters.")
    return v or None


def _get_activity(db: Session, activity_type_id: uuid.UUID, *, must_be_active: bool = True,
                  for_requester: bool = False) -> ActivityType:
    a = db.get(ActivityType, activity_type_id)
    if a is None or a.deleted_at is not None:
        raise bad_request("Unknown activity type.")
    if for_requester and not a.visible_to_requesters:
        # Hidden types are admin-only: answer exactly as if the type did not exist.
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
        q = q.where(Booking.uses_resource(resource_id))
    ids = []
    for b in db.scalars(q.with_for_update(of=Booking, skip_locked=True)).unique().all():
        _release_locks(db, b.id)
        _set_status(db, b, BookingStatus.EXPIRED, None, "Pending reservation expired without review")
        audit.record(db, "booking.expired", None, entity_type="booking", entity_id=b.id, booking_id=b.id,
                     previous={"status": BookingStatus.PENDING}, new={"status": BookingStatus.EXPIRED})
        notifications.notify_expired(db, b)
        ids.append(b.id)
    return ids


def apply_scheduled_deactivations(db: Session) -> list[uuid.UUID]:
    """Flip resources to inactive once their scheduled inactive-from date arrives (run by the worker)."""
    today = settings_service.org_today(db)
    q = (select(SecurityResource)
         .where(SecurityResource.is_active.is_(True), SecurityResource.inactive_from.is_not(None),
                SecurityResource.inactive_from <= today)
         .with_for_update(skip_locked=True))
    ids = []
    for r in db.scalars(q).all():
        r.is_active, r.deactivated_at = False, now_utc()
        flagged = conflicts.flag_inactive_resource(db, r, r.inactive_from, None)  # dedupes already-open conflicts
        audit.record(db, "resource.deactivated", None, entity_type="resource", entity_id=r.id,
                     previous={"is_active": True}, new={"is_active": False, "inactive_from": r.inactive_from,
                                                        "flagged_bookings": flagged},
                     reason=f"Scheduled deactivation effective {r.inactive_from.isoformat()}"
                            + (f": {r.inactive_reason}" if r.inactive_reason else ""))
        ids.append(r.id)
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
    activity = _get_activity(db, activity_type_id, for_requester=not actor.is_admin)
    if not activity.requires_resource:
        raise bad_request("This activity type does not use a security resource.", "no_resource_required")
    try:
        duration = total_duration(activity, additional_days)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)
    resource = db.get(SecurityResource, resource_id)
    if resource is None or resource.deleted_at is not None:
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


def preview_auto(db: Session, actor: User, activity_type_id: uuid.UUID, start: date | None,
                 additional_days: int = 0) -> dict[str, Any]:
    """Requester preview: the system picks the resource. Nothing is reserved until submission."""
    activity = _get_activity(db, activity_type_id, for_requester=not actor.is_admin)
    try:
        duration = total_duration(activity, additional_days)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)
    today = settings_service.org_today(db)
    base = {"activity_type_id": str(activity.id), "activity_name": activity.name, "requires_resource": activity.requires_resource,
            "duration_days": duration, "start_date": start.isoformat() if start else None, "end_date": None,
            "work_dates": [], "resource_id": None, "resource_display_name": None, "available": False, "reason": None,
            "message": "", "suggested_start_date": None, "available_resources": 0}
    if start is not None and start < today:
        return {**base, "reason": "past_date", "message": "The start date cannot be in the past."}
    if not activity.requires_resource:
        s_, e_, d_ = _resourceless_dates(db, start, duration)
        return {**base, "available": True, "start_date": s_.isoformat() if s_ else None, "end_date": e_.isoformat() if e_ else None,
                "duration_days": d_, "message": "No security resource is needed for this activity. The OffSec team will review your request."}
    if start is None:
        return {**base, "reason": "start_required", "message": "Choose a start date."}
    org = WorkCalendar(holidays=load_holidays(db, start, start), working_weekdays=working_weekdays(db))
    why = org.non_working_reason(start)
    cands = auto_candidates(db, start, duration)
    if cands:
        p = cands[0]
        return {**base, "available": True, "resource_id": str(p.resource.id), "resource_display_name": p.resource.display_name,
                "end_date": p.end_date.isoformat(), "work_dates": [d.isoformat() for d in p.work_dates],
                "available_resources": len(cands),
                "message": f"{p.resource.display_name} is available and will be assigned."}
    nxt = earliest_any_resource(db, duration, max(start, today) + timedelta(days=1))
    msg = ("Bookings must start on a working day." if why in ("weekend", "holiday")
           else "No security resource is available for these dates.")
    return {**base, "reason": "non_working_start" if why in ("weekend", "holiday") else "no_resource_available",
            "message": msg, "suggested_start_date": nxt.isoformat() if nxt else None}


def _new_booking(db: Session, actor: User, activity, inp: BookingInput, *, resource_id, start, end, duration, status,
                 source, expires_at, product_id, implementation_id, overridden: bool = False, reason: str = "Submitted") -> Booking:
    approved = status == BookingStatus.APPROVED
    b = Booking(
        id=uuid.uuid4(), requester_id=actor.id, resource_id=resource_id, activity_type_id=activity.id,
        activity_name_snapshot=activity.name, base_duration_snapshot=activity.base_duration_days,
        additional_days=inp.additional_days, duration_days=duration, duration_overridden=overridden,
        requires_resource=activity.requires_resource, product_id=product_id, implementation_id=implementation_id,
        application_name=inp.application_name, application_version=inp.application_version,
        pci_dss_scope=inp.pci_dss_scope, poc_name=inp.poc_name, poc_email=inp.poc_email,
        additional_comments=inp.additional_comments, start_date=start, end_date=end, status=status, source=source,
        expires_at=expires_at, submitted_at=now_utc(),
        approved_by=actor.id if approved else None, approved_at=now_utc() if approved else None,
    )
    db.add(b)
    db.flush()
    db.add(BookingStatusHistory(id=uuid.uuid4(), booking_id=b.id, from_status=None, to_status=status,
                                changed_by=actor.id, reason=reason))
    return b


def _place(db: Session, actor: User, activity, inp: BookingInput, *, duration: int, status: str, source: str,
           product_id, implementation_id, force: ForceOptions | None = None, end_date_override: date | None = None,
           overridden: bool = False, reason: str = "Submitted") -> tuple[Booking, SchedulePlan, bool]:
    """Create a resource-based booking: on the given resource, or on the best available one."""
    approved = status == BookingStatus.APPROVED
    lock_status = LockStatus.CONFIRMED if approved else LockStatus.PENDING
    expires_at = None if approved else _pending_expiry(db)
    if inp.resource_id:
        resource = lock_resources(db, [inp.resource_id])[inp.resource_id]  # serialises reservations on this resource
        if not resource.is_active and not actor.is_admin:
            raise conflict(f"{resource.display_name} is not accepting bookings.", "resource_unavailable")
        expire_stale_pending(db, resource.id)
        try:
            plan = plan_schedule(db, resource, inp.start_date, duration, explicit_end_date=end_date_override)
        except SchedulingError as e:
            raise bad_request(e.message, e.code)
        forced = _evaluate(db, plan, actor, force)
        b = _new_booking(db, actor, activity, inp, resource_id=resource.id, start=plan.start_date, end=plan.end_date,
                         duration=plan.duration_days, status=status, source=source, expires_at=expires_at,
                         product_id=product_id, implementation_id=implementation_id, overridden=overridden, reason=reason)
        _write_locks(db, b, plan, lock_status, forced, expires_at)
        return b, plan, forced

    # automatic assignment: try candidates best-first; the partial unique index arbitrates races,
    # a lost race just rolls back the savepoint and moves to the next resource.
    expire_stale_pending(db)
    for plan in auto_candidates(db, inp.start_date, duration):
        try:
            with db.begin_nested():
                b = _new_booking(db, actor, activity, inp, resource_id=plan.resource.id, start=plan.start_date,
                                 end=plan.end_date, duration=plan.duration_days, status=status, source=source,
                                 expires_at=expires_at, product_id=product_id, implementation_id=implementation_id,
                                 overridden=overridden, reason=reason)
                _write_locks(db, b, plan, lock_status, False, expires_at)
            return b, plan, False
        except ServiceError as e:
            if e.code != "resource_unavailable":
                raise
    today = settings_service.org_today(db)
    nxt = earliest_any_resource(db, duration, max(inp.start_date, today) + timedelta(days=1))
    raise conflict("No security resource is available for the requested dates. Please choose another start date.",
                   "no_resource_available", {"suggested_start_date": nxt.isoformat() if nxt else None})


@dataclass
class ExtraAllocation:
    """An additional resource on an admin booking. Anything left empty follows the main allocation, so a plain
    resource id reserves the same dates; a start date and working days (or an end date) give it its own slice
    of the activity (e.g. resource 1 takes the first 5 days, resource 2 takes the last 3 days a week later)."""
    resource_id: uuid.UUID
    start_date: date | None = None
    working_days: int | None = None
    end_date: date | None = None

    @property
    def custom(self) -> bool:
        return self.start_date is not None or self.working_days is not None or self.end_date is not None


def _place_multi(db: Session, admin: User, activity, inp: BookingInput, extras: list[ExtraAllocation], *, duration: int,
                 product_id, implementation_id, end_date_override: date | None, overridden: bool,
                 reason: str) -> tuple[Booking, SchedulePlan]:
    """Admin booking that blocks several resources for the same activity: ONE confirmed booking, one set of
    locks per resource. All-or-nothing - every chosen resource must be free for the whole period."""
    extra_ids = [e.resource_id for e in extras]
    all_ids = [inp.resource_id, *extra_ids]
    resources = lock_resources(db, all_ids)  # sorted row locks: concurrent bookings cannot interleave or deadlock
    for r in resources.values():
        expire_stale_pending(db, r.id)
    plans: list[SchedulePlan] = []
    # (resource, start, working days, explicit end) for the main resource first, then each additional one
    slices = [(inp.resource_id, inp.start_date, duration, end_date_override)]
    for e in extras:
        # No length given: follow the main allocation (same end date when it has one and the dates are the same)
        inherited_end = end_date_override if (e.start_date is None and e.working_days is None and e.end_date is None) else None
        slices.append((e.resource_id, e.start_date or inp.start_date, e.working_days or duration, e.end_date or inherited_end))
    for rid, start, days, end in slices:
        r = resources[rid]
        try:
            plan = plan_schedule(db, r, start, days, explicit_end_date=end)
        except SchedulingError as e:
            raise bad_request(f"{r.display_name}: {e.message}", e.code)
        if plan.issues:
            raise conflict(f"{r.display_name} is not free for the selected dates: {plan.issues[0].message} "
                           "Nothing was booked. Remove it from the selection or change the dates.",
                           "resource_unavailable",
                           {"resource_id": str(r.id), "issues": _issues_json(plan.issues, include_booking_ids=True)})
        plans.append(plan)
    primary = plans[0]
    end = max(p.end_date for p in plans if p.end_date)
    # Same dates for everyone: the booking is as long as the main allocation. Split between resources: it covers
    # the working days of all the slices together.
    total_days = sum(len(p.work_dates) for p in plans) if any(e.custom for e in extras) else primary.duration_days
    b = _new_booking(db, admin, activity, inp, resource_id=primary.resource.id, start=min(p.start_date for p in plans),
                     end=end, duration=total_days, status=BookingStatus.APPROVED, source="admin",
                     expires_at=None, product_id=product_id, implementation_id=implementation_id,
                     overridden=overridden, reason=reason)
    b.extra_resources = [resources[i] for i in extra_ids]
    for plan in plans:
        _write_locks(db, b, plan, LockStatus.CONFIRMED, False, None)
    return b, primary


def submit_booking(db: Session, actor: User, inp: BookingInput) -> Booking:
    _validate_input(inp)
    activity = _get_activity(db, inp.activity_type_id, for_requester=not actor.is_admin)
    try:
        duration = total_duration(activity, inp.additional_days)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)
    if inp.start_date is not None and inp.start_date < settings_service.org_today(db):
        raise bad_request("The start date cannot be in the past.", "past_date")
    product_id, implementation_id = resolve_product(db, actor, inp.product_id, inp.implementation_id, for_admin=False)

    if not activity.requires_resource:
        if inp.resource_id:
            raise bad_request("This activity type does not use a security resource.", "no_resource_required")
        start, end, duration = _resourceless_dates(db, inp.start_date, duration)
        b = _new_booking(db, actor, activity, inp, resource_id=None, start=start, end=end, duration=duration,
                         status=BookingStatus.PENDING, source="requester", expires_at=None,
                         product_id=product_id, implementation_id=implementation_id)
    else:
        if inp.start_date is None:
            raise bad_request("A start date is required for this activity.", "start_required")
        b, _plan, _ = _place(db, actor, activity, inp, duration=duration, status=BookingStatus.PENDING, source="requester",
                             product_id=product_id, implementation_id=implementation_id)
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
                         force: ForceOptions | None = None, reason: str | None = None,
                         additional: list[ExtraAllocation] | None = None) -> Booking:
    if not admin.is_admin:
        raise forbidden()
    ensure_force_allowed(admin, force)
    extras = list(additional or [])
    extra_ids = [e.resource_id for e in extras]
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
    product_id, implementation_id = resolve_product(db, admin, inp.product_id, inp.implementation_id, for_admin=True)
    note = reason or "Created by administrator"
    forced, plan = False, None
    if not activity.requires_resource:
        if extra_ids:
            raise bad_request("This activity type does not use a security resource.", "no_resource_required")
        if inp.resource_id:
            raise bad_request("This activity type does not use a security resource.", "no_resource_required")
        if end_date_override and inp.start_date:
            if end_date_override < inp.start_date:
                raise bad_request("End date must be on or after the start date.")
            start, end = inp.start_date, end_date_override
        else:
            start, end, duration = _resourceless_dates(db, inp.start_date, duration)
        b = _new_booking(db, admin, activity, inp, resource_id=None, start=start, end=end, duration=duration,
                         status=initial_status, source="admin", expires_at=None, product_id=product_id,
                         implementation_id=implementation_id, overridden=duration_override is not None, reason=note)
    else:
        if inp.start_date is None:
            raise bad_request("A start date is required for this activity.", "start_required")
        if force is not None and not inp.resource_id:
            raise bad_request("Select a resource to force allocate.")
        if extra_ids:
            if not inp.resource_id:
                raise bad_request("Choose the main resource first, then add the other resources.", "resource_required")
            if len(set(extra_ids)) != len(extra_ids) or inp.resource_id in extra_ids:
                raise bad_request("Each resource can only be selected once.", "duplicate_resource")
            if force is not None:
                raise bad_request("Force Allocate cannot be combined with multiple resources. Book resources "
                                  "that are free, or force allocate a single resource.", "force_not_supported")
            if initial_status != BookingStatus.APPROVED:
                raise bad_request("Multi-resource bookings are always confirmed.")
            b, plan = _place_multi(db, admin, activity, inp, extras, duration=duration, product_id=product_id,
                                   implementation_id=implementation_id, end_date_override=end_date_override,
                                   overridden=duration_override is not None or end_date_override is not None, reason=note)
            forced = False
        else:
            b, plan, forced = _place(db, admin, activity, inp, duration=duration, status=initial_status, source="admin",
                                     product_id=product_id, implementation_id=implementation_id, force=force,
                                     end_date_override=end_date_override,
                                     overridden=duration_override is not None or end_date_override is not None, reason=note)
    db.refresh(b)
    if forced:
        _record_force(db, admin, b, plan, force, plan.issues, previous_allocation=None)
    audit.record(db, "booking.admin_created", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 new=audit.booking_snapshot(b), reason=reason or (force.reason if force else None))
    if initial_status == BookingStatus.APPROVED:
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
    if not b.requires_resource:
        prev = audit.booking_snapshot(b)
        _set_status(db, b, BookingStatus.APPROVED, admin, "Approved")
        b.approved_by, b.approved_at, b.expires_at = admin.id, now_utc(), None
        db.flush()
        audit.record(db, "booking.approved", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                     previous=prev, new=audit.booking_snapshot(b))
        notifications.notify_approved(db, b)
        return b
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


def mark_completed(db: Session, admin: User, booking_id: uuid.UUID, note: str | None = None) -> Booking:
    """Manually complete an approved booking that does not use a resource (e.g. an automated scan).
    Resource bookings are completed automatically once their end date passes."""
    if not admin.is_admin:
        raise forbidden()
    b = lock_booking(db, booking_id)
    if b.status != BookingStatus.APPROVED:
        raise conflict("Only approved bookings can be marked completed.", "invalid_state")
    if b.requires_resource:
        raise conflict("Bookings with a security resource are completed automatically after their end date.", "invalid_state")
    prev = audit.booking_snapshot(b)
    _set_status(db, b, BookingStatus.COMPLETED, admin, note or "Marked completed")
    db.flush()
    audit.record(db, "booking.completed", admin, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=prev, new=audit.booking_snapshot(b), reason=note)
    return b


# --------------------------------------------------------------------------------------
# admin modification / reassignment / reschedule
# --------------------------------------------------------------------------------------

SCHEDULE_FIELDS = {"resource_id", "start_date", "activity_type_id", "additional_days", "duration_days", "end_date", "recalculate"}
DETAIL_FIELDS = {"application_name", "application_version", "pci_dss_scope", "poc_name", "poc_email", "additional_comments"}
PRODUCT_FIELDS = {"product_id", "implementation_id"}


def modify(db: Session, admin: User, booking_id: uuid.UUID, changes: dict[str, Any], reason: str,
           force: ForceOptions | None = None) -> Booking:
    if not admin.is_admin:
        raise forbidden()
    reason = _clean_text(reason, "Reason for change", max_len=2000)
    ensure_force_allowed(admin, force, booking_id=booking_id)
    unknown = set(changes) - SCHEDULE_FIELDS - DETAIL_FIELDS - PRODUCT_FIELDS
    if unknown:
        raise bad_request(f"Unsupported field(s): {', '.join(sorted(unknown))}")
    b = lock_booking(db, booking_id)
    if b.status not in BookingStatus.ACTIVE:
        raise conflict("Only pending or approved bookings can be modified.", "invalid_state")
    if b.extra_resources and (set(changes) & SCHEDULE_FIELDS):
        raise conflict("This booking holds several resources, so its dates, activity and resources can't be edited "
                       "in place. Cancel it and create a new multi-resource booking, or edit the booking details only.",
                       "multi_resource_locked")
    before = audit.booking_snapshot(b)
    old_alloc = {"resource_id": str(b.resource_id) if b.resource_id else None,
                 "resource_code": b.resource.code if b.resource else None,
                 "start_date": b.start_date.isoformat() if b.start_date else None,
                 "end_date": b.end_date.isoformat() if b.end_date else None,
                 "work_dates": [d.isoformat() for d in _active_lock_dates(db, b.id)]}
    forced = False
    plan = None
    activity = b.activity_type
    activity_changed = "activity_type_id" in changes and changes["activity_type_id"] != b.activity_type_id
    if activity_changed:
        activity = _get_activity(db, changes["activity_type_id"])

    if PRODUCT_FIELDS & set(changes):
        pid, iid = resolve_product(db, admin, changes.get("product_id", b.product_id),
                                   changes.get("implementation_id", b.implementation_id if "product_id" not in changes else None),
                                   for_admin=True)
        b.product_id, b.implementation_id = pid, iid

    if not activity.requires_resource and (SCHEDULE_FIELDS & set(changes) or b.requires_resource):
        # no security resource: release any reservation, dates/duration optional
        if changes.get("resource_id"):
            raise bad_request("This activity type does not use a security resource.", "no_resource_required")
        additional = changes.get("additional_days", 0 if activity_changed else b.additional_days)
        if changes.get("duration_days") is not None:
            duration, overridden = changes["duration_days"], True
        elif activity_changed or "additional_days" in changes or changes.get("recalculate") or b.requires_resource:
            try:
                duration, overridden = total_duration(activity, additional), False
            except SchedulingError as e:
                raise bad_request(e.message, e.code)
        else:
            duration, overridden = b.duration_days, b.duration_overridden
        start = changes.get("start_date") or b.start_date
        if changes.get("end_date"):
            if start is None or changes["end_date"] < start:
                raise bad_request("End date must be on or after the start date.")
            end, overridden = changes["end_date"], True
        else:
            start, end, duration = _resourceless_dates(db, start, duration)
        _release_locks(db, b.id)
        b.resource_id, b.requires_resource = None, False
        b.activity_type_id, b.activity_name_snapshot = activity.id, activity.name
        b.base_duration_snapshot, b.additional_days = activity.base_duration_days, additional
        b.duration_days, b.duration_overridden, b.start_date, b.end_date = duration, overridden, start, end

    elif activity.requires_resource and (SCHEDULE_FIELDS & set(changes) or not b.requires_resource):
        start = changes.get("start_date") or b.start_date
        if start is None:
            raise bad_request("A start date is required for an activity that uses a security resource.", "start_required")
        additional = changes.get("additional_days", 0 if activity_changed else b.additional_days)
        new_rid = changes.get("resource_id") or b.resource_id
        if new_rid is None:  # moving from a resource-less activity: pick the best available resource
            try:
                d_ = changes.get("duration_days") or total_duration(activity, additional)
            except SchedulingError as e:
                raise bad_request(e.message, e.code)
            cands = auto_candidates(db, start, d_, exclude_booking_id=b.id)
            if not cands:
                raise conflict("No security resource is available for these dates. Choose a resource to force allocate.",
                               "no_resource_available")
            new_rid = cands[0].resource.id
        resources = lock_resources(db, [x for x in (b.resource_id, new_rid) if x])
        for rid in resources:
            expire_stale_pending(db, rid)
        resource = resources[new_rid]
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
        if duration is None:
            try:
                duration, overridden = total_duration(activity, additional), False
            except SchedulingError as e:
                raise bad_request(e.message, e.code)
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
        b.requires_resource = True
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
        "booking.details_changed": DETAIL_FIELDS | PRODUCT_FIELDS,
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
                  "additional_comments": "Comments", "requires_resource": "Security resource required"}
        lines = []
        for k in sorted(changed):
            if k not in labels:
                continue
            if k == "resource_id":
                old_r = db.get(SecurityResource, uuid.UUID(before["resource_id"])) if before.get("resource_id") else None
                lines.append(f"- Resource: {old_r.display_name if old_r else 'Not required'} -> "
                             f"{b.resource.display_name if b.resource else 'Not required'}")
            else:
                lines.append(f"- {labels[k]}: {before.get(k)} -> {after.get(k)}")
        notifications.notify_modified(db, b, "\n".join(lines) or "Booking details updated.", reason)
        if "poc_email" in changed and before.get("poc_email"):
            notifications.enqueue(db, "booking_modified_poc", [before["poc_email"]],
                                  notifications.booking_context(b, **{"Change Summary": "\n".join(lines), "Reason": reason}), b.id)
    if b.status == BookingStatus.APPROVED:
        initiation.send_if_due(db, b)  # rescheduled (new start date) and already inside the window => send again now
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
    if request_type == "reschedule" and b.requires_resource:
        target = proposed_resource_id or b.resource_id
        r = db.get(SecurityResource, target)
        if r is None or not r.is_active or r.deleted_at is not None:
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
