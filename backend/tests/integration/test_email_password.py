"""
Integration tests for email verification and password reset.

Tests:
- POST /auth/email/verify (idempotent success)
- POST /auth/email/resend (constant-time)
- POST /auth/password/forgot (constant-time)
- POST /auth/password/reset
- Onboarding token cannot call /auth/me
"""

from uuid import uuid4

from sqlalchemy import text

from app.auth.tokens import issue_preauth_token
from app.core.db import set_current_user_id
from app.models.enums import TokenKind


def _make_user(session, email: str, *, verified: bool = False) -> str:
    """Create a test user."""
    user_id = uuid4()
    set_current_user_id(session, user_id)
    # Fixed statements, not string concatenation -- see the note in
    # test_2fa_enrollment.py.
    pw = "$argon2id$v=19$m=8192,t=1,p=1$test$hash"  # noqa: S105 -- a hash, not a password
    if verified:
        session.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, role, full_name, "
                "email_verified_at) VALUES (:id, :email, :pw, 'student', 'Test User', now())"
            ),
            {"id": user_id, "email": email, "pw": pw},
        )
    else:
        session.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, role, full_name) "
                "VALUES (:id, :email, :pw, 'student', 'Test User')"
            ),
            {"id": user_id, "email": email, "pw": pw},
        )
    session.flush()
    set_current_user_id(session, user_id)
    return str(user_id)


