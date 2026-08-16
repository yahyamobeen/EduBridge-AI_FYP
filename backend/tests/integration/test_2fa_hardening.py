"""
The KAN-10b review fixes, asserted end to end.

Every test here corresponds to something that was WRONG and is now not. They
are grouped separately from the happy-path suites on purpose: if one of these
starts failing, a security property regressed, not a feature.

Needs migration 20260803160000.
"""

from uuid import uuid4

import pyotp
import pytest
from sqlalchemy import text

from app.auth.security import hash_token
from app.auth.tokens import issue_challenge_token, issue_preauth_token
from app.core.db import set_current_user_id
from app.models.enums import TokenKind


def _make_user(session, email: str, *, verified: bool = True) -> str:
    user_id = uuid4()
    set_current_user_id(session, user_id)
    if verified:
        session.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, role, full_name, "
                "email_verified_at) VALUES (:id, :email, 'x', 'student', 'Test User', now())"
            ),
            {"id": user_id, "email": email},
        )
    else:
        session.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, role, full_name) "
                "VALUES (:id, :email, 'x', 'student', 'Test User')"
            ),
            {"id": user_id, "email": email},
        )
    session.flush()
    set_current_user_id(session, user_id)
    return str(user_id)


def _enrollment_token(db, user_id: str) -> str:
    return issue_challenge_token(db, user_id, kind=TokenKind.two_factor_enrollment, ttl_seconds=900)


