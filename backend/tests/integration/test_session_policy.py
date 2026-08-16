"""
Session policy — Phase 4, findings E2 and E3.

Revoking refresh tokens ends the ability to obtain a NEW access token and does
nothing about the one already in the caller's memory, which stays valid for up
to `access_token_ttl_minutes`. So before this phase, a password change — the
thing a user does when they believe they have been compromised — left the
attacker signed in for another quarter of an hour.

`app_user.sessions_invalidated_at` closes that window, and every test here
exists because one specific way of building it fails SILENTLY.
"""

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.auth.security import create_access_token, create_onboarding_token, hash_password
from app.core.config import get_settings
from app.core.db import set_current_user_id

PASSWORD = "password123"  # noqa: S105 -- a fixture value, not a credential


def _user(db, email: str) -> str:
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user "
            "(id, email, password_hash, role, status, full_name, email_verified_at) "
            "VALUES (:id, :e, :pw, 'parent', 'active', 'Session Probe', now())"
        ),
        {"id": user_id, "e": email, "pw": hash_password(PASSWORD)},
    )
    db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _stamp(db) -> datetime | None:
    """Read the caller's own invalidation stamp. Requires a bound user."""
    return db.execute(
        text("SELECT sessions_invalidated_at FROM app_user WHERE id = :u"),
        {"u": db.execute(text("SELECT app.current_user_id()")).scalar()},
    ).scalar()


class TestPasswordChangeEndsLiveSessions:
    def test_the_access_token_dies_too_not_just_the_refresh_family(self, client, db, unique_email):
        """
        ⚠️ THE TEST THAT WOULD PASS VACUOUSLY UNDER `now()`, AND THE REASON THE
           WHOLE PHASE USES `clock_timestamp()`.

        `now()` is `transaction_timestamp()` and is FROZEN for the transaction.
        The integration suite runs inside one outer transaction with savepoint
        nesting, so a stamp written with `now()` lands at TEST START — earlier
        than the `iat` of a token minted moments ago inside the same test. The
        token would survive the invalidation that was supposed to kill it, and
        nothing would fail.

        Measured on this project inside one transaction across 2 real seconds:
        `now()` moved 0.00s, `clock_timestamp()` moved 2.20s.

        Revert `app.invalidate_sessions` to `now()` and this test must fail.
        """
        user_id = _user(db, unique_email("session"))
        token, _ = create_access_token(UUID(user_id))

        # The token works before the change.
        assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 200

        changed = client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": "brand-new-password"},
            headers=_bearer(token),
        )
        assert changed.status_code == 204, changed.text

        after = client.get("/api/auth/me", headers=_bearer(token))
        assert after.status_code == 401, (
            "the access token outlived the password change -- the stamp is either "
            "missing or was written with now()"
        )
        assert after.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_only_the_caller_is_signed_out(self, client, db, unique_email):
        caller = _user(db, unique_email("session"))
        bystander = _user(db, unique_email("session"))
        caller_token, _ = create_access_token(UUID(caller))
        bystander_token, _ = create_access_token(UUID(bystander))

        client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": "brand-new-password"},
            headers=_bearer(caller_token),
        )

        assert client.get("/api/auth/me", headers=_bearer(bystander_token)).status_code == 200


