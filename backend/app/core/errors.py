from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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
    return JSONResponse(
        status_code=500,
        content=error_envelope(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_response)
    app.add_exception_handler(RequestValidationError, _validation_error_response)
    app.add_exception_handler(Exception, _unhandled_error_response)
