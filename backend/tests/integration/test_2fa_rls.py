"""
Integration tests for 2FA Row Level Security.

Tests that two_factor_enrollment and two_factor_backup_code tables are:
- Invisible without a bound user (zero rows)
- Owner-only (user A cannot see user B's rows)
"""

from uuid import uuid4

from sqlalchemy import text

from app.core.db import set_current_user_id


def _make_user(session, email: str) -> str:
    """Create a test user."""
    user_id = uuid4()
    set_current_user_id(session, user_id)
    session.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, full_name) "
            "VALUES (:id, :email, 'x', 'student', 'Test User')"
        ),
        {"id": user_id, "email": email},
    )
    session.flush()
    return str(user_id)


def _create_2fa_enrollment(session, user_id: str, method: str = "totp") -> None:
    """Create a 2FA enrollment row using the SECURITY DEFINER function."""
    # Must bind the user for RLS — the policy requires user_id = current_user_id
    set_current_user_id(session, user_id)
    if method == "totp":
        from app.auth.totp import encrypt_secret

        secret = encrypt_secret("JBSWY3DPEHPK3PXP")
        session.execute(
            text("SELECT app.upsert_2fa_enrollment(:uid, 'totp', :secret)"),
            {"uid": user_id, "secret": secret},
        )
    else:
        session.execute(
            text("SELECT app.upsert_2fa_enrollment(:uid, 'email_otp', NULL)"),
            {"uid": user_id},
        )
    session.flush()


def _create_backup_codes(session, user_id: str, codes: list[str]) -> None:
    """Create backup code rows using the SECURITY DEFINER function."""
    from app.auth.backup_codes import hash_backup_code

    # Must bind the user for RLS
    set_current_user_id(session, user_id)
    hashes = [hash_backup_code(c) for c in codes]
    session.execute(
        text("SELECT app.replace_backup_codes(:uid, :hashes)"),
        {"uid": user_id, "hashes": hashes},
    )
    session.flush()


class TestTwoFactorEnrollmentRls:
    def test_invisible_without_bound_user(self, db, unique_email):
        """With no user bound, two_factor_enrollment returns zero rows."""
        user_id = _make_user(db, unique_email("rls-no-bound"))
        _create_2fa_enrollment(db, user_id)

        # Clear the bound user
        db.execute(text("SELECT set_config('app.current_user_id', '', true)"))

        count = db.execute(text("SELECT count(*) FROM two_factor_enrollment")).scalar_one()
        assert count == 0

    def test_owner_only(self, db, unique_email):
        """User A cannot see user B's enrollment row."""
        user_a = _make_user(db, unique_email("rls-owner-a"))
        user_b = _make_user(db, unique_email("rls-owner-b"))

        _create_2fa_enrollment(db, user_a)
        _create_2fa_enrollment(db, user_b)

        # Bind user A
        set_current_user_id(db, user_a)

        rows = db.execute(text("SELECT user_id FROM two_factor_enrollment")).fetchall()

        # Should only see user A's row
        assert len(rows) == 1
        assert str(rows[0][0]) == user_a

    def test_user_sees_own_row(self, db, unique_email):
        """With user bound, they can see their own enrollment."""
        user_id = _make_user(db, unique_email("rls-own"))
        _create_2fa_enrollment(db, user_id)

        set_current_user_id(db, user_id)

        count = db.execute(
            text("SELECT count(*) FROM two_factor_enrollment WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar_one()
        assert count == 1


class TestTwoFactorBackupCodeRls:
    def test_invisible_without_bound_user(self, db, unique_email):
        """With no user bound, two_factor_backup_code returns zero rows."""
        user_id = _make_user(db, unique_email("backup-rls-no-bound"))
        _create_backup_codes(db, user_id, ["ABCDEF12", "GHIJKL34"])

        # Clear the bound user
        db.execute(text("SELECT set_config('app.current_user_id', '', true)"))

        count = db.execute(text("SELECT count(*) FROM two_factor_backup_code")).scalar_one()
        assert count == 0

    def test_owner_only(self, db, unique_email):
        """User A cannot see user B's backup codes."""
        user_a = _make_user(db, unique_email("backup-rls-a"))
        user_b = _make_user(db, unique_email("backup-rls-b"))

        _create_backup_codes(db, user_a, ["ABCDEF12", "GHIJKL34"])
        _create_backup_codes(db, user_b, ["MNOPQR56", "STUVWX78"])

        # Bind user A
        set_current_user_id(db, user_a)

        rows = db.execute(text("SELECT user_id FROM two_factor_backup_code")).fetchall()

        # Should only see user A's rows
        assert len(rows) == 2
        assert all(str(row[0]) == user_a for row in rows)

    def test_user_sees_own_codes(self, db, unique_email):
        """With user bound, they can see their own backup codes."""
        user_id = _make_user(db, unique_email("backup-rls-own"))
        _create_backup_codes(db, user_id, ["ABCDEF12", "GHIJKL34", "MNOPQR56"])

        set_current_user_id(db, user_id)

        count = db.execute(
            text("SELECT count(*) FROM two_factor_backup_code WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar_one()
        assert count == 3
