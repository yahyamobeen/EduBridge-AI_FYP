import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("edubridge.errors")


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def validation_error(*, message: str, details: dict[str, Any] | None = None) -> AppError:
    return AppError(code="VALIDATION_ERROR", message=message, status_code=400, details=details)


def unauthenticated(message: str = "Authentication required") -> AppError:
    return AppError(code="UNAUTHENTICATED", message=message, status_code=401)


def two_factor_locked(locked_until: str) -> AppError:
    return AppError(
        code="TWO_FACTOR_LOCKED",
        message="Too many attempts. Try again later.",
        status_code=423,
        details={"locked_until": locked_until},
    )


def email_already_registered() -> AppError:
    return AppError(
        code="EMAIL_ALREADY_REGISTERED",
        message="An account with this email already exists.",
        status_code=409,
    )


def invalid_class_group(message: str = "Invalid board, class level, or student group.") -> AppError:
    return AppError(code="INVALID_CLASS_GROUP", message=message, status_code=422)


def rate_limited(message: str = "Too many requests. Please slow down.") -> AppError:
    return AppError(code="RATE_LIMITED", message=message, status_code=429)


def captcha_failed(message: str = "Please complete the security check again.") -> AppError:
    # 400, not 403: the request body carried a token that failed verification,
    # exactly like VALIDATION_ERROR is a 400 for a body that failed validation.
    # The code — not the status — is what the client branches on, and this code
    # is new, so a client that does not know it renders the generic state
    # safely (ERROR_CODES additions in the frontend phase).
    return AppError(code="CAPTCHA_FAILED", message=message, status_code=400)


def forbidden_scope(message: str = "This account cannot do that.") -> AppError:
    return AppError(code="FORBIDDEN_SCOPE", message=message, status_code=403)


def gate_pending(message: str = "Parental consent is pending.") -> AppError:
    return AppError(code="GATE_PENDING", message=message, status_code=403)


def self_link_forbidden(message: str = "A parent cannot be linked to themselves.") -> AppError:
    return AppError(code="SELF_LINK_FORBIDDEN", message=message, status_code=422)


def guardian_already_linked(message: str = "A guardian is already linked.") -> AppError:
    return AppError(code="GUARDIAN_ALREADY_LINKED", message=message, status_code=409)


def invalid_token(message: str = "This link is invalid or has expired.") -> AppError:
    return AppError(code="INVALID_TOKEN", message=message, status_code=400)


def guardian_not_found(message: str = "No parent account uses that email.") -> AppError:
    return AppError(code="GUARDIAN_NOT_FOUND", message=message, status_code=422)


def two_factor_invalid() -> AppError:
    return AppError(code="TWO_FACTOR_INVALID", message="Invalid or expired code.", status_code=401)


def pending_token_expired() -> AppError:
    return AppError(
        code="PENDING_TOKEN_EXPIRED",
        message="Challenge expired. Please sign in again.",
        status_code=401,
    )


def token_expired(message: str = "This link has expired.") -> AppError:
    return AppError(code="TOKEN_EXPIRED", message=message, status_code=410)


def error_envelope(
    *, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _app_error_response(request: Request, error: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error_envelope(code=error.code, message=error.message, details=error.details),
    )


def _validation_error_response(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors: dict[str, Any] = {}
    skip = ("body", "query", "path", "header")
    for item in exc.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()) if part not in skip)
        errors[loc or "body"] = item.get("msg", "Invalid value")
    return JSONResponse(
        status_code=400,
        content=error_envelope(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            details={"fields": errors},
        ),
    )


def _unhandled_error_response(request: Request, exc: Exception) -> JSONResponse:
    """
    The catch-all.

    THE EXCEPTION IS LOGGED, WHICH IT PREVIOUSLY WAS NOT. This handler used to
    return the envelope and drop the exception entirely, with no logger
    configured anywhere â€” so every crash in production was invisible and the
    first symptom would have been a user reporting it.

    The response body still says nothing: a stack or a database message can
    carry an email address, a token fragment or an internal path, and this is
    reachable by anyone. The request id is the bridge â€” meaningless to a
    caller, and enough to find the log line.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "unhandled error on %s %s (request_id=%s)",
        request.method,
        request.url.path,
        request_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content=error_envelope(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            details={"request_id": request_id} if request_id else None,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_response)
    app.add_exception_handler(RequestValidationError, _validation_error_response)
    app.add_exception_handler(Exception, _unhandled_error_response)
