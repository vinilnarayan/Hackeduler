"""ORM models. The authoritative DDL lives in alembic/versions/0001_initial_schema.py."""
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Table, Text, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONType = JSONB().with_variant(JSON(), "sqlite")


class BookingStatus:
    PENDING = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"

    ALL = (PENDING, APPROVED, REJECTED, CANCELLED, COMPLETED, EXPIRED)
    ACTIVE = (PENDING, APPROVED)  # statuses that hold a reservation
    LABELS = {
        PENDING: "Pending Approval",
        APPROVED: "Approved",
        REJECTED: "Rejected",
        CANCELLED: "Cancelled",
        COMPLETED: "Completed",
        EXPIRED: "Expired",
    }


class LockStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RELEASED = "released"
    ACTIVE = (PENDING, CONFIRMED)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


ROLE_ADMIN_ID = 1
ROLE_REQUESTER_ID = 2
ROLE_RESOURCE_ID = 3


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sso_provider_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sso_providers.id", ondelete="SET NULL"))
    sso_subject: Mapped[str | None] = mapped_column(Text)
    last_login_method: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    implementation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("implementations.id"))
    # Only for the 'resource' (security engineer) role: the resource this person is
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("security_resources.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    role: Mapped[Role] = relationship(lazy="joined")
    product: Mapped["Product | None"] = relationship(lazy="joined", foreign_keys=[product_id])
    implementation: Mapped["Implementation | None"] = relationship(lazy="joined", foreign_keys=[implementation_id])

    resource: Mapped["SecurityResource | None"] = relationship(lazy="joined", foreign_keys=[resource_id])

    @property
    def role_name(self) -> str:
        return self.role.name

    @property
    def is_admin(self) -> bool:
        return self.role_id == ROLE_ADMIN_ID

    @property
    def is_resource(self) -> bool:
        return self.role_id == ROLE_RESOURCE_ID


class Product(Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Implementation(Base):
    __tablename__ = "implementations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product: Mapped[Product] = relationship(lazy="joined")


class SSOProvider(Base):
    """An OpenID Connect identity provider configured by an admin. The client secret is stored encrypted."""
    __tablename__ = "sso_providers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    provider_type: Mapped[str] = mapped_column(Text, default="generic")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    issuer: Mapped[str] = mapped_column(Text)
    discovery_url: Mapped[str | None] = mapped_column(Text)
    authorization_endpoint: Mapped[str | None] = mapped_column(Text)
    token_endpoint: Mapped[str | None] = mapped_column(Text)
    jwks_uri: Mapped[str | None] = mapped_column(Text)
    userinfo_endpoint: Mapped[str | None] = mapped_column(Text)
    end_session_endpoint: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str] = mapped_column(Text)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    token_auth_method: Mapped[str] = mapped_column(Text, default="client_secret_post")
    scopes: Mapped[str] = mapped_column(Text, default="openid email profile")
    extra_auth_params: Mapped[Any] = mapped_column(JSONType, default=dict)
    use_pkce: Mapped[bool] = mapped_column(Boolean, default=True)
    fetch_userinfo: Mapped[bool] = mapped_column(Boolean, default=False)
    rp_initiated_logout: Mapped[bool] = mapped_column(Boolean, default=False)
    email_claim: Mapped[str] = mapped_column(Text, default="email")
    name_claim: Mapped[str] = mapped_column(Text, default="name")
    groups_claim: Mapped[str] = mapped_column(Text, default="groups")
    admin_groups: Mapped[Any] = mapped_column(JSONType, default=list)
    requester_groups: Mapped[Any] = mapped_column(JSONType, default=list)
    allowed_email_domains: Mapped[Any] = mapped_column(JSONType, default=list)
    auto_provision: Mapped[bool] = mapped_column(Boolean, default=True)
    default_role: Mapped[str] = mapped_column(Text, default="requester")
    sync_role_on_login: Mapped[bool] = mapped_column(Boolean, default=True)
    link_existing_by_email: Mapped[bool] = mapped_column(Boolean, default=True)
    clock_skew_seconds: Mapped[int] = mapped_column(Integer, default=120)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SecurityResource(Base):
    __tablename__ = "security_resources"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence_no: Mapped[int] = mapped_column(Integer, unique=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text, unique=True)
    engineer_name: Mapped[str] = mapped_column(Text)
    engineer_email: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # First date the resource is unavailable (scheduled or immediate deactivation). NULL = no deactivation planned.
    inactive_from: Mapped[date | None] = mapped_column(Date)
    inactive_reason: Mapped[str | None] = mapped_column(Text)
    # False = admin-only: hidden from the requester calendar / lists, never auto-assigned, not selectable by requesters
    visible_to_requesters: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def inactive_on(self, d: date) -> bool:
        """True if the resource cannot work on ``d``."""
        if self.inactive_from is not None:
            return d >= self.inactive_from
        return not self.is_active
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ActivityType(Base):
    __tablename__ = "activity_types"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    base_duration_days: Mapped[int | None] = mapped_column(Integer)
    requires_resource: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_additional_days: Mapped[bool] = mapped_column(Boolean, default=False)
    max_additional_days: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # False = only admins can book this type (e.g. Manual Allocation); requesters never see it.
    visible_to_requesters: Mapped[bool] = mapped_column(Boolean, default=True)
    # Activity initiation email: False = never; days NULL = global default; details NULL = built-in checklist
    initiation_email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    initiation_days_before: Mapped[int | None] = mapped_column(Integer)
    initiation_details: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Holiday(Base):
    __tablename__ = "holidays"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ResourceLeave(Base):
    __tablename__ = "resource_leaves"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("security_resources.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    leave_type: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    resource: Mapped[SecurityResource] = relationship(lazy="joined")


booking_extra_resources = Table(
    "booking_extra_resources", Base.metadata,
    Column("booking_id", UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True),
    Column("resource_id", UUID(as_uuid=True), ForeignKey("security_resources.id"), primary_key=True),
)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("security_resources.id"))
    activity_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_types.id"))
    activity_name_snapshot: Mapped[str] = mapped_column(Text)
    base_duration_snapshot: Mapped[int | None] = mapped_column(Integer)
    additional_days: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    requires_resource: Mapped[bool] = mapped_column(Boolean, default=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    implementation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("implementations.id"))
    duration_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    application_name: Mapped[str] = mapped_column(Text)
    application_version: Mapped[str] = mapped_column(Text)
    pci_dss_scope: Mapped[bool] = mapped_column(Boolean)
    poc_name: Mapped[str] = mapped_column(Text)
    poc_email: Mapped[str] = mapped_column(Text)
    additional_comments: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="requester")
    is_force_allocated: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Report sharing: set by the assigned engineer (or an admin)
    report_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    report_type: Mapped[str | None] = mapped_column(Text)            # 'V1' | 'Met'
    report_comments: Mapped[str | None] = mapped_column(Text)
    report_shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    initiation_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initiation_email_for_start: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    resource: Mapped[SecurityResource | None] = relationship(lazy="joined")
    requester: Mapped[User] = relationship(foreign_keys=[requester_id], lazy="joined")
    activity_type: Mapped[ActivityType] = relationship(lazy="joined")
    product: Mapped[Product | None] = relationship(lazy="joined", foreign_keys=[product_id])
    implementation: Mapped[Implementation | None] = relationship(lazy="joined", foreign_keys=[implementation_id])
    # Additional security resources working the same booking (admin multi-resource allocation). The primary
    # resource stays in ``resource_id``; every resource (primary + extras) has its own locks.
    extra_resources: Mapped[list["SecurityResource"]] = relationship(secondary="booking_extra_resources", lazy="selectin",
                                                                      order_by="SecurityResource.sequence_no")

    @property
    def extra_resource_ids(self) -> list[uuid.UUID]:
        return [r.id for r in self.extra_resources]

    @classmethod
    def uses_resource(cls, resource_id: uuid.UUID):
        """SQL clause: the booking's primary resource OR one of its additional resources is ``resource_id``."""
        return or_(cls.resource_id == resource_id,
                   cls.id.in_(select(booking_extra_resources.c.booking_id).where(booking_extra_resources.c.resource_id == resource_id)))


