"""Admin configuration endpoints. Every route requires the Admin role (router-level dependency)."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..errors import bad_request, conflict, not_found
from ..models import (
    ROLE_ADMIN_ID,
    ROLE_REQUESTER_ID,
    ActivityType,
    Booking,
    EmailNotificationLog,
    EmailTemplate,
    Holiday,
    ResourceLeave,
    SecurityResource,
    User,
)
from ..schemas import (
    ActivityCreate,
    ActivityOut,
    ActivityUpdate,
    EmailLogOut,
    HolidayIn,
    HolidayOut,
    HolidayUpdate,
    LeaveIn,
    LeaveOut,
    LeaveUpdate,
    ResourceAdmin,
    ResourceCreate,
    ResourceUpdate,
    SettingsUpdate,
    TemplateOut,
    TemplateUpdate,
    UserCreate,
    UserUpdate,
    booking_admin_out,
)
from ..security import hash_password, validate_password_strength
from ..services import audit, conflicts, notifications, settings_service
from ..services.availability import now_utc
from ..services.calendar_engine import expand_ranges
from .auth import user_out
from .common import commit

router = APIRouter(prefix="/api/admin", tags=["admin-config"], dependencies=[Depends(require_admin)])


def _snap(obj, fields) -> dict:
    return {f: audit.jsonable(getattr(obj, f)) for f in fields}


# =============================================================== resources
RES_FIELDS = ("code", "display_name", "engineer_name", "engineer_email", "notes", "is_active", "inactive_from", "inactive_reason")


@router.get("/resources", response_model=list[ResourceAdmin])
def list_resources(db: Session = Depends(get_db)):
    return db.scalars(select(SecurityResource).order_by(SecurityResource.sequence_no)).all()


@router.post("/resources", response_model=ResourceAdmin, status_code=201)
def create_resource(body: ResourceCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # lock the table briefly so two admins cannot allocate the same sequence number
    db.execute(select(func.pg_advisory_xact_lock(424242)))
    seq = (db.scalar(select(func.max(SecurityResource.sequence_no))) or 0) + 1
    r = SecurityResource(id=uuid.uuid4(), sequence_no=seq, code=f"RES-{seq:02d}", display_name=f"Resource {seq:02d}",
                         engineer_name=body.engineer_name, engineer_email=body.engineer_email, notes=body.notes)
    db.add(r)
    db.flush()
    audit.record(db, "resource.created", admin, entity_type="resource", entity_id=r.id, new=_snap(r, RES_FIELDS))
    commit(db)
    return r


@router.patch("/resources/{resource_id}", response_model=ResourceAdmin)
def update_resource(resource_id: uuid.UUID, body: ResourceUpdate, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    r = db.get(SecurityResource, resource_id)
    if r is None:
        raise not_found("Resource")
    prev = _snap(r, RES_FIELDS)
    data = body.model_dump(exclude_unset=True)
    reason = (data.pop("reason", None) or "").strip() or None
    today = settings_service.org_today(db)
    has_from = "inactive_from" in data
    inactive_from = data.pop("inactive_from", None)
    want_active = data.pop("is_active", None)
    if has_from and want_active is not None:
        raise bad_request("Send either is_active or inactive_from, not both.")
    for k, v in data.items():
        setattr(r, k, v)

    action, flagged = None, []
    if want_active is True and (not r.is_active or r.inactive_from):
        # reactivate, or cancel a scheduled deactivation
        action = "resource.activated" if not r.is_active else "resource.deactivation_cancelled"
        r.is_active, r.deactivated_at, r.inactive_from, r.inactive_reason = True, None, None, None
    elif want_active is False and r.is_active:
        # immediate deactivation (from today)
        r.is_active, r.deactivated_at, r.inactive_from, r.inactive_reason = False, now_utc(), today, reason
        action = "resource.deactivated"
        flagged = conflicts.flag_inactive_resource(db, r, today, admin)
    elif has_from:
        if inactive_from is None:
            if r.inactive_from and r.is_active:
                r.inactive_from, r.inactive_reason = None, None
                action = "resource.deactivation_cancelled"
        else:
            if not r.is_active:
                raise bad_request(f"{r.display_name} is already inactive. Reactivate it first.")
            if inactive_from < today:
                raise bad_request("The inactive-from date cannot be in the past. Use today to deactivate immediately.")
            r.inactive_from, r.inactive_reason = inactive_from, reason
            if inactive_from == today:
                r.is_active, r.deactivated_at = False, now_utc()
                action = "resource.deactivated"
            else:
                action = "resource.deactivation_scheduled"
            flagged = conflicts.flag_inactive_resource(db, r, inactive_from, admin)
    if action:
        audit.record(db, action, admin, entity_type="resource", entity_id=r.id,
                     previous={"is_active": prev["is_active"], "inactive_from": prev["inactive_from"]},
                     new={"is_active": r.is_active, "inactive_from": r.inactive_from, "flagged_bookings": flagged}, reason=reason)
    if data:
        audit.record(db, "resource.updated", admin, entity_type="resource", entity_id=r.id, previous=prev,
                     new=_snap(r, RES_FIELDS), reason=reason)
    commit(db)
    return r


@router.get("/resources/{resource_id}/allocation")
def resource_allocation(resource_id: uuid.UUID, start: date | None = None, end: date | None = None,
                        db: Session = Depends(get_db)):
    r = db.get(SecurityResource, resource_id)
    if r is None:
        raise not_found("Resource")
    today = settings_service.org_today(db)
    start = start or today - timedelta(days=90)
    end = end or today + timedelta(days=180)
    bookings = db.scalars(select(Booking).where(Booking.resource_id == r.id, Booking.start_date <= end,
                                                Booking.end_date >= start).order_by(Booking.start_date)).unique().all()
    leaves = db.scalars(select(ResourceLeave).where(ResourceLeave.resource_id == r.id, ResourceLeave.start_date <= end,
                                                    ResourceLeave.end_date >= start).order_by(ResourceLeave.start_date)).unique().all()
    return {"resource": ResourceAdmin.model_validate(r), "bookings": [booking_admin_out(b) for b in bookings],
            "leaves": [_leave_out(lv) for lv in leaves]}


# =============================================================== activity types
ACT_FIELDS = ("name", "description", "base_duration_days", "allow_additional_days", "max_additional_days", "is_active", "sort_order")


def _check_activity(a: ActivityType) -> None:
    if not a.allow_additional_days and a.max_additional_days:
        raise bad_request("max_additional_days must be 0 unless additional days are allowed.")
    if a.allow_additional_days and a.max_additional_days <= 0:
        raise bad_request("max_additional_days must be a positive integer when additional days are allowed.")


@router.get("/activity-types", response_model=list[ActivityOut])
def list_activities(db: Session = Depends(get_db)):
    return db.scalars(select(ActivityType).order_by(ActivityType.sort_order, ActivityType.name)).all()


@router.post("/activity-types", response_model=ActivityOut, status_code=201)
def create_activity(body: ActivityCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    a = ActivityType(id=uuid.uuid4(), **body.model_dump())
    _check_activity(a)
    db.add(a)
    db.flush()
    audit.record(db, "activity_type.created", admin, entity_type="activity_type", entity_id=a.id, new=_snap(a, ACT_FIELDS))
    commit(db)
    return a


@router.patch("/activity-types/{activity_id}", response_model=ActivityOut)
def update_activity(activity_id: uuid.UUID, body: ActivityUpdate, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    a = db.get(ActivityType, activity_id)
    if a is None:
        raise not_found("Activity type")
    prev = _snap(a, ACT_FIELDS)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    _check_activity(a)
    new = _snap(a, ACT_FIELDS)
    action = "activity_type.updated"
    if prev["is_active"] != new["is_active"]:
        action = "activity_type.activated" if a.is_active else "activity_type.deactivated"
    # Existing bookings keep their own duration snapshot; nothing else is touched.
    audit.record(db, action, admin, entity_type="activity_type", entity_id=a.id, previous=prev, new=new)
    commit(db)
    return a


# =============================================================== holidays
@router.get("/holidays", response_model=list[HolidayOut])
def list_holidays(year: int | None = None, db: Session = Depends(get_db)):
    q = select(Holiday).order_by(Holiday.holiday_date)
    if year:
        q = q.where(Holiday.holiday_date.between(date(year, 1, 1), date(year, 12, 31)))
    return db.scalars(q).all()


def _holiday_added(db, h: Holiday, admin) -> list:
    return conflicts.flag_new_non_working(db, {h.holiday_date}, "holiday", f"Organisation holiday '{h.name}'",
                                          f"holiday:{h.id}:{h.holiday_date}", admin)


def _holiday_removed(db, d: date, name: str, hid, admin) -> list:
    return conflicts.flag_removed_non_working(db, {d}, "holiday", f"Organisation holiday '{name}' ({d})",
                                              f"holiday-removed:{hid}:{d}", admin)


@router.post("/holidays", status_code=201)
def create_holiday(body: HolidayIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.scalar(select(Holiday.id).where(Holiday.holiday_date == body.holiday_date)):
        raise conflict("A holiday already exists on that date.", "duplicate")
    h = Holiday(id=uuid.uuid4(), **body.model_dump())
    db.add(h)
    db.flush()
    flagged = _holiday_added(db, h, admin)
    audit.record(db, "holiday.created", admin, entity_type="holiday", entity_id=h.id,
                 new={**body.model_dump(mode="json"), "flagged_bookings": flagged})
    commit(db)
    return {"holiday": HolidayOut.model_validate(h), "flagged_bookings": [str(x) for x in flagged]}


@router.patch("/holidays/{holiday_id}")
def update_holiday(holiday_id: uuid.UUID, body: HolidayUpdate, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    h = db.get(Holiday, holiday_id)
    if h is None:
        raise not_found("Holiday")
    prev = _snap(h, ("name", "holiday_date", "description"))
    data = body.model_dump(exclude_unset=True)
    old_date = h.holiday_date
    if "holiday_date" in data and data["holiday_date"] != old_date:
        if db.scalar(select(Holiday.id).where(Holiday.holiday_date == data["holiday_date"], Holiday.id != h.id)):
            raise conflict("A holiday already exists on that date.", "duplicate")
    for k, v in data.items():
        setattr(h, k, v)
    db.flush()
    flagged = []
    if h.holiday_date != old_date:
        flagged += _holiday_removed(db, old_date, prev["name"], h.id, admin)
        flagged += _holiday_added(db, h, admin)
    audit.record(db, "holiday.updated", admin, entity_type="holiday", entity_id=h.id, previous=prev,
                 new={**_snap(h, ("name", "holiday_date", "description")), "flagged_bookings": flagged})
    commit(db)
    return {"holiday": HolidayOut.model_validate(h), "flagged_bookings": [str(x) for x in flagged]}


@router.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    h = db.get(Holiday, holiday_id)
    if h is None:
        raise not_found("Holiday")
    prev = _snap(h, ("name", "holiday_date", "description"))
    flagged = _holiday_removed(db, h.holiday_date, h.name, h.id, admin)
    db.delete(h)
    audit.record(db, "holiday.deleted", admin, entity_type="holiday", entity_id=holiday_id, previous=prev,
                 new={"flagged_bookings": flagged})
    commit(db)
    return {"ok": True, "flagged_bookings": [str(x) for x in flagged]}


def _parse_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date '{s}' (use YYYY-MM-DD)")


def _read_rows(filename: str, content: bytes) -> list[dict]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(c or "").strip().lower() for c in next(it, [])]
        return [dict(zip(header, row)) for row in it if any(c not in (None, "") for c in row)]
    if name.endswith(".csv") or not name:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        reader.fieldnames = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
        return [r for r in reader if any((v or "").strip() for v in r.values() if isinstance(v, str))]
    raise bad_request("Unsupported file type. Upload a .csv or .xlsx file.")


@router.post("/holidays/import")
async def import_holidays(file: UploadFile = File(...), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    content = await file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise bad_request("File too large (max 2 MB).")
    try:
        rows = _read_rows(file.filename, content)
    except UnicodeDecodeError:
        raise bad_request("CSV must be UTF-8 encoded.")
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "status_code"):
            raise
        raise bad_request(f"Could not read file: {e}")
    if len(rows) > 1000:
        raise bad_request("Too many rows (max 1000).")
    created, updated, errors, flagged = 0, 0, [], []
    for idx, row in enumerate(rows, start=2):
        name = str(row.get("name") or row.get("holiday") or row.get("holiday name") or "").strip()
        raw_date = row.get("date") or row.get("holiday_date") or row.get("holiday date")
        desc = row.get("description")
        desc = str(desc).strip() if desc not in (None, "") else None
        if not name or not raw_date:
            errors.append({"row": idx, "error": "name and date are required"})
            continue
        if len(name) > 200:
            errors.append({"row": idx, "error": "name too long"})
            continue
        try:
            d = _parse_date(raw_date)
        except ValueError as e:
            errors.append({"row": idx, "error": str(e)})
            continue
        h = db.scalars(select(Holiday).where(Holiday.holiday_date == d)).first()
        if h:
            if h.name != name or h.description != desc:
                h.name, h.description = name, desc
                updated += 1
        else:
            h = Holiday(id=uuid.uuid4(), name=name, holiday_date=d, description=desc)
            db.add(h)
            db.flush()
            flagged += _holiday_added(db, h, admin)
            created += 1
    audit.record(db, "holiday.imported", admin, entity_type="holiday", entity_id=file.filename,
                 new={"created": created, "updated": updated, "errors": len(errors), "flagged_bookings": flagged})
    commit(db)
    return {"created": created, "updated": updated, "errors": errors, "flagged_bookings": [str(x) for x in flagged]}


# =============================================================== leave
def _leave_out(lv: ResourceLeave) -> LeaveOut:
    return LeaveOut(id=lv.id, resource_id=lv.resource_id, resource_code=lv.resource.code,
                    resource_display_name=lv.resource.display_name, engineer_name=lv.resource.engineer_name,
                    start_date=lv.start_date, end_date=lv.end_date, leave_type=lv.leave_type, reason=lv.reason,
                    status=lv.status)


LEAVE_FIELDS = ("resource_id", "start_date", "end_date", "leave_type", "reason", "status")


@router.get("/leaves", response_model=list[LeaveOut])
def list_leaves(resource_id: uuid.UUID | None = None, start: date | None = None, end: date | None = None,
                include_cancelled: bool = False, db: Session = Depends(get_db)):
    q = select(ResourceLeave).order_by(ResourceLeave.start_date.desc())
    if resource_id:
        q = q.where(ResourceLeave.resource_id == resource_id)
    if start:
        q = q.where(ResourceLeave.end_date >= start)
    if end:
        q = q.where(ResourceLeave.start_date <= end)
    if not include_cancelled:
        q = q.where(ResourceLeave.status == "active")
    return [_leave_out(lv) for lv in db.scalars(q.limit(1000)).unique().all()]


@router.post("/leaves", status_code=201)
def create_leave(body: LeaveIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.end_date < body.start_date:
        raise bad_request("Leave end date must be on or after the start date.")
    if (body.end_date - body.start_date).days > 366:
        raise bad_request("Leave period cannot exceed one year.")
    r = db.get(SecurityResource, body.resource_id)
    if r is None:
        raise not_found("Resource")
    lv = ResourceLeave(id=uuid.uuid4(), created_by=admin.id, **body.model_dump())
    db.add(lv)
    db.flush()
    dates = set(expand_ranges([(lv.start_date, lv.end_date)]))
    flagged = conflicts.flag_new_non_working(db, dates, "leave", f"Leave for {r.display_name} ({r.engineer_name})",
                                             f"leave:{lv.id}:{lv.start_date}:{lv.end_date}", admin, resource_id=r.id)
    audit.record(db, "leave.created", admin, entity_type="leave", entity_id=lv.id,
                 new={**_snap(lv, LEAVE_FIELDS), "flagged_bookings": flagged})
    commit(db)
    db.refresh(lv)
    return {"leave": _leave_out(lv), "flagged_bookings": [str(x) for x in flagged]}


@router.patch("/leaves/{leave_id}")
def update_leave(leave_id: uuid.UUID, body: LeaveUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    lv = db.get(ResourceLeave, leave_id)
    if lv is None or lv.status != "active":
        raise not_found("Leave")
    prev = _snap(lv, LEAVE_FIELDS)
    old_dates = set(expand_ranges([(lv.start_date, lv.end_date)]))
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(lv, k, v)
    if lv.end_date < lv.start_date:
        raise bad_request("Leave end date must be on or after the start date.")
    db.flush()
    new_dates = set(expand_ranges([(lv.start_date, lv.end_date)]))
    label = f"Leave for {lv.resource.display_name} ({lv.resource.engineer_name})"
    flagged = conflicts.flag_new_non_working(db, new_dates - old_dates, "leave", label,
                                             f"leave:{lv.id}:{lv.start_date}:{lv.end_date}", admin, resource_id=lv.resource_id)
    flagged += conflicts.flag_removed_non_working(db, old_dates - new_dates, "leave", label,
                                                  f"leave-removed:{lv.id}:{lv.start_date}:{lv.end_date}", admin,
                                                  resource_id=lv.resource_id)
    audit.record(db, "leave.updated", admin, entity_type="leave", entity_id=lv.id, previous=prev,
                 new={**_snap(lv, LEAVE_FIELDS), "flagged_bookings": flagged})
    commit(db)
    return {"leave": _leave_out(lv), "flagged_bookings": [str(x) for x in flagged]}


@router.delete("/leaves/{leave_id}")
def cancel_leave(leave_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    lv = db.get(ResourceLeave, leave_id)
    if lv is None or lv.status != "active":
        raise not_found("Leave")
    prev = _snap(lv, LEAVE_FIELDS)
    lv.status = "cancelled"
    db.flush()
    flagged = conflicts.flag_removed_non_working(
        db, set(expand_ranges([(lv.start_date, lv.end_date)])), "leave",
        f"Leave for {lv.resource.display_name} ({lv.resource.engineer_name})", f"leave-removed:{lv.id}", admin,
        resource_id=lv.resource_id)
    audit.record(db, "leave.cancelled", admin, entity_type="leave", entity_id=lv.id, previous=prev,
                 new={"status": "cancelled", "flagged_bookings": flagged})
    commit(db)
    return {"ok": True, "flagged_bookings": [str(x) for x in flagged]}


# =============================================================== users
def _users_out(db: Session, users) -> list:
    from ..models import SSOProvider

    names = {p.id: p.display_name for p in db.scalars(select(SSOProvider)).all()}
    return [user_out(u, names.get(u.sso_provider_id)) for u in users]


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return _users_out(db, db.scalars(select(User).order_by(User.full_name)).unique().all())


@router.post("/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.password:
        err = validate_password_strength(body.password)
        if err:
            raise bad_request(err)
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise conflict("A user with that email already exists.", "duplicate")
    u = User(id=uuid.uuid4(), email=body.email.lower(), full_name=body.full_name,
             password_hash=hash_password(body.password) if body.password else None,
             role_id=ROLE_ADMIN_ID if body.role == "admin" else ROLE_REQUESTER_ID)
    db.add(u)
    db.flush()
    db.refresh(u)
    audit.record(db, "user.created", admin, entity_type="user", entity_id=u.id,
                 new={"email": u.email, "full_name": u.full_name, "role": body.role, "sso_only": not body.password})
    commit(db)
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        raise not_found("User")
    data = body.model_dump(exclude_unset=True)
    if u.id == admin.id and (data.get("is_active") is False or data.get("role") == "requester"):
        raise bad_request("You cannot deactivate or demote your own account.")
    prev = {"full_name": u.full_name, "role": u.role_name, "is_active": u.is_active}
    if "full_name" in data:
        u.full_name = data["full_name"]
    revoke = False
    if "role" in data:
        new_role = ROLE_ADMIN_ID if data["role"] == "admin" else ROLE_REQUESTER_ID
        revoke = revoke or new_role != u.role_id
        u.role_id = new_role
    if "is_active" in data:
        revoke = revoke or data["is_active"] != u.is_active
        u.is_active = data["is_active"]
    if data.get("password"):
        err = validate_password_strength(data["password"])
        if err:
            raise bad_request(err)
        u.password_hash = hash_password(data["password"])
        revoke = True
    elif data.get("remove_password"):
        if u.id == admin.id:
            raise bad_request("You cannot remove your own password here.")
        if u.sso_provider_id is None:
            raise bad_request("Link the account to SSO before removing its password, or it could never sign in.")
        u.password_hash = None
        revoke = True
    if data.get("unlink_sso"):
        if u.password_hash is None and not data.get("password"):
            raise bad_request("Set a password before unlinking SSO, or the account could never sign in.")
        u.sso_provider_id, u.sso_subject = None, None
        revoke = True
    if revoke:
        u.token_version += 1
    db.flush()
    db.refresh(u)
    audit.record(db, "user.updated", admin, entity_type="user", entity_id=u.id, previous=prev,
                 new={"full_name": u.full_name, "role": u.role_name, "is_active": u.is_active,
                      "password_reset": bool(data.get("password")), "password_removed": bool(data.get("remove_password")),
                      "sso_unlinked": bool(data.get("unlink_sso"))})
    commit(db)
    return _users_out(db, [u])[0]


# =============================================================== settings / email
@router.get("/settings")
def get_settings_(db: Session = Depends(get_db)):
    from ..config import get_settings

    env = get_settings()
    return {
        "values": settings_service.get_all(db),
        "descriptions": {k: d for k, (_, d) in settings_service.DEFAULTS.items()},
        # informational only - secrets are NEVER returned
        "environment": {"email_backend": env.email_backend, "smtp_host": env.smtp_host, "smtp_port": env.smtp_port,
                        "smtp_password_configured": bool(env.smtp_password)},
    }


@router.put("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    changes = {}
    for k, v in body.values.items():
        try:
            old, new = settings_service.set_setting(db, k, v, admin.id)
        except KeyError:
            raise bad_request(f"Unknown setting '{k}'.")
        except ValueError as e:
            raise bad_request(str(e))
        if old != new:
            changes[k] = {"old": old, "new": new}
    if changes:
        audit.record(db, "settings.updated", admin, entity_type="settings", entity_id="application_settings",
                     previous={k: c["old"] for k, c in changes.items()}, new={k: c["new"] for k, c in changes.items()})
    commit(db)
    return {"values": settings_service.get_all(db)}


def _ensure_templates(db: Session) -> None:
    existing = set(db.scalars(select(EmailTemplate.key)))
    for key, t in notifications.DEFAULT_TEMPLATES.items():
        if key not in existing:
            db.add(EmailTemplate(id=uuid.uuid4(), key=key, name=t["name"], subject_template=t["subject"], body_template=t["body"]))
    db.flush()


@router.get("/email-templates", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)):
    _ensure_templates(db)
    commit(db)
    return db.scalars(select(EmailTemplate).order_by(EmailTemplate.key)).all()


@router.get("/email-templates/variables")
def template_variables():
    return sorted(notifications.ALLOWED_VARIABLES)


@router.put("/email-templates/{key}", response_model=TemplateOut)
def update_template(key: str, body: TemplateUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _ensure_templates(db)
    t = db.scalars(select(EmailTemplate).where(EmailTemplate.key == key)).first()
    if t is None:
        raise not_found("Template")
    prev = {"subject_template": t.subject_template, "body_template": t.body_template, "is_active": t.is_active}
    data = body.model_dump(exclude_unset=True)
    subject = data.get("subject_template", t.subject_template)
    bodytxt = data.get("body_template", t.body_template)
    try:
        notifications.validate_template(subject, bodytxt)
    except ValueError as e:
        raise bad_request(str(e))
    for k, v in data.items():
        setattr(t, k, v)
    t.updated_by = admin.id
    audit.record(db, "email_template.updated", admin, entity_type="email_template", entity_id=key, previous=prev,
                 new={"subject_template": t.subject_template, "body_template": t.body_template, "is_active": t.is_active})
    commit(db)
    return t


@router.post("/email-templates/{key}/preview")
def preview_template(key: str, body: TemplateUpdate, db: Session = Depends(get_db)):
    _ensure_templates(db)
    t = db.scalars(select(EmailTemplate).where(EmailTemplate.key == key)).first()
    if t is None:
        raise not_found("Template")
    subject = body.subject_template or t.subject_template
    bodytxt = body.body_template or t.body_template
    try:
        notifications.validate_template(subject, bodytxt)
    except ValueError as e:
        raise bad_request(str(e))
    sample = {v: f"<{v}>" for v in notifications.ALLOWED_VARIABLES}
    sample.update({"Booking ID": "550e8400-e29b-41d4-a716-446655440000", "Yes/No": "Yes", "PCI DSS Scope": "Yes"})
    db.rollback()
    return {"subject": notifications.render(subject, sample), "body": notifications.render(bodytxt, sample)}


@router.get("/email-logs", response_model=list[EmailLogOut])
def email_logs(status: str | None = None, booking_id: uuid.UUID | None = None, recipient: str | None = Query(None, max_length=254),
               limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    q = select(EmailNotificationLog).order_by(EmailNotificationLog.created_at.desc())
    if status:
        q = q.where(EmailNotificationLog.status == status)
    if booking_id:
        q = q.where(EmailNotificationLog.booking_id == booking_id)
    if recipient:
        q = q.where(EmailNotificationLog.recipient.ilike(f"%{recipient}%"))
    return db.scalars(q.limit(limit)).all()


@router.post("/email-logs/{log_id}/retry", response_model=EmailLogOut)
def retry_email(log_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    row = db.get(EmailNotificationLog, log_id)
    if row is None:
        raise not_found("Email")
    if row.status == "sent":
        raise conflict("This email was already delivered.", "invalid_state")
    row.status, row.next_attempt_at = "queued", now_utc()
    row.max_attempts = max(row.max_attempts, row.attempts + 3)
    audit.record(db, "email.retry_requested", admin, entity_type="email", entity_id=row.id, booking_id=row.booking_id)
    commit(db)
    return row

