"""FastAPI application entry point."""
from __future__ import annotations

import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError

from .config import get_settings
from .context import client_ip_var, request_id_var
from .errors import ServiceError
from .routers import admin_bookings, admin_config, admin_reports, auth, requester, sso
from .security import limiter
from .services import audit

log = logging.getLogger("orp")
settings = get_settings()

app = FastAPI(
    title="OffSec Resource Planner API",
    version="1.0.0",
    description="Capacity, availability and booking management for the Offensive Security team. "
                "All /api/admin/* endpoints require the Admin role.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

if settings.cors_origins and not settings.is_production:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"])

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-_.]{1,64}$")


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-ID")
    rid = rid if rid and REQUEST_ID_RE.match(rid) else str(uuid.uuid4())
    ip = request.client.host if request.client else "unknown"
    request_id_var.set(rid)
    client_ip_var.set(ip)
    if request.url.path.startswith("/api/") and not limiter.allow(f"ip:{ip}", settings.rate_limit_per_minute):
        resp = JSONResponse({"error": {"code": "rate_limited", "message": "Too many requests. Please slow down."}}, 429)
    else:
        resp = await call_next(request)
    resp.headers["X-Request-ID"] = rid
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Cache-Control"] = "no-store"
    if not request.url.path.startswith("/api/docs") and not request.url.path.startswith("/api/redoc"):
        resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.is_production:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    body["error"]["request_id"] = request_id_var.get()
    return JSONResponse(body, status_code=status)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    user = getattr(request.state, "user", None)
    # audit failed administrative operations (authorisation denials are audited in deps.require_admin)
    if (user is not None and user.is_admin and request.url.path.startswith("/api/admin")
            and request.method in ("POST", "PUT", "PATCH", "DELETE") and exc.status_code != 403):
        audit.record_detached("admin.operation_failed", user, entity_type="endpoint",
                              entity_id=f"{request.method} {request.url.path}",
                              new={"status": exc.status_code, "code": exc.code, "message": exc.message})
    return _error(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()]
    forbidden_fields = [e["field"] for e in errs if e["type"] == "extra_forbidden"]
    user = getattr(request.state, "user", None)
    if forbidden_fields and any(f.split(".")[0] in ("force", "end_date", "duration_days", "status") for f in forbidden_fields):
        audit.record_detached("authorization.denied", user, entity_type="endpoint",
                              entity_id=f"{request.method} {request.url.path}",
                              reason=f"Attempt to supply backend-controlled/admin-only fields: {', '.join(forbidden_fields)}")
    return _error(422, "validation_error", "Request validation failed.", errs)


@app.exception_handler(OperationalError)
async def db_operational_handler(request: Request, exc: OperationalError):
    msg = str(exc.orig) if exc.orig else str(exc)
    if "deadlock" in msg or "could not serialize" in msg or "lock" in msg:
        return _error(409, "concurrent_update", "Another change was being made at the same time. Please retry.")
    log.exception("database error")
    return _error(503, "database_unavailable", "Database temporarily unavailable.")


@app.exception_handler(DBAPIError)
async def dbapi_handler(request: Request, exc: DBAPIError):
    log.exception("database error")
    return _error(500, "internal_error", "An unexpected error occurred.")


@app.get("/api/health", tags=["meta"])
def health():
    from sqlalchemy import text

    from .db import engine

    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(sso.public)
app.include_router(sso.admin)
app.include_router(requester.router)
app.include_router(admin_config.router)
app.include_router(admin_bookings.router)
app.include_router(admin_reports.router)