class TestTheTrapsThatFailSilently:
    def test_a_user_who_never_had_an_invalidation_event_can_still_authenticate(
        self, client, db, unique_email
    ):
        """
        ⚠️ TRAP 3, AND IT 401s EVERY REQUEST FOR EVERY USER.

        `sessions_invalidated_at` is NULL until a user's first event, which is
        almost everybody. Expressed as a SQL `WHERE` clause the comparison yields
        NULL against that, the row is filtered out, the dependency reads "no such
        user" and answers 401 — with the SAME message as a malformed token, so it
        presents as a client bug rather than as a server one.

        The comparison therefore lives in Python
        (`security.session_is_invalidated`) and the column is merely SELECTed.
        """
        user_id = _user(db, unique_email("session"))
        assert (
            db.execute(
                text("SELECT sessions_invalidated_at FROM app_user WHERE id = :u"), {"u": user_id}
            ).scalar()
            is None
        )

        token, _ = create_access_token(UUID(user_id))
        assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 200

    def test_a_token_issued_after_the_stamp_still_works(
        self, client, db, unique_email, monkeypatch
    ):
        """
        The inverse guard: invalidation must not become a permanent ban.

        ⚠️ IT SLEEPS, AND THE OBVIOUS ALTERNATIVE IS IMPOSSIBLE. The first
        version minted the second token with `now=stamp + 10s` to avoid waiting.
        **PyJWT refuses to decode a token whose `iat` is in the future** (2.13
        raises, and `decode_access_claims` reports it as an invalid token), so
        that token could never have existed — the test was asserting against a
        shape production cannot produce, and failed for a reason unrelated to
        what it was checking.

        Real time therefore has to pass. `session_invalidation_skew_seconds` is
        turned down to 1 so the wait is two seconds instead of seven; the LOGIC
        under test is identical, only the constant differs. Waiting out the full
        default here would put seven idle seconds into every suite run.

        The allowance exists because `iat` is minted by Python on this host and
        the stamp by `clock_timestamp()` on the database host — measured 1.1s
        apart, in the direction that let an invalidated token survive.
        """
        monkeypatch.setattr(get_settings(), "session_invalidation_skew_seconds", 1)

        user_id = _user(db, unique_email("session"))
        first, _ = create_access_token(UUID(user_id))

        client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": "brand-new-password"},
            headers=_bearer(first),
        )
        assert client.get("/api/auth/me", headers=_bearer(first)).status_code == 401

        # Past the stamp, past the allowance, past the truncation boundary.
        time.sleep(2.2)
        later, _ = create_access_token(UUID(user_id))

        assert client.get("/api/auth/me", headers=_bearer(later)).status_code == 200, (
            "a token issued after the invalidation was refused -- the stamp is "
            "acting as a permanent ban"
        )

    def test_an_onboarding_token_cannot_bypass_the_comparison(self, db, unique_email):
        """
        ⚠️ WHY THE COMPARISON IS A SHARED HELPER RATHER THAN INLINE.

        The onboarding token carries an `iat` exactly like an access token, so
        the moment any endpoint decodes with `expected_type="onboarding"` a
        second, forgotten copy of this rule becomes a bypass. Asserted against
        the helper itself, because no endpoint accepts onboarding tokens today —
        which is precisely why the guard needs pinning before one does.
        """
        from app.auth.security import decode_access_claims, session_is_invalidated

        user_id = _user(db, unique_email("session"))
        issued = datetime.now(UTC) - timedelta(minutes=5)
        token, _ = create_onboarding_token(UUID(user_id), now=issued)

        claims = decode_access_claims(token, expected_type="onboarding")
        assert session_is_invalidated(claims.issued_at, datetime.now(UTC)) is True
        assert session_is_invalidated(claims.issued_at, None) is False

    def test_a_token_with_no_issue_time_is_refused(self, client, db, unique_email):
        """
        Fail closed on a missing claim. Treating "no `iat`" as "issued now" would
        make every invalidation bypassable by stripping one field.
        """
        import jwt

        from app.core.config import get_settings

        user_id = _user(db, unique_email("session"))
        settings = get_settings()
        forged = jwt.encode(
            {
                "sub": user_id,
                "type": "access",
                "exp": datetime.now(UTC) + timedelta(minutes=15),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        assert client.get("/api/auth/me", headers=_bearer(forged)).status_code == 401


class TestReuseDetectionAlsoEndsLiveSessions:
    def test_a_detected_reuse_invalidates_access_tokens(self, db, unique_email, monkeypatch):
        """
        Token theft is the case where the stolen ACCESS token matters most, so
        `app.revoke_refresh_family` stamps as well as revoking.

        ⚠️ Three of the four invalidation events run with NO BOUND USER — this
        one included, since reuse detection happens on `get_db`. A plain
        `UPDATE app_user SET sessions_invalidated_at = ...` would match zero rows
        under `app_user_self_update` AND RAISE NOTHING. That is why the stamp
        lives inside the SECURITY DEFINER function.
        """
        from app.auth import tokens
        from app.core.config import get_settings

        user_id = _user(db, unique_email("session"))
        set_current_user_id(db, user_id)
        plain, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()
        tokens.rotate_refresh_token(db, plain)
        db.flush()

        monkeypatch.setattr(get_settings(), "refresh_race_grace_seconds", 0)
        with pytest.raises(tokens.RefreshTokenReuseError):
            tokens.rotate_refresh_token(db, plain)
        tokens.revoke_refresh_family(db, user_id)
        db.flush()

        assert (
            db.execute(
                text("SELECT sessions_invalidated_at FROM app_user WHERE id = :u"), {"u": user_id}
            ).scalar()
            is not None
        )


class TestTheAbsoluteCeilingIsConfigured:
    def test_a_ceiling_shorter_than_one_token_is_refused_at_boot(self):
        """
        A cap of 7 days against a 7-day refresh token can never fire: the token
        expires first on every chain, so the setting looks like a session bound
        and is inert. Caught by a validator rather than discovered by nobody.

        ⚠️ SET THROUGH THE ENVIRONMENT, NOT AS KEYWORD ARGUMENTS. Both fields
        carry an explicit `validation_alias`, and with one set pydantic matches
        the ALIAS only — so `Settings(session_absolute_ttl_days=7)` is silently
        ignored, the default of 14 applies, and the test passes for the wrong
        reason. The first version of this test did exactly that and reported
        DID NOT RAISE.
        """
        import pytest as _pytest
        from pydantic import ValidationError

        from app.core.config import Settings

        monkeypatch = _pytest.MonkeyPatch()
        try:
            monkeypatch.setenv("JWT_REFRESH_TTL_DAYS", "7")
            monkeypatch.setenv("SESSION_ABSOLUTE_TTL_DAYS", "7")
            with pytest.raises(ValidationError, match="SESSION_ABSOLUTE_TTL_DAYS"):
                Settings()
        finally:
            monkeypatch.undo()
