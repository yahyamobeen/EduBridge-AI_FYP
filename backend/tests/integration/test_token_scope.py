"""
The token boundary.

Definition of Done: "The pending/enrollment token CANNOT call any business
endpoint." Nothing asserted it, so this file does.

Two separate properties, and the second is the one the original design could not
enforce at all:

  1. A challenge token is opaque; only a signed JWT opens a session. Presenting
     one as a bearer must fail.
  2. An ENROLMENT token and a PENDING token are different kinds. `/2fa/verify`
     exchanges a pending token for a full session, so it must be able to reject
     the longer-lived enrolment token — which was impossible while both were
     stored as `two_factor_pending`.
"""

import pytest
from sqlalchemy import text

from app.auth.tokens import find_token, issue_challenge_token, issue_refresh_token
from app.core.db import set_current_user_id
from app.models.enums import TokenKind


def _make_user(session, email: str) -> str:
    return str(
        session.execute(
            text(
                "INSERT INTO app_user (email, password_hash, role, full_name, email_verified_at) "
                "VALUES (:email, 'x', 'student', 'Scope Test', now()) RETURNING id"
            ),
            {"email": email},
        ).scalar_one()
    )


class TestChallengeTokensAreNotSessions:
    def test_a_pending_token_cannot_call_a_business_endpoint(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("pending"))
        db.flush()
        set_current_user_id(db, user_id)
        token = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        db.flush()

        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_an_enrollment_token_cannot_either(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("enroll"))
        db.flush()
        set_current_user_id(db, user_id)
        token = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_enrollment, ttl_seconds=900
        )
        db.flush()

        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_a_refresh_token_is_not_an_access_token(self, client, db, unique_email):
        """The refresh token is opaque too; only the cookie path accepts it."""
        user_id = _make_user(db, unique_email("refresh"))
        db.flush()
        set_current_user_id(db, user_id)
        plain, _ = issue_refresh_token(db, user_id)
        db.flush()

        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {plain}"})
        assert response.status_code == 401


class TestKindsAreDistinguishable:
    """
    The property that made this fixable. Both challenge tokens used to be stored
    as `two_factor_pending`, so /2fa/verify — the endpoint that hands out a full
    session — had no way to tell them apart and would have accepted the
    longer-lived enrolment token.
    """

    def test_enrollment_and_pending_are_stored_under_different_kinds(self, db, unique_email):
        user_id = _make_user(db, unique_email("kinds"))
        db.flush()
        set_current_user_id(db, user_id)

        pending = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        enrollment = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_enrollment, ttl_seconds=900
        )
        db.flush()

        assert find_token(db, pending).kind == TokenKind.two_factor_pending.value
        assert find_token(db, enrollment).kind == TokenKind.two_factor_enrollment.value

    def test_a_challenge_kind_is_required_and_checked(self, db, unique_email):
        """A caller cannot issue a challenge token as some other kind."""
        user_id = _make_user(db, unique_email("badkind"))
        db.flush()
        set_current_user_id(db, user_id)

        with pytest.raises(ValueError):
            issue_challenge_token(db, user_id, kind=TokenKind.refresh, ttl_seconds=300)
