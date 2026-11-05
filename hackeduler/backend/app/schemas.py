"""Request/response schemas.

Requester-facing input models use ``extra='forbid'``: fields such as end_date,
duration_days, status or force are REJECTED rather than silently ignored, so a
requester cannot even attempt to supply backend-calculated or admin-only values.
Requester-facing output models never contain engineer identities.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from .models import BookingStatus


_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def _validate_email(v: str) -> str:
    v = v.strip()
    if len(v) > 254 or not _EMAIL_RE.match(v):
        raise ValueError("value is not a valid email address")
    return v


# Accepts internal domains such as *.local that strict validators reject; still rejects malformed / header-injection input.
EmailStr = Annotated[str, AfterValidator(_validate_email)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth / users
class LoginIn(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None = None
    has_password: bool = True
    sso_provider_id: uuid.UUID | None = None
    sso_provider_name: str | None = None
    last_login_method: str | None = None
    deleted_at: datetime | None = None
    product_id: uuid.UUID | None = None
    product_name: str | None = None
    implementation_id: uuid.UUID | None = None
    implementation_name: str | None = None


class UserCreate(Strict):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=256,
                                 description="Omit to create an SSO-only account (pre-provisioning)")
    role: Literal["admin", "requester"]
    product_id: uuid.UUID | None = None
    implementation_id: uuid.UUID | None = None


class UserUpdate(Strict):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Literal["admin", "requester"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
    remove_password: bool | None = None
    unlink_sso: bool | None = None
    product_id: uuid.UUID | None = Field(default=None, description="null clears the product (and implementation)")
    implementation_id: uuid.UUID | None = None


class PasswordChange(Strict):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


# ---------------------------------------------------------------- resources
class ResourcePublic(ORM):
    """Anonymous view for requesters - NO engineer identity."""
    id: uuid.UUID
    code: str
    display_name: str
    is_active: bool


class ResourceAdmin(ORM):
    id: uuid.UUID
    sequence_no: int
    code: str
    display_name: str
    engineer_name: str
    engineer_email: str | None
    notes: str | None
    is_active: bool
    deactivated_at: datetime | None
    inactive_from: date | None = None
    inactive_reason: str | None = None
    deleted_at: datetime | None = None
    created_at: datetime


class ResourceCreate(Strict):
    engineer_name: str = Field(min_length=1, max_length=200)
    engineer_email: EmailStr | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ResourceUpdate(Strict):
    engineer_name: str | None = Field(default=None, min_length=1, max_length=200)
    engineer_email: EmailStr | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = Field(default=None, description="false = deactivate immediately (today); true = reactivate")
    inactive_from: date | None = Field(default=None, description="Deactivate from this date (today or later); null cancels a scheduled deactivation")
    reason: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------- activity types
class ActivityOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    base_duration_days: int | None
    requires_resource: bool = True
    allow_additional_days: bool
    max_additional_days: int
    is_active: bool
    sort_order: int


class ActivityCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    base_duration_days: int | None = Field(default=None, gt=0, le=250, strict=True,
                                           description="Required when the activity needs a security resource")
    requires_resource: bool = True
    allow_additional_days: bool = False
    max_additional_days: int = Field(default=0, ge=0, le=250, strict=True)
    sort_order: int = 0


class ActivityUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    base_duration_days: int | None = Field(default=None, gt=0, le=250, strict=True)
    requires_resource: bool | None = None
    allow_additional_days: bool | None = None
    max_additional_days: int | None = Field(default=None, ge=0, le=250, strict=True)
    is_active: bool | None = None
    sort_order: int | None = None


# ---------------------------------------------------------------- holidays / leave
class HolidayOut(ORM):
    id: uuid.UUID
    name: str
    holiday_date: date
    description: str | None


class HolidayIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    holiday_date: date
    description: str | None = Field(default=None, max_length=2000)


class HolidayUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    holiday_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)


class LeaveOut(ORM):
    id: uuid.UUID
    resource_id: uuid.UUID
    resource_code: str
    resource_display_name: str
    engineer_name: str
    start_date: date
    end_date: date
    leave_type: str | None
    reason: str | None
    status: str


class LeaveIn(Strict):
    resource_id: uuid.UUID
    start_date: date
    end_date: date
    leave_type: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)


class LeaveUpdate(Strict):
    start_date: date | None = None
    end_date: date | None = None
    leave_type: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------- bookings
class AvailabilityQuery(Strict):
    resource_id: uuid.UUID
    activity_type_id: uuid.UUID
    start_date: date
    additional_days: int = Field(default=0, ge=0, le=250)


class AdminAvailabilityQuery(AvailabilityQuery):
    exclude_booking_id: uuid.UUID | None = None


class AutoAvailabilityQuery(Strict):
    """Requester preview without choosing a resource; the system assigns one."""
    activity_type_id: uuid.UUID
    start_date: date | None = None
    additional_days: int = Field(default=0, ge=0, le=250)


class BookingCreate(Strict):
    """Requester submission. NO end_date / duration / status / force fields - those are backend-controlled."""
    application_name: str = Field(min_length=1, max_length=255)
    application_version: str = Field(min_length=1, max_length=100)
    activity_type_id: uuid.UUID
    pci_dss_scope: bool
    resource_id: uuid.UUID | None = Field(default=None, description="Optional preferred resource; omit to assign automatically")
    start_date: date | None = Field(default=None, description="Required unless the activity needs no security resource")
    poc_name: str = Field(min_length=1, max_length=255)
    poc_email: EmailStr
    additional_comments: str | None = Field(default=None, max_length=4000)
    additional_days: int = Field(default=0, ge=0, le=250)
    implementation_id: uuid.UUID | None = None


class ForceIn(Strict):
    confirm: bool
    reason: str = Field(min_length=1, max_length=2000)


class AdminBookingCreate(BookingCreate):
    initial_status: Literal["approved", "pending_approval"] = "approved"
    duration_days: int | None = Field(default=None, gt=0, le=250)
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=2000)
    force: ForceIn | None = None
    product_id: uuid.UUID | None = None


class BookingModify(Strict):
    resource_id: uuid.UUID | None = None
    start_date: date | None = None
    activity_type_id: uuid.UUID | None = None
    additional_days: int | None = Field(default=None, ge=0, le=250)
    duration_days: int | None = Field(default=None, gt=0, le=250)
    end_date: date | None = None
    recalculate: bool | None = None
    application_name: str | None = Field(default=None, min_length=1, max_length=255)
    application_version: str | None = Field(default=None, min_length=1, max_length=100)
    pci_dss_scope: bool | None = None
    poc_name: str | None = Field(default=None, min_length=1, max_length=255)
    poc_email: EmailStr | None = None
    additional_comments: str | None = Field(default=None, max_length=4000)
    product_id: uuid.UUID | None = None
    implementation_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    force: ForceIn | None = None


class CompleteIn(Strict):
    note: str | None = Field(default=None, max_length=2000)


class ApproveIn(Strict):
    force: ForceIn | None = None


class RejectIn(Strict):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A rejection reason is required")
        return v


class CancelIn(Strict):
    reason: str = Field(min_length=1, max_length=2000)


class ChangeRequestIn(Strict):
    request_type: Literal["cancel", "reschedule"]
    reason: str = Field(min_length=1, max_length=2000)
    proposed_start_date: date | None = None
    proposed_resource_id: uuid.UUID | None = None


class ChangeDecisionIn(Strict):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)
    force: ForceIn | None = None


class BookingRequesterOut(BaseModel):
    """Requester view of THEIR OWN booking - anonymous resource only, no admin internals."""
    id: uuid.UUID
    application_name: str
    application_version: str
    activity_type_id: uuid.UUID
    activity_name: str
    duration_days: int | None
    additional_days: int
    pci_dss_scope: bool
    requires_resource: bool = True
    resource_id: uuid.UUID | None
    resource_display_name: str | None
    start_date: date | None
    end_date: date | None
    product_id: uuid.UUID | None = None
    product_name: str | None = None
    implementation_id: uuid.UUID | None = None
    implementation_name: str | None = None
    is_mine: bool = True
    requester_name: str | None = None
    poc_name: str
    poc_email: str
    additional_comments: str | None
    status: str
    status_label: str
    submitted_at: datetime
    expires_at: datetime | None
    rejection_reason: str | None
    cancellation_reason: str | None
    pending_change_request: dict | None = None


class BookingAdminOut(BookingRequesterOut):
    resource_code: str | None
    engineer_name: str | None
    requester_id: uuid.UUID
    requester_email: str
    source: str
    is_force_allocated: bool
    needs_review: bool
    duration_overridden: bool
    base_duration_snapshot: int | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    rejected_by: uuid.UUID | None
    rejected_at: datetime | None
    cancelled_by: uuid.UUID | None
    cancelled_at: datetime | None
    version: int
    open_conflicts: int = 0


def booking_requester_out(b, pending_cr=None, viewer_id=None) -> BookingRequesterOut:
    """``viewer_id`` set => a product colleague may be viewing: flag ownership, show the requester's name only."""
    mine = viewer_id is None or b.requester_id == viewer_id
    return BookingRequesterOut(
        id=b.id, application_name=b.application_name, application_version=b.application_version,
        activity_type_id=b.activity_type_id, activity_name=b.activity_name_snapshot, duration_days=b.duration_days,
        additional_days=b.additional_days, pci_dss_scope=b.pci_dss_scope, requires_resource=b.requires_resource,
        resource_id=b.resource_id, resource_display_name=b.resource.display_name if b.resource else None,
        start_date=b.start_date, end_date=b.end_date,
        product_id=b.product_id, product_name=b.product.name if b.product else None,
        implementation_id=b.implementation_id, implementation_name=b.implementation.name if b.implementation else None,
        is_mine=mine, requester_name=b.requester.full_name if b.requester else None,
        poc_name=b.poc_name, poc_email=b.poc_email, additional_comments=b.additional_comments, status=b.status,
        status_label=BookingStatus.LABELS[b.status], submitted_at=b.submitted_at, expires_at=b.expires_at,
        rejection_reason=b.rejection_reason, cancellation_reason=b.cancellation_reason,
        pending_change_request=pending_cr,
    )


