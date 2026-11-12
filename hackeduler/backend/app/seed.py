"""Idempotent seed data for local development / demos.

    python -m app.seed            # reference data + dev accounts + sample data
    python -m app.seed --minimal  # reference data only (activity types, templates, settings)

Dev accounts (CHANGE OR DISABLE IN PRODUCTION):
    admin@offsec.local      / Admin@12345678
    requester@offsec.local  / Requester@12345
    requester2@offsec.local / Requester@12345
"""
from __future__ import annotations

import argparse
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import (
    ROLE_ADMIN_ID,
    ROLE_REQUESTER_ID,
    ActivityType,
    Booking,
    EmailTemplate,
    Holiday,
    ResourceLeave,
    SecurityResource,
    User,
)
from .security import hash_password
from .services import booking_service, notifications, settings_service

ACTIVITY_TYPES = [
    ("Web Application PT", 8, 0),
    ("Web Application PT with LLM", 12, 0),
    ("Hybrid Application PT – Single Codebase", 12, 0),
    ("Hybrid Application PT – Single Codebase", 16, 0),
    ("Hybrid Application PT – Multiple Codebases", 16, 0),
    ("Hybrid Application PT – Multiple Codebases", 20, 0),
    ("Mobile Application PT – Single Platform", 8, 0),
    ("Mobile Application PT – Android and iOS", 12, 0),
    ("API PT – Below 30 Endpoints", 8, 0),
    ("API PT – 30 - 70 Endpoints", 12, 0),
    ("API PT – 70 or More Endpoints", 16, 0),
    ("Thick Client PT", 8, 0),
    ("Network PT", 8, 0),
    ("Network + Segmentation PT", 12, 0),
    ("Segmentation PT", 5, 0),
    ("Standalone LLM PT", 4, 4),  # example of an additional-duration rule: up to +4 working days
]

# Activities that need no security engineer (no resource reserved, duration optional)
RESOURCELESS_ACTIVITIES = [
    ("XBOW Automated Scan", None, "Automated scan - no security resource is allocated"),
]

SAMPLE_PRODUCTS = {
    "Payments Platform": ["Retail Bank Rollout", "Card Issuing"],
    "Customer Engagement": ["Mobile App", "Web Portal"],
}

HYBRID_SCOPE = {
    ("Hybrid Application PT – Single Codebase", 12): "Standard scope",
    ("Hybrid Application PT – Single Codebase", 16): "Extended scope",
    ("Hybrid Application PT – Multiple Codebases", 16): "Standard scope",
    ("Hybrid Application PT – Multiple Codebases", 20): "Extended scope",
}

DEV_USERS = [
    ("admin@offsec.local", "OffSec Admin", "Admin@12345678", ROLE_ADMIN_ID),
    ("requester@offsec.local", "Priya Requester", "Requester@12345", ROLE_REQUESTER_ID),
    ("requester2@offsec.local", "Arjun Requester", "Requester@12345", ROLE_REQUESTER_ID),
]

ENGINEERS = [
    ("Ananya Iyer", "ananya.iyer@offsec.local"),
    ("Rahul Menon", "rahul.menon@offsec.local"),
    ("Sneha Pillai", "sneha.pillai@offsec.local"),
    ("Vikram Nair", "vikram.nair@offsec.local"),
    ("Meera Krishnan", "meera.krishnan@offsec.local"),
    ("Karthik Rao", "karthik.rao@offsec.local"),
]


def is_default_activity(name: str, days: int | None) -> bool:
    """True for the built-in activity types that seed_reference() (re)creates at start-up when missing."""
    return any(n == name and d == days for n, d, _ in ACTIVITY_TYPES) or any(n == name for n, _, _ in RESOURCELESS_ACTIVITIES)


def seed_reference(db: Session) -> None:
    for i, (name, days, extra) in enumerate(ACTIVITY_TYPES):
        exists = db.scalar(select(ActivityType.id).where(ActivityType.name == name, ActivityType.base_duration_days == days))
        if not exists:
            desc = HYBRID_SCOPE.get((name, days))
            db.add(ActivityType(id=uuid.uuid4(), name=name, base_duration_days=days, allow_additional_days=extra > 0,
                                max_additional_days=extra, sort_order=i, description=desc))
    for i, (name, days, desc) in enumerate(RESOURCELESS_ACTIVITIES, start=len(ACTIVITY_TYPES)):
        if not db.scalar(select(ActivityType.id).where(ActivityType.name == name)):
            db.add(ActivityType(id=uuid.uuid4(), name=name, base_duration_days=days, requires_resource=False,
                                allow_additional_days=False, max_additional_days=0, sort_order=i, description=desc))
    for key, t in notifications.DEFAULT_TEMPLATES.items():
        if not db.scalar(select(EmailTemplate.id).where(EmailTemplate.key == key)):
            db.add(EmailTemplate(id=uuid.uuid4(), key=key, name=t["name"], subject_template=t["subject"], body_template=t["body"]))
    for key in settings_service.DEFAULTS:
        settings_service.get_setting(db, key)  # defaults are implicit; nothing to insert
    db.commit()


