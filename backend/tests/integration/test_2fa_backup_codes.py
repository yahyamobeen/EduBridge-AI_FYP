"""
Integration tests for backup code regeneration.

Tests POST /auth/2fa/backup-codes:
- Returns 10 new codes
- Invalidates the old set
- Requires active 2FA
- Requires authentication
"""

import pytest
import pyotp
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.tokens import issue_challenge_token
from app.core.db import set_current_user_id
from app.models.enums import TokenKind


def _make_user(session, email: str, *, verified: bool = True) -> str:
    """Create a test user."""
    user_id = uuid4()
    set_current_user_id(session, user_id)
    columns = "id, email, password_hash, role, full_name"
    values = ":id, :email, 'x', 'student', 'Test User'"
    if verified:
        columns += ", email_verified_at"
        values += ", now()"
    session.execute(
        text(f"INSERT INTO app_user ({columns}) VALUES ({values})"),
        {"id": user_id, "email": email},
    )
    session.flush()
    set_current_user_id(session, user_id)
    return str(user_id)


def _enroll_and_activate_totp(client, db, user_id: str) -> list[str]:
    """Helper: enroll TOTP and activate 2FA, return backup_codes."""
    enroll_token = issue_challenge_token(
        db, user_id, kind=TokenKind.two_factor_enrollment, ttl_seconds=900
    )
    resp = client.post(
        "/api/auth/2fa/enroll",
        json={"method": "totp", "enrollment_token": enroll_token},
    )
    assert resp.status_code == 200
    secret = resp.json()["secret"]

    totp = pyotp.TOTP(secret)
    resp2 = client.post(
        "/api/auth/2fa/confirm",
        json={"code": totp.now(), "enrollment_token": enroll_token},
    )
    assert resp2.status_code == 200
    return resp2.json()["backup_codes"]


class TestRegenerateBackupCodes:
    def test_regenerate_backup_codes_returns_10_new_codes(self, client, db, unique_email):
        """POST /2fa/backup-codes returns 10 new codes."""
        user_id = _make_user(db, unique_email("regen-new"))
        original_codes = _enroll_and_activate_totp(client, db, user_id)

        # Get access token by verifying 2FA
        pending_token = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        row = db.execute(
            text("SELECT totp_secret_encrypted FROM two_factor_enrollment WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()
        from app.auth.totp import decrypt_secret
        secret = decrypt_secret(row[0])
        totp = pyotp.TOTP(secret)
        code = totp.now()

        resp = client.post(
            "/api/auth/2fa/verify",
            json={
                "pending_token": pending_token,
                "code": code,
                "type": "totp",
            },
        )
        assert resp.status_code == 200
        access_token = resp.json()["access_token"]

        # Regenerate backup codes
        resp2 = client.post(
            "/api/auth/2fa/backup-codes",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp2.status_code == 200
        new_codes = resp2.json()["backup_codes"]
        assert len(new_codes) == 10
        assert new_codes != original_codes

    def test_regenerate_backup_codes_invalidates_old_set(self, client, db, unique_email):
        """After regeneration, old backup codes no longer work."""
        user_id = _make_user(db, unique_email("regen-invalidate"))
        original_codes = _enroll_and_activate_totp(client, db, user_id)

        # Get access token
        pending_token = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        row = db.execute(
            text("SELECT totp_secret_encrypted FROM two_factor_enrollment WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()
        from app.auth.totp import decrypt_secret
        secret = decrypt_secret(row[0])
        totp = pyotp.TOTP(secret)

        resp = client.post(
            "/api/auth/2fa/verify",
            json={
                "pending_token": pending_token,
                "code": totp.now(),
                "type": "totp",
            },
        )
        access_token = resp.json()["access_token"]

        # Regenerate
        resp2 = client.post(
            "/api/auth/2fa/backup-codes",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp2.status_code == 200

        # Try to use old backup code
        pending_token2 = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        resp3 = client.post(
            "/api/auth/2fa/verify",
            json={
                "pending_token": pending_token2,
                "code": original_codes[0],
                "type": "backup_code",
            },
        )
        assert resp3.status_code == 401
        assert resp3.json()["error"]["code"] == "TWO_FACTOR_INVALID"

    def test_regenerate_requires_active_2fa(self, client, db, unique_email):
        """POST /2fa/backup-codes without active 2FA → 403."""
        user_id = _make_user(db, unique_email("regen-no-2fa"))

        # Create access token without 2FA
        from app.auth.security import create_access_token
        access_token, _ = create_access_token(user_id)

        resp = client.post(
            "/api/auth/2fa/backup-codes",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    def test_regenerate_requires_authentication(self, client, db, unique_email):
        """POST /2fa/backup-codes without bearer token → 401."""
        resp = client.post("/api/auth/2fa/backup-codes")
        assert resp.status_code == 401
