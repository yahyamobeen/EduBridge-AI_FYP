"""
Segregated administrator authentication, against the REAL database.

The unit suite (`tests/unit/test_admin_login_gate.py`) proves the rule with a
fake row, so it would keep passing if `app.lookup_user_for_login` had never
gained its `role` column, or if the SELECT list in `login()` misspelled it. These
tests exist to catch exactly that: they go through the real SECURITY DEFINER
function, so a missing migration or a wrong column name fails here.

Needs migration 20260816140000.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.auth.schemas import LoginRequest
from app.auth.service import login
from app.core.db import set_current_user_id
from app.core.errors import AppError

PASSWORD = "correct-horse-battery"  # noqa: S105 -- a fixture credential
WRONG_PASSWORD = "not-the-password"  # noqa: S105 -- a fixture credential
TURNSTILE_TOKEN = "test-turnstile-token"  # noqa: S105 -- a fixture token, not a password


def _student(db, email: str) -> str:
    """A verified, active student with a real argon2 password hash."""
    from app.auth.security import hash_password

    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, status, full_name, "
            "email_verified_at) VALUES (:id, :e, :pw, 'student', 'active', 'T', now())"
        ),
        {"id": user_id, "e": email, "pw": hash_password(PASSWORD)},
    )
    db.flush()
    return str(user_id)


def _provisioned_admin_email(db) -> str:
    """
    The address of an administrator that ALREADY EXISTS, or skip.

    `app_user_insert` refuses `role = 'admin'` to `app_backend` since
    20260816120000, so a test cannot create one — which is the point. An
    administrator is provisioned by the repository owner running SQL as the table
    owner (§1.6.6), and this helper reflects that rather than working around it.
    """
    email = db.execute(
        text("SELECT email FROM app_user WHERE role = 'admin' AND deleted_at IS NULL LIMIT 1")
    ).scalar()
    if email is None:
        pytest.skip("no administrator is provisioned in this database")
    return str(email)


def _attempt(db, email: str, *, admin_portal: bool, password: str = PASSWORD):
    return login(
        db,
        LoginRequest(email=email, password=password, turnstile_token=TURNSTILE_TOKEN),
        admin_portal=admin_portal,
    )


def _envelope(exc_info) -> tuple[str, str, int]:
    error: AppError = exc_info.value
    return (error.code, error.message, error.status_code)


class TestTheLookupActuallyReturnsARole:
    def test_the_function_has_the_column(self, db):
        """
        The narrowest possible statement of the migration's effect. If this
        fails, 20260816140000 has not been applied to whatever database the
        suite is pointed at, and every other test in this file is meaningless.
        """
        row = (
            db.execute(
                text(
                    "SELECT id, password_hash, status, email_verified_at, role "
                    "FROM app.lookup_user_for_login('no-such-user@example.invalid')"
                )
            )
            .mappings()
            .one_or_none()
        )

        assert row is None  # the column resolves; there is simply no such user

    def test_a_real_student_reads_back_as_student(self, db):
        email = f"admin-seg-role-{uuid4()}@test.com"
        _student(db, email)

        row = (
            db.execute(
                text("SELECT role FROM app.lookup_user_for_login(:e)"),
                {"e": email},
            )
            .mappings()
            .one()
        )

        assert str(row["role"]) == "student"


class TestNonAdministratorsCannotUseTheAdministratorEndpoint:
    def test_refused_with_the_wrong_password_envelope(self, db):
        """
        A correct password, a real active verified account, and still a 401 —
        identical to what a wrong password answers, so the administrator endpoint
        cannot be used to test whether an address exists.
        """
        email = f"admin-seg-{uuid4()}@test.com"
        _student(db, email)

        with pytest.raises(AppError) as refused:
            _attempt(db, email, admin_portal=True)
        with pytest.raises(AppError) as wrong_password:
            _attempt(db, email, admin_portal=False, password=WRONG_PASSWORD)

        assert _envelope(refused) == _envelope(wrong_password)
        assert refused.value.details == {}

    def test_the_same_account_still_works_at_the_public_endpoint(self, db):
        """The control. Without it, a gate that refused EVERYONE would pass."""
        email = f"admin-seg-ok-{uuid4()}@test.com"
        _student(db, email)

        result = _attempt(db, email, admin_portal=False)

        assert result["status"] == "two_factor_enrollment_required"


class TestAdministratorsCannotUseThePublicEndpoint:
    def test_refused_at_the_public_endpoint(self, db):
        """
        Skips until §1.6.6 provisions an administrator. The password is not known
        here, so this asserts the refusal a WRONG password would also produce —
        which is the whole invariant: the two are indistinguishable, and that is
        exactly why one test can stand for both.
        """
        email = _provisioned_admin_email(db)

        with pytest.raises(AppError) as refused:
            _attempt(db, email, admin_portal=False, password=WRONG_PASSWORD)

        assert _envelope(refused) == ("UNAUTHENTICATED", "Incorrect email or password.", 401)
