from typing import Any


class ServiceError(Exception):
    """Business-rule failure mapped to a structured JSON error response."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(what: str = "Resource") -> ServiceError:
    return ServiceError(404, "not_found", f"{what} not found.")


def forbidden(message: str = "You are not authorised to perform this action.") -> ServiceError:
    return ServiceError(403, "forbidden", message)


def bad_request(message: str, code: str = "validation_error", details: Any = None) -> ServiceError:
    return ServiceError(422, code, message, details)


def conflict(message: str, code: str = "conflict", details: Any = None) -> ServiceError:
    return ServiceError(409, code, message, details)