class TestEmailVerify:
    def test_email_verify_succeeds(self, client, db, unique_email):
        """POST /email/verify with valid token → 200."""
        user_id = _make_user(db, unique_email("verify-ok"))
        token = issue_preauth_token(db, user_id, kind=TokenKind.email_verify, ttl_seconds=3600)

        resp = client.post(
            "/api/auth/email/verify",
            json={"token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email_verified"] is True
        assert "access_token" in body
        assert "enrollment_token" in body
        assert "onboarding_state" in body

    def test_email_verify_idempotent(self, client, db, unique_email):
        """Second call with spent token → 200 (already verified)."""
        user_id = _make_user(db, unique_email("verify-idempotent"))
        token = issue_preauth_token(db, user_id, kind=TokenKind.email_verify, ttl_seconds=3600)

        # First verify
        resp1 = client.post(
            "/api/auth/email/verify",
            json={"token": token},
        )
        assert resp1.status_code == 200

        # Second verify with same token
        resp2 = client.post(
            "/api/auth/email/verify",
            json={"token": token},
        )
        assert resp2.status_code == 200
        assert resp2.json()["email_verified"] is True

    def test_email_verify_expired_token(self, client, db, unique_email):
        """Expired token → 410 TOKEN_EXPIRED."""
        user_id = _make_user(db, unique_email("verify-expired"))
        # Use -3600 (1 hour ago) to ensure token is definitively expired
        # and visible across transaction boundaries
        token = issue_preauth_token(db, user_id, kind=TokenKind.email_verify, ttl_seconds=-3600)
        db.flush()  # Ensure token is visible to HTTP request's session

        resp = client.post(
            "/api/auth/email/verify",
            json={"token": token},
        )
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "TOKEN_EXPIRED"

    def test_email_verify_invalid_token(self, client, db, unique_email):
        """Unknown token → 400 INVALID_TOKEN."""
        _make_user(db, unique_email("verify-invalid"))

        resp = client.post(
            "/api/auth/email/verify",
            json={"token": "not-a-real-token"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"


class TestOnboardingTokenScoping:
    def test_onboarding_token_cannot_call_me(self, client, db, unique_email):
        """Onboarding token (type='onboarding') rejected by /auth/me."""
        user_id = _make_user(db, unique_email("onboarding-me"))
        token = issue_preauth_token(db, user_id, kind=TokenKind.email_verify, ttl_seconds=3600)

        resp = client.post(
            "/api/auth/email/verify",
            json={"token": token},
        )
        assert resp.status_code == 200
        access_token = resp.json()["access_token"]

        # Try to call /auth/me with onboarding token
        resp2 = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp2.status_code == 401
        assert resp2.json()["error"]["code"] == "UNAUTHENTICATED"


class TestEmailResend:
    def test_email_resend_constant_time(self, client, db, unique_email):
        """POST /email/resend returns same response for known/unknown emails."""
        known_email = unique_email("resend-known")
        _make_user(db, known_email)

        # Known email
        resp1 = client.post(
            "/api/auth/email/resend",
            json={"email": known_email},
        )
        assert resp1.status_code == 204

        # Unknown email
        resp2 = client.post(
            "/api/auth/email/resend",
            json={"email": unique_email("resend-unknown")},
        )
        assert resp2.status_code == 204


class TestPasswordForgot:
    def test_password_forgot_constant_time(self, client, db, unique_email):
        """POST /password/forgot returns same response for known/unknown emails."""
        known_email = unique_email("forgot-known")
        _make_user(db, known_email, verified=True)

        # Known email
        resp1 = client.post(
            "/api/auth/password/forgot",
            json={"email": known_email},
        )
        assert resp1.status_code == 204

        # Unknown email
        resp2 = client.post(
            "/api/auth/password/forgot",
            json={"email": unique_email("forgot-unknown")},
        )
        assert resp2.status_code == 204


class TestPasswordReset:
    def test_password_reset_succeeds(self, client, db, unique_email):
        """POST /password/reset with valid token → 204, new password works."""
        email = unique_email("reset-ok")
        user_id = _make_user(db, email, verified=True)
        token = issue_preauth_token(db, user_id, kind=TokenKind.password_reset, ttl_seconds=3600)

        resp = client.post(
            "/api/auth/password/reset",
            json={"token": token, "new_password": "newpassword123"},
        )
        assert resp.status_code == 204

        # Try to login with new password
        resp2 = client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": "newpassword123",
                "turnstile_token": "test-turnstile-token",
            },
        )
        assert resp2.status_code == 200

    def test_password_reset_revokes_refresh_tokens(self, client, db, unique_email):
        """Password reset revokes all refresh tokens."""
        email = unique_email("reset-revoke")
        user_id = _make_user(db, email, verified=True)

        # Issue a refresh token
        from app.auth.tokens import issue_refresh_token

        set_current_user_id(db, user_id)
        refresh_plain, _ = issue_refresh_token(db, user_id)

        # Reset password
        reset_token = issue_preauth_token(
            db, user_id, kind=TokenKind.password_reset, ttl_seconds=3600
        )
        resp = client.post(
            "/api/auth/password/reset",
            json={"token": reset_token, "new_password": "newpassword123"},
        )
        assert resp.status_code == 204

        # Try to use old refresh token
        resp2 = client.post(
            "/api/auth/refresh",
            cookies={"refresh_token": refresh_plain},
        )
        assert resp2.status_code == 401

    def test_password_reset_expired_token(self, client, db, unique_email):
        """Expired reset token → 410 TOKEN_EXPIRED."""
        user_id = _make_user(db, unique_email("reset-expired"), verified=True)
        # Use -3600 (1 hour ago) to ensure token is definitively expired
        # and visible across transaction boundaries
        token = issue_preauth_token(db, user_id, kind=TokenKind.password_reset, ttl_seconds=-3600)
        db.flush()  # Ensure token is visible to HTTP request's session

        resp = client.post(
            "/api/auth/password/reset",
            json={"token": token, "new_password": "newpassword123"},
        )
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "TOKEN_EXPIRED"

    def test_password_reset_invalid_token(self, client, db, unique_email):
        """Unknown reset token → 400 INVALID_TOKEN."""
        _make_user(db, unique_email("reset-invalid"), verified=True)

        resp = client.post(
            "/api/auth/password/reset",
            json={"token": "not-a-real-token", "new_password": "newpassword123"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"
