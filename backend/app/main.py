import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.core.config import get_settings
from app.core.db import assert_backend_role_cannot_bypass_rls
from app.core.errors import register_exception_handlers

logger = logging.getLogger("edubridge")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # `log_level` was read from settings and never used, so nothing the
    # application logged went anywhere.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Refuse to start rather than run with every Row Level Security policy
    # silently inert. This is the check that turns "connect as app_backend,
    # never as postgres" from a comment into a guarantee.
    assert_backend_role_cannot_bypass_rls()
    logger.info("database role verified: cannot bypass row level security")

    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        lifespan=lifespan,
    )

    # `allow_origins` must be a real list. With `allow_credentials=True` a "*"
    # entry does NOT send a literal `*` — Starlette echoes the requesting origin
    # back instead — so a wildcard lets any site make credentialed calls, and
    # the refresh cookie is a credential. Settings rejects "*" in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # One id per request, echoed on the response and attached to any 500, so
        # a user's bug report can be tied to a specific log line.
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    register_exception_handlers(app)

    app.include_router(auth_router, prefix=settings.api_base_path)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {
            "status": "ok",
            "service": settings.app_name,
            "environment": settings.environment,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    return app


app = create_app()