class BookingStatusHistory(Base):
    __tablename__ = "booking_status_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingResourceLock(Base):
    __tablename__ = "booking_resource_locks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("security_resources.id"))
    work_date: Mapped[date] = mapped_column(Date)
    lock_status: Mapped[str] = mapped_column(Text)
    is_forced: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BookingChangeRequest(Base):
    __tablename__ = "booking_change_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    request_type: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    proposed_start_date: Mapped[date | None] = mapped_column(Date)
    proposed_resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("security_resources.id"))
    status: Mapped[str] = mapped_column(Text, default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booking: Mapped[Booking] = relationship(lazy="joined")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    previous_value: Mapped[Any] = mapped_column(JSONType)
    new_value: Mapped[Any] = mapped_column(JSONType)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_email: Mapped[str | None] = mapped_column(Text)
    actor_role: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingConflict(Base):
    __tablename__ = "booking_conflicts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    conflicting_booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("security_resources.id"))
    conflict_type: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    conflict_start_date: Mapped[date | None] = mapped_column(Date)
    conflict_end_date: Mapped[date | None] = mapped_column(Date)
    source_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booking: Mapped[Booking] = relationship(foreign_keys=[booking_id], lazy="joined")
    conflicting_booking: Mapped[Booking | None] = relationship(foreign_keys=[conflicting_booking_id], lazy="joined")
    resource: Mapped[SecurityResource | None] = relationship(lazy="joined")


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    subject_template: Mapped[str] = mapped_column(Text)
    body_template: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EmailNotificationLog(Base):
    __tablename__ = "email_notification_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_key: Mapped[str] = mapped_column(Text)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    recipient: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ApplicationSetting(Base):
    __tablename__ = "application_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