def seed_users(db: Session) -> dict[str, User]:
    out = {}
    for email, name, pw, role in DEV_USERS:
        u = db.scalars(select(User).where(func.lower(User.email) == email)).first()
        if not u:
            u = User(id=uuid.uuid4(), email=email, full_name=name, password_hash=hash_password(pw), role_id=role)
            db.add(u)
        out[email] = u
    db.commit()
    return out


def seed_products(db: Session, users: dict[str, User]) -> None:
    from .models import Implementation, Product

    first = {}
    for pname, impls in SAMPLE_PRODUCTS.items():
        p = db.scalars(select(Product).where(func.lower(Product.name) == pname.lower())).first()
        if not p:
            p = Product(id=uuid.uuid4(), name=pname, description="Sample product")
            db.add(p)
            db.flush()
        for iname in impls:
            i = db.scalars(select(Implementation).where(Implementation.product_id == p.id, Implementation.name == iname)).first()
            if not i:
                i = Implementation(id=uuid.uuid4(), product_id=p.id, name=iname)
                db.add(i)
                db.flush()
            first.setdefault(pname, (p.id, i.id))
    # both demo requesters work on the same product so product sharing can be tried out
    for email in ("requester@offsec.local", "requester2@offsec.local"):
        u = users.get(email)
        if u and not u.product_id:
            u.product_id, u.implementation_id = first["Payments Platform"]
    db.commit()


def seed_resources(db: Session) -> list[SecurityResource]:
    existing = list(db.scalars(select(SecurityResource).order_by(SecurityResource.sequence_no)))
    if existing:
        return existing
    out = []
    for i, (name, email) in enumerate(ENGINEERS, start=1):
        r = SecurityResource(id=uuid.uuid4(), sequence_no=i, code=f"RES-{i:02d}", display_name=f"Resource {i:02d}",
                             engineer_name=name, engineer_email=email)
        db.add(r)
        out.append(r)
    db.commit()
    return out


def seed_holidays(db: Session, year: int) -> None:
    sample = [
        (date(year, 1, 26), "Republic Day"), (date(year, 3, 14), "Holi"), (date(year, 5, 1), "May Day"),
        (date(year, 8, 15), "Independence Day"), (date(year, 10, 2), "Gandhi Jayanti"),
        (date(year, 11, 1), "Kerala Piravi"), (date(year, 12, 25), "Christmas"),
    ]
    for d, n in sample:
        if not db.scalar(select(Holiday.id).where(Holiday.holiday_date == d)):
            db.add(Holiday(id=uuid.uuid4(), name=n, holiday_date=d, description="Sample organisation holiday"))
    db.commit()


def seed_sample_bookings(db: Session, users: dict[str, User], resources: list[SecurityResource]) -> None:
    if db.scalar(select(func.count()).select_from(Booking)):
        return
    today = settings_service.org_today(db)
    admin = users["admin@offsec.local"]
    req = users["requester@offsec.local"]
    req2 = users["requester2@offsec.local"]
    acts = {a.name + str(a.base_duration_days): a for a in db.scalars(select(ActivityType))}

    def next_monday(d: date, weeks: int = 0) -> date:
        return d + timedelta(days=(7 - d.weekday()) % 7 or 7) + timedelta(weeks=weeks)

    # leave for Resource 03 next fortnight
    lv_start = next_monday(today, 1)
    db.add(ResourceLeave(id=uuid.uuid4(), resource_id=resources[2].id, start_date=lv_start, end_date=lv_start + timedelta(days=4),
                         leave_type="Annual leave", reason="Planned vacation", created_by=admin.id))
    db.commit()

    def mk(user, res, act_key, start, app, ver, pci=False):
        inp = booking_service.BookingInput(application_name=app, application_version=ver, activity_type_id=acts[act_key].id,
                                           pci_dss_scope=pci, resource_id=res.id, start_date=start,
                                           poc_name=user.full_name, poc_email=user.email)
        b = booking_service.submit_booking(db, user, inp)
        db.commit()
        return b

    b1 = mk(req, resources[0], "Web Application PT8", next_monday(today), "Customer Portal", "4.2.0", True)
    booking_service.approve(db, admin, b1.id)
    db.commit()
    mk(req, resources[1], "API PT – Below 30 Endpoints8", next_monday(today), "Payments API", "2.1")
    b3 = mk(req2, resources[3], "Mobile Application PT – Android and iOS12", next_monday(today, 1), "Mobile Banking", "7.0", True)
    booking_service.approve(db, admin, b3.id)
    db.commit()
    mk(req2, resources[4], "Network PT8", next_monday(today, 3), "Branch Network", "2026-Q4")
    b5 = mk(req, resources[5], "Thick Client PT8", next_monday(today, 2), "Treasury Desktop", "11.3")
    booking_service.reject(db, admin, b5.id, "Scope document not yet signed off; please resubmit once approved.")
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimal", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        seed_reference(db)
        if not args.minimal:
            users = seed_users(db)
            seed_products(db, users)
            resources = seed_resources(db)
            year = settings_service.org_today(db).year
            seed_holidays(db, year)
            seed_holidays(db, year + 1)
            seed_sample_bookings(db, users, resources)
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
