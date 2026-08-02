from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import tokens
from app.auth.security import hash_token
from app.models.enums import TokenKind


def _create_user(conn, email: str) -> str:
    row = conn.execute(
        text(
            "INSERT INTO app_user (email, password_hash, role, full_name) "
            "VALUES (:email, 'x', 'student', 'Test') RETURNING id"
        ),
        {"email": email},
    )
    return str(row.scalar())


def _session(conn) -> Session:
    return Session(bind=conn)


def test_issue_refresh_token(service_conn):
    uid = _create_user(service_conn, f"tok-{uuid4().hex}@test.com")
    session = _session(service_conn)
    plain, row = tokens.issue_refresh_token(session, uid)
    session.flush()
    assert row.kind == TokenKind.refresh.value
    assert str(row.user_id) == uid
    assert not row.revoked
    assert row.expires_at > datetime.now(UTC)
    assert len(plain) >= 40


def test_rotate_revokes_old_and_replay_fails(service_conn):
    uid = _create_user(service_conn, f"tok-{uuid4().hex}@test.com")
    session = _session(service_conn)
    plain_old, _ = tokens.issue_refresh_token(session, uid)
    session.commit()

    rotated = tokens.rotate_refresh_token(session, plain_old)
    assert rotated is not None
    plain_new, new_row = rotated
    assert plain_new != plain_old
    assert str(new_row.user_id) == uid
    session.commit()

    replay = tokens.rotate_refresh_token(session, plain_old)
    assert replay is None


def test_rotate_unknown_token_returns_none(service_conn):
    session = _session(service_conn)
    assert tokens.rotate_refresh_token(session, "does-not-exist") is None


def test_revoke_user_tokens(service_conn):
    uid = _create_user(service_conn, f"tok-{uuid4().hex}@test.com")
    session = _session(service_conn)
    tokens.issue_refresh_token(session, uid)
    tokens.issue_refresh_token(session, uid)
    session.commit()

    count = tokens.revoke_user_tokens(session, uid, kind=TokenKind.refresh.value)
    session.commit()
    assert count >= 1


def test_issue_pending_token(service_conn):
    uid = _create_user(service_conn, f"tok-{uuid4().hex}@test.com")
    session = _session(service_conn)
    plain, row = tokens.issue_pending_token(session, uid, ttl_seconds=300)
    session.flush()
    assert row.kind == TokenKind.two_factor_pending.value
    assert row.expires_at - datetime.now(UTC) <= timedelta(seconds=300)
    assert hash_token(plain)