def booking_admin_out(b, pending_cr=None, open_conflicts: int = 0) -> BookingAdminOut:
    base = booking_requester_out(b, pending_cr).model_dump()
    return BookingAdminOut(
        **base, resource_code=b.resource.code if b.resource else None,
        engineer_name=b.resource.engineer_name if b.resource else None, requester_id=b.requester_id,
        requester_email=b.requester.email, source=b.source,
        is_force_allocated=b.is_force_allocated, needs_review=b.needs_review, duration_overridden=b.duration_overridden,
        base_duration_snapshot=b.base_duration_snapshot, approved_by=b.approved_by, approved_at=b.approved_at,
        rejected_by=b.rejected_by, rejected_at=b.rejected_at, cancelled_by=b.cancelled_by, cancelled_at=b.cancelled_at,
        version=b.version, open_conflicts=open_conflicts,
    )


# ---------------------------------------------------------------- conflicts / audit / email / settings
class ConflictResolveIn(Strict):
    resolution_note: str = Field(min_length=1, max_length=2000)


class AuditOut(ORM):
    id: uuid.UUID
    booking_id: uuid.UUID | None
    entity_type: str
    entity_id: str | None
    action: str
    previous_value: Any
    new_value: Any
    actor_id: uuid.UUID | None
    actor_email: str | None
    actor_role: str | None
    reason: str | None
    request_id: str | None
    ip_address: str | None
    created_at: datetime


class TemplateOut(ORM):
    id: uuid.UUID
    key: str
    name: str
    subject_template: str
    body_template: str
    is_active: bool
    updated_at: datetime


class TemplateUpdate(Strict):
    subject_template: str | None = Field(default=None, min_length=1, max_length=300)
    body_template: str | None = Field(default=None, min_length=1, max_length=20000)
    is_active: bool | None = None


class EmailLogOut(ORM):
    id: uuid.UUID
    template_key: str
    booking_id: uuid.UUID | None
    recipient: str
    subject: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime


class SettingsUpdate(Strict):
    values: dict[str, Any]
