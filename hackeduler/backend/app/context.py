"""Per-request context (correlation ID, client IP) available to services such as auditing."""
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)
# (admin id, admin email) while an admin is using "Act as"; stamped on every audit entry of the request
acting_admin_var: ContextVar[tuple[str, str] | None] = ContextVar("acting_admin", default=None)
