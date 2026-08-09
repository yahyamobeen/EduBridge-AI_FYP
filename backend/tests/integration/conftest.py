"""
Test isolation.

THE PROBLEM THIS SOLVES: the integration tests drive the real application
against the real Supabase project, and nothing rolled anything back — so every
run left `@test.com` users, profiles, subscriptions and tokens behind
permanently. This file already had rollback fixtures; the TestClient tests
simply never used them.

Every session the application opens during a test is now bound to ONE connection
inside ONE outer transaction, rolled back afterwards. Savepoints let the
application's own `commit()` calls behave normally without escaping it.

`SessionLocal` is patched in BOTH modules that reference it, because
`app.auth.dependencies` imports the name directly — patching only
`app.core.db.SessionLocal` would leave every authenticated request writing to
the real database.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.db import engine, service_engine
from app.core.ratelimit import reset_for_tests
from app.main import app


@pytest.fixture
def db_connection():
    """One connection, one transaction, rolled back at the end of the test."""
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def isolate_database(db_connection, monkeypatch):
    """
    Point every application session at the test transaction.

    `join_transaction_mode="create_savepoint"` means a `session.commit()` inside
    the application releases a savepoint rather than committing the outer
    transaction — so the code under test behaves exactly as it does in
    production while nothing it writes survives the test.
    """
    TestSessionLocal = sessionmaker(  # noqa: N806 -- a session factory, so PascalCase
        bind=db_connection,
        autoflush=False,
        expire_on_commit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )

    import app.auth.dependencies as dependencies_module
    import app.core.db as db_module

    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(dependencies_module, "SessionLocal", TestSessionLocal)

    # The limiter counts per client host, and TestClient is always the same
    # host — so without this the fifth registration in the suite would get a
    # 429 and every later test would fail for a reason unrelated to what it
    # asserts.
    reset_for_tests()

    return TestSessionLocal


@pytest.fixture(autouse=True)
def never_send_real_email(monkeypatch):
    """
    THE SUITE MUST NOT TALK TO A MAIL PROVIDER.

    This is not hypothetical. A developer `.env` with `EMAIL_PROVIDER=resend`
    and a live key made a full test run fire real API calls — Resend rejected
    them only because the fixtures use `@example.com`, which is luck, not a
    control. A run that happened to use a deliverable address would have mailed
    a stranger a password-reset link and spent production quota doing it.

    Patched at the sender rather than through the environment, because
    `get_settings` is `lru_cache`d and already built by the time any fixture
    runs — setting the variable here would be too late and would look like it
    worked.

    Also drains the dispatch queue after each test: `send_async` returns before
    delivery, so without this a message could surface during an unrelated test
    and be attributed to it.
    """
    import app.auth.email as email_module

    monkeypatch.setattr(email_module, "get_email_sender", email_module.LoggingEmailSender)
    yield
    email_module.drain_pending_emails()


@pytest.fixture(autouse=True)
def never_call_turnstile(monkeypatch):
    """
    THE SUITE MUST NOT TALK TO CHALLENGES.CLOUDFLARE.COM.

    Same rule as `never_send_real_email`: a developer .env with a real
    TURNSTILE_SECRET_KEY and a token in a test body would fire a live HTTP
    call from CI. Patch the verify seam so every verification PASSES; the
    captcha-failure paths are tested by explicitly re-patching it to a
    rejecting stub (see test_turnstile.py).

    NOTE on the patch target: `service.py` does `from app.auth.turnstile
    import verify_turnstile_token`, so the name the request path calls lives
    in `app.auth.service` — patching the turnstile module alone would leave
    the real function reachable from every register/login test.
    """
    import app.auth.service as service_module

    monkeypatch.setattr(service_module, "verify_turnstile_token", lambda _token: True)
    yield


@pytest.fixture
def valid_turnstile_token() -> str:
    """The token value supplied by tests; the autouse fixture accepts anything."""
    return "test-turnstile-token"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db(isolate_database):
    """A session on the test transaction, for arranging fixtures directly."""
    session = isolate_database()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def service_conn():
    """
    RLS-BYPASSING connection, for the few assertions that need to see rows the
    application role deliberately cannot — proving a policy hides them, for
    instance. Rolled back like everything else.
    """
    connection = service_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def unique_email():
    def _make(prefix: str = "test") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"

    return _make


@pytest.fixture
def make_link(db):
    """
    Build a `guardian_link` in a given state.

    A FIXTURE RATHER THAN A RAW INSERT, because migration 20260803090000 closed
    the hole that let either participant INSERT a link that was already
    `verified`: `guardian_link_create` now requires `status = 'pending'` and
    `guardian_link_update` refuses to produce `verified` at all. A link reaches
    `verified` through exactly one path — `app.confirm_guardian_link` with a
    valid one-time invite token — so a test that wants one has to take that
    path. Which is an improvement: the fixture exercises the real transition
    instead of asserting against a state the application could never produce.

    Leaves the session bound to the PARENT; rebind before reading as anyone else.
    """
    from app.auth.security import hash_token
    from app.auth.tokens import issue_guardian_invite_token
    from app.core.db import set_current_user_id

    def _as_uuid(value):
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))

    def _make(*, parent_id, student_id, status: str = "pending") -> None:
        parent, student = _as_uuid(parent_id), _as_uuid(student_id)

        set_current_user_id(db, parent)
        db.execute(
            text(
                "INSERT INTO guardian_link (parent_id, student_id, status) "
                "VALUES (:p, :s, 'pending')"
            ),
            {"p": parent, "s": student},
        )
        db.flush()
        if status == "pending":
            return

        if status == "verified":
            token = issue_guardian_invite_token(db, student)
            db.flush()
            row = db.execute(
                text("SELECT status FROM app.confirm_guardian_link(:p, :h)"),
                {"p": parent, "h": hash_token(token)},
            ).one_or_none()
            assert row is not None, "confirm_guardian_link refused a freshly issued token"
        elif status == "revoked":
            # Withdrawing consent is the one transition a parent may still write
            # directly — the asymmetry the gate needs.
            set_current_user_id(db, parent)
            affected = db.execute(
                text(
                    "UPDATE guardian_link SET status = 'revoked' "
                    "WHERE student_id = :s AND parent_id = :p"
                ),
                {"s": student, "p": parent},
            ).rowcount
            assert affected == 1, "a parent must be able to revoke their own link"
        else:  # pragma: no cover -- programmer error in a test
            raise ValueError(f"unsupported guardian_link status: {status}")
        db.flush()

    return _make
