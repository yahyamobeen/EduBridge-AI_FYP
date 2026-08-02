from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.auth import tokens
from app.auth.security import hash_token
from app.core.db import set_current_user_id
from app.models.enums import TokenKind


def _make_user(session, email: str) -> str:
    return str(
        session.execute(
            text(
                "INSERT INTO app_user (email, password_hash, role, full_name) "
                "VALUES (:email, 'x', 'student', 'Token Test') RETURNING id"
            ),
            {"email": email},
        ).scalar_one()
    )


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
        plain, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()
        future = datetime.now(UTC) + timedelta(days=999)
        assert tokens.rotate_refresh_token(db, plain, now=future) is None


class TestReuseDetection:
    """
    Rotation means a refresh token is valid EXACTLY ONCE, so a second use means
    two parties hold it and one is not the user. Answering 401 and stopping
    there would leave a thief who redeemed first with a working rotating chain,
    and would record nothing.
    """

    def test_replaying_a_rotated_token_raises_rather_than_returning_none(self, db, user_id):
        plain_old, _ = tokens.issue_refresh_token(db, user_id)
        db.flush()
        tokens.rotate_refresh_token(db, plain_old)
        db.flush()

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
