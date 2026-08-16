from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.auth import tokens
from app.auth.security import hash_token
from app.core.config import get_settings
from app.core.db import set_current_user_id
from app.models.enums import TokenKind


def _make_user(session, email: str, **extra) -> str:
    """
    Bind the id BEFORE inserting.

    The applied database scopes app_user inserts to the acting user, so an
    unbound insert is refused — which is also why `register()` binds the id it
    is about to create. (`rls_policies.sql` in the repo shows
    `app_user_insert ... WITH CHECK (true)`; the live policy is stricter, so the
    file and the database disagree. Worth reconciling separately.)
    """
    from uuid import uuid4

    from app.core.db import set_current_user_id

    user_id = uuid4()
    set_current_user_id(session, user_id)
    columns = "id, email, password_hash, role, full_name"
    values = ":id, :email, 'x', 'student', 'Test User'"
    if extra.get("verified"):
        columns += ", email_verified_at"
        values += ", now()"
    session.execute(
        text(f"INSERT INTO app_user ({columns}) VALUES ({values})"),  # noqa: S608
        {"id": user_id, "email": email},
    )
    return str(user_id)


@pytest.fixture
def user_id(db, unique_email):
    uid = _make_user(db, unique_email("tok"))
    db.flush()
    # Token reads go through the SECURITY DEFINER lookups, but `revoke_user_tokens`
    # runs under `auth_token_owner`, so the tests bind a user like a real
    # authenticated request would.
    set_current_user_id(db, uid)
    return uid


class TestIssue:
    def test_refresh_token_is_stored_hashed_and_never_in_plaintext(self, db, user_id):
        plain, row_id = tokens.issue_refresh_token(db, user_id)
        db.flush()

        assert len(plain) >= 40

        # The row is findable by the HASH and not by the token itself, which is
        # what "stored hashed" has to mean in practice.
        assert tokens.find_token(db, plain) is not None
        matched_by_plaintext = db.execute(
            text("SELECT count(*) FROM app.lookup_refresh_token(:t)"), {"t": plain}
        ).scalar_one()
        assert matched_by_plaintext == 0, "the plaintext token matched a stored row"
        assert hash_token(plain) != plain

        found = tokens.find_token(db, plain)
        assert found.id == row_id
        assert found.kind == TokenKind.refresh.value
        assert found.revoked is False
        assert found.expires_at > datetime.now(UTC)

    def test_challenge_token_honours_its_ttl(self, db, user_id):
        plain = tokens.issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        db.flush()

        found = tokens.find_token(db, plain)
        assert found is not None
        assert found.expires_at - datetime.now(UTC) <= timedelta(seconds=300)


class TestRotation:
    def test_rotation_issues_a_new_token_and_revokes_the_old(self, db, user_id):
        plain_old, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()

        rotated = tokens.rotate_refresh_token(db, plain_old)
        assert rotated is not None
        plain_new, _ = rotated
        db.flush()

        assert plain_new != plain_old
        assert tokens.find_token(db, plain_old).revoked is True
        assert tokens.find_token(db, plain_new).revoked is False

    def test_unknown_token_is_simply_rejected(self, db, user_id):
        assert tokens.rotate_refresh_token(db, "does-not-exist") is None

    def test_expired_token_is_rejected(self, db, user_id):
        """
        ⚠️ REWRITTEN IN PHASE 4, AND THE OLD VERSION WOULD NOW PASS VACUOUSLY.

        It used to call `rotate_refresh_token(db, plain, now=far_future)` and
        assert None — i.e. it faked the clock in PYTHON. Rotation is now one
        locked statement inside `app.rotate_refresh_token`, which compares
        against `clock_timestamp()`, so `now` only sets the NEW token's expiry
        and a live token would happily rotate. The test has to expire the row.

        That is a strict improvement: the database is what actually decides, and
        this now asserts the thing production relies on.

        ⚠️ The token is minted WITH A PAST `now` rather than by updating
        `expires_at`, because `20260817120000` narrowed UPDATE on `auth_token` to
        `revoked` — a direct write is `permission denied for table auth_token`,
        which is that migration working. Every setup below reaches its state
        through a path production also uses.
        """
        long_ago = datetime.now(UTC) - timedelta(days=999)
        plain, _ = tokens.issue_refresh_token(db, user_id, now=long_ago)
        db.flush()

        assert tokens.rotate_refresh_token(db, plain) is None

    def test_a_family_past_the_absolute_ceiling_cannot_rotate(self, db, user_id, monkeypatch):
        """
        The absolute session cap (finding E2).

        Rotation without one means a chain is extendable for ever, seven days at
        a time, so no session anybody keeps using ever expires. The token itself
        is still live here — only the FAMILY has aged out, which is the whole
        distinction, and it is why the cap cannot be expressed as a token expiry.

        The ceiling is driven to zero through the SETTING rather than by ageing
        `family_started_at`, which is not writable by the application role. Same
        branch, reached the way production reaches it.
        """
        monkeypatch.setattr(get_settings(), "session_absolute_ttl_days", 0)

        plain, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()

        assert tokens.rotate_refresh_token(db, plain) is None
        # Refused AND closed out, so a second attempt cannot keep probing.
        assert tokens.find_token(db, plain).revoked is True

    def test_the_family_start_is_carried_forward_not_restarted(self, db, user_id):
        """
        ⚠️ THE ASSERTION THAT MAKES THE CAP MEAN ANYTHING. If rotation stamped a
        fresh `family_started_at`, every refresh would reset the ceiling and the
        cap would be unreachable — the code would look right and bound nothing.
        """
        plain_old, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()
        started = db.execute(
            text("SELECT family_started_at FROM auth_token WHERE id = :i"),
            {"i": tokens.find_token(db, plain_old).id},
        ).scalar()

        plain_new, _ = tokens.rotate_refresh_token(db, plain_old)
        db.flush()

        carried = db.execute(
            text("SELECT family_started_at FROM auth_token WHERE id = :i"),
            {"i": tokens.find_token(db, plain_new).id},
        ).scalar()
        assert carried == started