def _enrolled_totp(client, db, user_id: str) -> str:
    """Start a TOTP enrolment and return the secret."""
    resp = client.post(
        "/api/auth/2fa/enroll",
        json={"method": "totp", "enrollment_token": _enrollment_token(db, user_id)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["secret"]


def _enrollment_row(db, user_id: str):
    # Rebind: the request that just ran used its own session, and this one may
    # still be bound to whoever was set up last.
    set_current_user_id(db, user_id)
    return (
        db.execute(
            text(
                "SELECT status, failed_attempts, locked_until, last_used_counter "
                "FROM two_factor_enrollment WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one()
    )


class TestEnrolmentIsRateLimitedToo:
    """
    /2fa/confirm verified a code and raised, never touching `failed_attempts`.
    A six-digit email OTP was therefore guessable with only the per-address
    limiter in the way, and the account never locked. tdd.md §6.9 D7 draws no
    distinction between enrolment and challenge.
    """

    def test_repeated_wrong_codes_at_confirm_eventually_lock(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("lock"))
        _enrolled_totp(client, db, user_id)

        codes = set()
        last = None
        for _ in range(4):
            token = _enrollment_token(db, user_id)
            last = client.post(
                "/api/auth/2fa/confirm",
                json={"code": "000000", "enrollment_token": token},
            )
            codes.add(last.status_code)

        assert 423 in codes, f"never locked; saw {codes}"
        assert last.json()["error"]["code"] in {"TWO_FACTOR_LOCKED", "TWO_FACTOR_INVALID"}

    def test_a_lockout_carries_details_the_client_can_count_down_from(
        self, client, db, unique_email
    ):
        user_id = _make_user(db, unique_email("lock"))
        _enrolled_totp(client, db, user_id)

        for _ in range(4):
            resp = client.post(
                "/api/auth/2fa/confirm",
                json={"code": "000000", "enrollment_token": _enrollment_token(db, user_id)},
            )
            if resp.status_code == 423:
                assert resp.json()["error"]["details"]["locked_until"]
                return
        pytest.fail("never locked")

    def test_failures_are_counted_and_survive_the_error(self, client, db, unique_email):
        """
        The write has to be COMMITTED before the 401 propagates, or `get_db`
        rolls it back and the counter never moves — unlimited attempts behind a
        correct-looking implementation.
        """
        user_id = _make_user(db, unique_email("lock"))
        _enrolled_totp(client, db, user_id)

        client.post(
            "/api/auth/2fa/confirm",
            json={"code": "000000", "enrollment_token": _enrollment_token(db, user_id)},
        )

        assert _enrollment_row(db, user_id)["failed_attempts"] >= 1


class TestReEnrollingCannotLaunderALockout:
    """
    `upsert_2fa_enrollment` reset `failed_attempts = 0, locked_until = NULL` on
    conflict, and the client's enrolment resend IS a re-call of /2fa/enroll
    (tdd.md §14.4 finding 2) — so a locked enrolment was cleared by reloading
    the page. Only a successful verification clears the counters now.
    """

    def test_a_lockout_survives_re_enrolment(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("relock"))
        _enrolled_totp(client, db, user_id)

        for _ in range(4):
            client.post(
                "/api/auth/2fa/confirm",
                json={"code": "000000", "enrollment_token": _enrollment_token(db, user_id)},
            )
        locked_before = _enrollment_row(db, user_id)["locked_until"]
        assert locked_before is not None, "precondition: the account should be locked"

        # The page reload.
        resp = client.post(
            "/api/auth/2fa/enroll",
            json={"method": "totp", "enrollment_token": _enrollment_token(db, user_id)},
        )

        # FINDING A9, fixed: /2fa/enroll now checks the lockout, so the reload is
        # refused outright rather than being served and merely failing to launder
        # the counters. Asserted here because this test previously ignored the
        # response entirely and would have passed either way.
        assert resp.status_code == 423, resp.text
        assert resp.json()["error"]["code"] == "TWO_FACTOR_LOCKED"

        # The original guarantee, still asserted. `upsert_2fa_enrollment`
        # preserving the counters is the layer underneath — it is what holds if
        # the check above is ever bypassed by a new caller.
        after = _enrollment_row(db, user_id)
        assert after["locked_until"] is not None, "re-enrolling cleared the lockout"
        assert after["failed_attempts"] >= 1, "re-enrolling reset the failure counter"

    def test_a_locked_account_is_not_sent_another_enrolment_email(self, client, db, unique_email):
        """
        Finding A9, the reason it mattered.

        `/2fa/enroll` with `method=email_otp` SENDS MAIL. Without the lockout
        check, a caller holding a live enrolment token could re-post it against a
        locked account and generate a message every time — bounded only by the
        per-account rate limit, which is five per five minutes.

        Scope, honestly: this was never a way to bypass guessing. `/2fa/confirm`
        checked the lockout throughout, and `app.upsert_2fa_enrollment`
        deliberately preserves `failed_attempts` and `locked_until`. It was mail
        flooding, not a breach — fixed because a lockout that four of five entry
        points honour is not a lockout.
        """
        user_id = _make_user(db, unique_email("nomail"))
        _enrolled_totp(client, db, user_id)

        for _ in range(4):
            client.post(
                "/api/auth/2fa/confirm",
                json={"code": "000000", "enrollment_token": _enrollment_token(db, user_id)},
            )
        assert _enrollment_row(db, user_id)["locked_until"] is not None, "precondition"

        resp = client.post(
            "/api/auth/2fa/enroll",
            json={"method": "email_otp", "enrollment_token": _enrollment_token(db, user_id)},
        )

        assert resp.status_code == 423, resp.text
        assert resp.json()["error"]["details"]["locked_until"]


class TestEnrolmentCodeCannotBeReplayed:
    """
    Enrolment verified the first TOTP code and stored nothing, so
    `last_used_counter` stayed NULL until the first successful CHALLENGE —
    leaving the code that completed enrolment usable again at /2fa/verify for
    its whole ±1 window.
    """

    def test_confirm_records_the_counter_it_consumed(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("replay"))
        secret = _enrolled_totp(client, db, user_id)

        resp = client.post(
            "/api/auth/2fa/confirm",
            json={
                "code": pyotp.TOTP(secret).now(),
                "enrollment_token": _enrollment_token(db, user_id),
            },
        )
        assert resp.status_code == 200, resp.text

        row = _enrollment_row(db, user_id)
        assert row["status"] == "active"
        assert row["last_used_counter"] is not None, (
            "the enrolment code was consumed but not recorded, so it stays replayable"
        )

    def test_the_enrolment_code_is_rejected_at_the_next_challenge(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("replay"))
        secret = _enrolled_totp(client, db, user_id)
        code = pyotp.TOTP(secret).now()

        assert (
            client.post(
                "/api/auth/2fa/confirm",
                json={"code": code, "enrollment_token": _enrollment_token(db, user_id)},
            ).status_code
            == 200
        )

        pending = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        replay = client.post(
            "/api/auth/2fa/verify",
            json={"pending_token": pending, "code": code, "type": "totp"},
        )

        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "TWO_FACTOR_INVALID"


class TestSpentTokensAreInvalidNotExpired:
    """
    `check_token_status` did not report `revoked`, so a token that had already
    been used answered TOKEN_EXPIRED (410) — which the client renders with a
    "request a new link" affordance, sending the user round a loop they had in
    fact already finished.
    """

    def test_a_spent_password_reset_token_is_invalid(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("spent"), verified=True)
        token = issue_preauth_token(db, user_id, kind=TokenKind.password_reset, ttl_seconds=3600)
        db.flush()

        first = client.post(
            "/api/auth/password/reset",
            json={"token": token, "new_password": "a-new-password-1"},
        )
        assert first.status_code == 204, first.text

        second = client.post(
            "/api/auth/password/reset",
            json={"token": token, "new_password": "a-third-password-1"},
        )
        assert second.status_code == 400
        assert second.json()["error"]["code"] == "INVALID_TOKEN"

    def test_an_unused_lapsed_token_still_reports_expired(self, client, db, unique_email):
        """The other half: a genuinely stale link must still offer a resend."""
        user_id = _make_user(db, unique_email("stale"), verified=True)
        token = issue_preauth_token(db, user_id, kind=TokenKind.password_reset, ttl_seconds=-3600)
        db.flush()

        resp = client.post(
            "/api/auth/password/reset",
            json={"token": token, "new_password": "a-new-password-1"},
        )

        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "TOKEN_EXPIRED"


class TestEnumerationSurface:
    def test_forgot_answers_identically_for_known_and_unknown_addresses(
        self, client, db, unique_email
    ):
        known = unique_email("known")
        _make_user(db, known, verified=True)
        db.flush()

        hit = client.post("/api/auth/password/forgot", json={"email": known})
        miss = client.post("/api/auth/password/forgot", json={"email": "nobody-at-all@example.com"})

        assert hit.status_code == miss.status_code == 204
        assert hit.content == miss.content

    def test_a_suspended_account_looks_exactly_like_an_unknown_one(self, client, db, unique_email):
        email = unique_email("suspended")
        user_id = _make_user(db, email, verified=True)
        set_current_user_id(db, user_id)
        db.execute(
            text("UPDATE app_user SET status = 'suspended' WHERE id = :uid"), {"uid": user_id}
        )
        db.flush()

        resp = client.post("/api/auth/password/forgot", json={"email": email})
        assert resp.status_code == 204

        # ...and no reset token was minted for it.
        set_current_user_id(db, user_id)
        minted = db.execute(
            text(
                "SELECT count(*) FROM auth_token WHERE user_id = :uid AND kind = 'password_reset'"
            ),
            {"uid": user_id},
        ).scalar_one()
        assert minted == 0


class TestResendIsCatalogued:
    def test_resend_on_a_totp_enrolment_uses_a_catalogued_code(self, client, db, unique_email):
        """
        It raised `INVALID_METHOD`, which appears in neither tdd.md §7.3 nor the
        client's ERROR_CODES — so the client fell through to "something went
        wrong" for a perfectly explainable condition.
        """
        user_id = _make_user(db, unique_email("resend"))
        secret = _enrolled_totp(client, db, user_id)
        client.post(
            "/api/auth/2fa/confirm",
            json={
                "code": pyotp.TOTP(secret).now(),
                "enrollment_token": _enrollment_token(db, user_id),
            },
        )

        pending = issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        resp = client.post("/api/auth/2fa/resend", json={"pending_token": pending})

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert resp.json()["error"]["details"]["fields"]


class TestOnboardingTokenIsNotASession:
    def test_the_email_verify_token_cannot_call_me(self, client, db, unique_email):
        """
        The DoD item. If this token reached a business endpoint, controlling a
        mailbox would be a full login and 2FA would be bypassable.
        """
        user_id = _make_user(db, unique_email("scope"), verified=False)
        token = issue_preauth_token(db, user_id, kind=TokenKind.email_verify, ttl_seconds=3600)
        db.flush()

        verified = client.post("/api/auth/email/verify", json={"token": token})
        assert verified.status_code == 200, verified.text
        onboarding_token = verified.json()["access_token"]

        blocked = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {onboarding_token}"}
        )
        assert blocked.status_code == 401
        assert blocked.json()["error"]["code"] == "UNAUTHENTICATED"


class TestHashedAtRest:
    def test_the_email_otp_is_never_stored_in_the_clear(self, client, db, unique_email):
        user_id = _make_user(db, unique_email("otp"))
        resp = client.post(
            "/api/auth/2fa/enroll",
            json={"method": "email_otp", "enrollment_token": _enrollment_token(db, user_id)},
        )
        assert resp.status_code == 200, resp.text

        set_current_user_id(db, user_id)
        stored = db.execute(
            text(
                "SELECT token_hash FROM auth_token "
                "WHERE user_id = :uid AND kind = 'two_factor_email_otp' AND revoked = false"
            ),
            {"uid": user_id},
        ).scalar_one()

        # Keyed HMAC, not a bare digest: six digits is a million possibilities,
        # so an unkeyed hash of an OTP is a rainbow table.
        assert stored.startswith("hmac-sha256:")
        assert stored != hash_token("000000")
