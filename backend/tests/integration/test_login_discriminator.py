"""
Which status `POST /auth/login` returns, and why it must be read privileged.

REGRESSION. `login()` decided this by reading `two_factor_enrollment` with a
plain SELECT. Login has no bound user, so `two_factor_enrollment_owner` matched
an unset `app.current_user_id()` and the read returned ZERO ROWS for every
account — which the code read as "no second factor yet".

A user with active TOTP was therefore told `two_factor_enrollment_required` and
handed an enrolment token; `/2fa/enroll` then refused, because its own read
happens after binding and saw the truth. Correct password, correct
authenticator, no way in. The lockout check read the same empty row, so it never
fired either.

Nothing failed loudly. That is the point of these tests: the bug's whole
signature was a query that returned nothing and looked reasonable.

Needs migration 20260803180000.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.auth.schemas import LoginRequest
from app.auth.service import login
from app.core.db import set_current_user_id
from app.core.errors import AppError

PASSWORD = "correct-horse-battery"  # noqa: S105 -- a fixture credential
# Accepted by the autouse `never_call_turnstile` fixture; never a real token.
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


def _enrol(db, user_id: str, *, status: str = "active", locked_for: int | None = None) -> None:
    set_current_user_id(db, user_id)
    db.execute(
        text(
            # Explicit casts: `:st` appears in an enum comparison AND a CASE,
            # and psycopg cannot deduce one type for both without them.
            "INSERT INTO two_factor_enrollment (user_id, method, status, confirmed_at, "
            "totp_secret_encrypted, locked_until) VALUES ("
            "  :uid, 'totp', CAST(:st AS two_factor_status),"
            "  CASE WHEN CAST(:st AS text) = 'active' THEN now() END,"
            "  :sec, CAST(:lock AS timestamptz))"
        ),
        {
            "uid": user_id,
            "st": status,
            "sec": b"x",
            "lock": (
                datetime.now(UTC) + timedelta(seconds=locked_for)
                if locked_for is not None
                else None
            ),
        },
    )
    db.flush()


class TestLoginSeesTheEnrolment:
    def test_an_enrolled_user_is_challenged_not_asked_to_enrol_again(self, db, unique_email):
        """
        The bug, stated as an assertion. `two_factor_required` means "prove the
        factor you already have"; `two_factor_enrollment_required` means "set one
        up" — and the second answer, given to someone who already has one, is a
        locked door, because /2fa/enroll refuses an active enrolment.
        """
        email = unique_email("disc")
        user_id = _student(db, email)
        _enrol(db, user_id, status="active")

        result = login(
            db, LoginRequest(email=email, password=PASSWORD, turnstile_token=TURNSTILE_TOKEN)
        )

        assert result["status"] == "two_factor_required", (
            "an enrolled user was sent to enrolment; login cannot see "
            "two_factor_enrollment under RLS without the privileged lookup"
        )
        assert result["method"] == "totp"
        assert result["pending_token"]

    def test_a_user_with_no_enrolment_is_still_sent_to_enrol(self, db, unique_email):
        """The other half: the fix must not make everyone look enrolled."""
        email = unique_email("disc")
        _student(db, email)

        result = login(
            db, LoginRequest(email=email, password=PASSWORD, turnstile_token=TURNSTILE_TOKEN)
        )

        assert result["status"] == "two_factor_enrollment_required"
        assert result["enrollment_token"]

    def test_a_pending_enrolment_is_treated_as_not_enrolled(self, db, unique_email):
        """Started but never confirmed: there is no factor to challenge yet."""
        email = unique_email("disc")
        user_id = _student(db, email)
        _enrol(db, user_id, status="pending")

        result = login(
            db, LoginRequest(email=email, password=PASSWORD, turnstile_token=TURNSTILE_TOKEN)
        )

        assert result["status"] == "two_factor_enrollment_required"


class TestLoginHonoursTheLockout:
    def test_a_locked_account_is_refused_at_login(self, db, unique_email):
        """
        The lockout ladder read the same empty row, so it was enforced at
        /2fa/verify and skipped entirely at login — which is the cheaper door to
        knock on.
        """
        email = unique_email("disc")
        user_id = _student(db, email)
        _enrol(db, user_id, status="active", locked_for=300)

        with pytest.raises(AppError) as exc:
            login(db, LoginRequest(email=email, password=PASSWORD, turnstile_token=TURNSTILE_TOKEN))

        assert exc.value.status_code == 423
        assert exc.value.code == "TWO_FACTOR_LOCKED"
        assert exc.value.details["locked_until"]

    def test_a_lapsed_lockout_does_not_block(self, db, unique_email):
        """Fail-closed, not fail-stuck: the lock has to expire."""
        email = unique_email("disc")
        user_id = _student(db, email)
        _enrol(db, user_id, status="active", locked_for=-300)

        assert login(
            db, LoginRequest(email=email, password=PASSWORD, turnstile_token=TURNSTILE_TOKEN)
        )["status"] == ("two_factor_required")

    def test_a_wrong_password_on_a_locked_account_still_answers_401(self, db, unique_email):
        """
        Order matters. The lockout is checked AFTER the password, so a wrong
        guess cannot be used to discover that an account exists and is locked.
        """
        email = unique_email("disc")
        user_id = _student(db, email)
        _enrol(db, user_id, status="active", locked_for=300)

        wrong = "not-the-password"  # noqa: S105 -- the point of the test
        with pytest.raises(AppError) as exc:
            login(db, LoginRequest(email=email, password=wrong, turnstile_token=TURNSTILE_TOKEN))

        assert exc.value.status_code == 401
