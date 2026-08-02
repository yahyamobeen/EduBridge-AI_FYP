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