class TestReuseDetection:
    """
    Rotation means a refresh token is valid EXACTLY ONCE, so a second use means
    two parties hold it and one is not the user. Answering 401 and stopping
    there would leave a thief who redeemed first with a working rotating chain,
    and would record nothing.
    """

    def test_an_immediate_replay_is_a_race_and_does_not_revoke_the_family(self, db, user_id):
        """
        ⚠️ THIS TEST ASSERTED THE OPPOSITE UNTIL PHASE 4, AND THE CHANGE IS
           DELIBERATE, NOT A LOOSENED ASSERTION.

        The client's single-flight guard is per browser TAB, so two tabs
        refreshing together present the same token twice. Reading that as theft
        revoked the whole family and signed the user out of every device, on a
        collision they could not avoid.

        `app.rotate_refresh_token` forgives a replay only when BOTH hold: the
        revocation is inside `refresh_race_grace_seconds`, and a live sibling of
        the same family still exists. Both are asserted separately below.

        ⚠️ THE COST, WRITTEN DOWN RATHER THAN GLOSSED: a thief replaying a stolen
        token inside that window also lands here, so the family is not revoked.
        They are still refused — the token buys them nothing — and `refresh()`
        writes a `refresh_token_race_detected` audit row so the event is not
        silent. A replay 2 seconds after a legitimate rotation is genuinely
        indistinguishable from a second tab.
        """
        plain_old, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()
        plain_new, _ = tokens.rotate_refresh_token(db, plain_old)
        db.flush()

        with pytest.raises(tokens.RefreshTokenRaceError) as caught:
            tokens.rotate_refresh_token(db, plain_old)

        assert str(caught.value.user_id) == str(user_id)
        # The whole point: the winner's token is untouched.
        assert tokens.find_token(db, plain_new).revoked is False

    def test_a_replay_with_no_live_sibling_is_reuse(self, db, user_id):
        """
        Half of what separates a race from a theft. With the replacement already
        dead there is no concurrent refresh to have lost — so this is a replay of
        a token that should not exist any more, inside the grace window or not.
        """
        plain_old, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()
        plain_new, _ = tokens.rotate_refresh_token(db, plain_old)
        db.flush()
        db.execute(
            text("UPDATE auth_token SET revoked = true WHERE id = :i"),
            {"i": tokens.find_token(db, plain_new).id},
        )
        db.flush()

        with pytest.raises(tokens.RefreshTokenReuseError) as caught:
            tokens.rotate_refresh_token(db, plain_old)

        assert str(caught.value.user_id) == str(user_id)

    def test_a_replay_outside_the_grace_window_is_reuse(self, db, user_id, monkeypatch):
        """
        The other half. A captured token replayed later is exactly the case
        reuse detection exists for, and the grace window must not swallow it.

        The window is closed to zero through the SETTING rather than by sleeping
        ten real seconds or ageing `revoked_at` (which the application role may
        not write). A test that waits ten seconds is a test people delete.
        """
        plain_old, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()
        tokens.rotate_refresh_token(db, plain_old)
        db.flush()

        monkeypatch.setattr(get_settings(), "refresh_race_grace_seconds", 0)

        with pytest.raises(tokens.RefreshTokenReuseError) as caught:
            tokens.rotate_refresh_token(db, plain_old)

        assert str(caught.value.user_id) == str(user_id)

    def test_revoking_the_family_kills_every_live_token(self, db, user_id):
        live_a, _ = tokens.issue_refresh_token(db, user_id)
        live_b, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()

        revoked = tokens.revoke_refresh_family(db, user_id)
        db.flush()

        assert revoked == 2
        assert tokens.find_token(db, live_a).revoked is True
        assert tokens.find_token(db, live_b).revoked is True

    def test_the_reuse_is_audited(self, db, user_id):
        """
        The audit INSERT must be permitted on this path — it runs before any
        session exists, and `audit_insert` is WITH CHECK (true) precisely so it
        can. `audit_admin_read` then hides the row from this non-admin caller,
        so there is nothing to read back; a denied insert would raise here,
        which is the assertion.
        """
        tokens.issue_refresh_token(db, user_id)
        db.flush()

        revoked = tokens.revoke_refresh_family(db, user_id)
        db.flush()

        assert revoked == 1


class TestRevocation:
    def test_logout_revokes_only_refresh_tokens(self, db, user_id):
        refresh_plain, _ = tokens.issue_refresh_token(db, user_id)
        pending_plain = tokens.issue_challenge_token(
            db, user_id, kind=TokenKind.two_factor_pending, ttl_seconds=300
        )
        db.flush()

        count = tokens.revoke_user_tokens(db, user_id, kind=TokenKind.refresh.value)
        db.flush()

        assert count == 1
        assert tokens.find_token(db, refresh_plain).revoked is True
        # The challenge token is a different kind and is left alone.
        assert tokens.find_token(db, pending_plain).revoked is False
