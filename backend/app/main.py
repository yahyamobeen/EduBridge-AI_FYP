import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.auth.email import drain_pending_emails
from app.auth.routes import router as auth_router
from app.core.config import get_settings
from app.core.db import DatabaseUnreachableError, assert_backend_role_cannot_bypass_rls
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
    #
    # A connectivity failure here used to surface as ~150 lines of SQLAlchemy
    # pool internals ending in `getaddrinfo failed`, which reads like a code
    # fault and is not one. The message is logged plainly and the traceback
    # dropped: nothing in those frames helps, and the actual cause is one line.
    try:
        assert_backend_role_cannot_bypass_rls()
    except DatabaseUnreachableError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from None
    logger.info("database role verified: cannot bypass row level security")

    yield

    # ⚠️ FINDING D8 — THE SHUTDOWN THAT DID NOT EXIST.
    #
    # `lifespan` ended at the bare `yield` above, so nothing ever drained the
    # email dispatch queue. `send_async` returns before delivery, and
    # `drain_pending_emails` was called from exactly one place in the whole
    # repository: `tests/integration/conftest.py`. In production the only thing
    # standing between a shutdown and a silently dropped verification email was
    # the `atexit` hook in `email.py` — which does not run when a container is
    # stopped with SIGTERM, which is how Render stops one.
    #
    # `_pending` also grew without bound: every Future was appended and nothing
    # removed them, so a long-lived process accumulated one object per email
    # sent since boot. Draining here is what makes that list finite in
    # production rather than only under test.
    #
    # Bounded rather than unbounded: a mail provider that has stopped answering
    # must not hold the shutdown open past the platform's kill timeout, because
    # then the process is killed anyway and the drain achieved nothing.
    try:
        drain_pending_emails(timeout=5.0)
    except Exception:  # noqa: BLE001 -- shutdown must complete regardless
        logger.exception("email queue did not drain cleanly during shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        # Finding A5. `docs_url` and `redoc_url` gate only the two HTML VIEWERS.
        # Both are just pages that fetch this URL, which kept its default — so
        # production served the complete schema, unauthenticated, while /docs
        # returned 404 and looked closed. That schema lists every route, every
        # field name and bound, and every enum, including which roles register
        # accepts. It is a map, and it was public.
        openapi_url=None if settings.is_production else "/openapi.json",
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
