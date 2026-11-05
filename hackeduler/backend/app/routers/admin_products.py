"""Products and their implementations (admin only).

Requesters are assigned to a product (and optionally an implementation). Requesters
of the same product can see each other's bookings; bookings are tagged with the
product/implementation for reporting.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..errors import conflict, not_found
from ..models import Booking, Implementation, Product, User
from ..services import audit
from .common import commit

router = APIRouter(prefix="/api/admin", tags=["admin-products"], dependencies=[Depends(require_admin)])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NameIn(_Strict):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class NameUpdate(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


def _counts(db: Session, col, value) -> dict:
    users = db.scalar(select(func.count()).select_from(User).where(col(User) == value, User.deleted_at.is_(None))) or 0
    bookings = db.scalar(select(func.count()).select_from(Booking).where(col(Booking) == value)) or 0
    return {"users": users, "bookings": bookings}


def _impl_out(db: Session, i: Implementation) -> dict:
    return {"id": str(i.id), "product_id": str(i.product_id), "name": i.name, "description": i.description,
            "is_active": i.is_active, **_counts(db, lambda m: m.implementation_id, i.id)}


def _product_out(db: Session, p: Product, include_inactive: bool = True) -> dict:
    q = select(Implementation).where(Implementation.product_id == p.id).order_by(Implementation.name)
    if not include_inactive:
        q = q.where(Implementation.is_active.is_(True))
    return {"id": str(p.id), "name": p.name, "description": p.description, "is_active": p.is_active,
            **_counts(db, lambda m: m.product_id, p.id),
            "implementations": [_impl_out(db, i) for i in db.scalars(q).unique().all()]}


def _name_taken(db: Session, model, name: str, *, scope=None, exclude=None) -> bool:
    q = select(model.id).where(func.lower(model.name) == name.lower())
    if scope is not None:
        q = q.where(scope)
    if exclude is not None:
        q = q.where(model.id != exclude)
    return db.scalar(q) is not None


@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    return [_product_out(db, p) for p in db.scalars(select(Product).order_by(Product.name)).all()]


@router.post("/products", status_code=201)
def create_product(body: NameIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if _name_taken(db, Product, body.name):
        raise conflict("A product with that name already exists.", "duplicate")
    p = Product(id=uuid.uuid4(), name=body.name, description=body.description)
    db.add(p)
    db.flush()
    audit.record(db, "product.created", admin, entity_type="product", entity_id=p.id, new=body.model_dump())
    commit(db)
    return _product_out(db, p)


@router.patch("/products/{product_id}")
def update_product(product_id: uuid.UUID, body: NameUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.get(Product, product_id)
    if p is None:
        raise not_found("Product")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and _name_taken(db, Product, data["name"], exclude=p.id):
        raise conflict("A product with that name already exists.", "duplicate")
    prev = {"name": p.name, "description": p.description, "is_active": p.is_active}
    for k, v in data.items():
        setattr(p, k, v)
    audit.record(db, "product.updated", admin, entity_type="product", entity_id=p.id, previous=prev, new=data)
    commit(db)
    return _product_out(db, p)


@router.delete("/products/{product_id}")
def delete_product(product_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.get(Product, product_id)
    if p is None:
        raise not_found("Product")
    c = _counts(db, lambda m: m.product_id, p.id)
    if c["users"] or c["bookings"]:
        raise conflict(f"{p.name} is used by {c['users']} user(s) and {c['bookings']} booking(s). "
                       "Deactivate it instead, or move the users to another product first.", "product_in_use", c)
    db.query(Implementation).filter(Implementation.product_id == p.id).delete()
    db.delete(p)
    audit.record(db, "product.deleted", admin, entity_type="product", entity_id=product_id, previous={"name": p.name})
    commit(db)
    return {"ok": True}


@router.post("/products/{product_id}/implementations", status_code=201)
def create_implementation(product_id: uuid.UUID, body: NameIn, db: Session = Depends(get_db),
                          admin: User = Depends(require_admin)):
    p = db.get(Product, product_id)
    if p is None:
        raise not_found("Product")
    if _name_taken(db, Implementation, body.name, scope=Implementation.product_id == p.id):
        raise conflict(f"{p.name} already has an implementation with that name.", "duplicate")
    i = Implementation(id=uuid.uuid4(), product_id=p.id, name=body.name, description=body.description)
    db.add(i)
    db.flush()
    audit.record(db, "implementation.created", admin, entity_type="implementation", entity_id=i.id,
                 new={**body.model_dump(), "product": p.name})
    commit(db)
    return _impl_out(db, i)


@router.patch("/implementations/{implementation_id}")
def update_implementation(implementation_id: uuid.UUID, body: NameUpdate, db: Session = Depends(get_db),
                          admin: User = Depends(require_admin)):
    i = db.get(Implementation, implementation_id)
    if i is None:
        raise not_found("Implementation")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and _name_taken(db, Implementation, data["name"], scope=Implementation.product_id == i.product_id,
                                      exclude=i.id):
        raise conflict("That product already has an implementation with that name.", "duplicate")
    prev = {"name": i.name, "description": i.description, "is_active": i.is_active}
    for k, v in data.items():
        setattr(i, k, v)
    audit.record(db, "implementation.updated", admin, entity_type="implementation", entity_id=i.id, previous=prev, new=data)
    commit(db)
    return _impl_out(db, i)


@router.delete("/implementations/{implementation_id}")
def delete_implementation(implementation_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    i = db.get(Implementation, implementation_id)
    if i is None:
        raise not_found("Implementation")
    c = _counts(db, lambda m: m.implementation_id, i.id)
    if c["users"] or c["bookings"]:
        raise conflict(f"{i.name} is used by {c['users']} user(s) and {c['bookings']} booking(s). Deactivate it instead.",
                       "implementation_in_use", c)
    db.delete(i)
    audit.record(db, "implementation.deleted", admin, entity_type="implementation", entity_id=implementation_id,
                 previous={"name": i.name})
    commit(db)
    return {"ok": True}


