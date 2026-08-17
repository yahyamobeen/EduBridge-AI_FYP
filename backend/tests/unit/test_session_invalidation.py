"""
`session_is_invalidated` — the comparison behind Phase 4's session policy.

⚠️ THIS EXISTS BECAUSE THE SAME PROPERTY, TESTED THROUGH THE STACK, FAILED FOUR
   TIMES FOR FOUR REASONS THAT HAD NOTHING TO DO WITH IT.

The integration version slept until real time passed the invalidation stamp and
then minted a token. Every failure came from something it was not trying to
test: skew between the application and database clocks (measured at 1.1s, in the
direction that let an invalidated token survive), the flooring of a JWT `iat` to
a whole second, and how much CPU the rest of the suite was using.

"Invalidation must not become a permanent ban" is a property of one pure
function. Feeding it explicit instants states it exactly, in microseconds, with
no clock to race — and covers boundaries a sleeping test could never hit
reliably.

The direction that MATTERS for security — a token issued before the stamp must
be refused — is still asserted end to end in
`tests/integration/test_session_policy.py`, because that one genuinely needs the
whole stack.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.security import session_is_invalidated
from app.core.config import get_settings

STAMP = datetime(2026, 8, 17, 12, 0, 0, 500_000, tzinfo=UTC)


@pytest.fixture
def allowance() -> int:
    return get_settings().session_invalidation_skew_seconds


class TestNoEventMeansNoInvalidation:
    def test_a_null_stamp_never_invalidates(self):
        """
        ⚠️ TRAP 3, AND IT 401s EVERY REQUEST FOR EVERY USER.

        `sessions_invalidated_at` is NULL until a user's first event, which is
        almost everybody. Anything that treats NULL as "invalidate" — including
        expressing this as a SQL `WHERE` clause, where the comparison yields
        NULL and filters the row out — signs the entire user base out.
        """
        assert session_is_invalidated(datetime.now(UTC), None) is False
        assert session_is_invalidated(datetime(2000, 1, 1, tzinfo=UTC), None) is False


class TestTokensIssuedBeforeTheStamp:
    @pytest.mark.parametrize(
        "before",
        [
            timedelta(days=365),
            timedelta(hours=1),
            timedelta(seconds=30),
            timedelta(seconds=1),
        ],
        ids=["a year", "an hour", "30s", "1s"],
    )
    def test_they_are_refused(self, before):
        assert session_is_invalidated(STAMP - before, STAMP) is True

    def test_the_truncation_boundary_fails_closed(self):
        """
        ⚠️ THE CASE A STRICT `<` GETS WRONG, AND IT FAILS OPEN.

        A JWT `iat` is an integer, so a token minted at 12:00:00.7 carries
        `iat = 12:00:00`. Against a stamp of 12:00:00.5 it plainly predates the
        invalidation and must die — but `12:00:00 < 12:00:00` (the truncated
        cutoff) is False, so a strict comparison lets it live.

        `<=` inverts the error to the safe side. That is the whole reason the
        operator is what it is.
        """
        floored = STAMP.replace(microsecond=0)
        assert session_is_invalidated(floored, STAMP) is True


class TestTokensIssuedAfterTheStamp:
    """
    The inverse guard: invalidation ends sessions, it does not ban an account.
    """

    def test_a_token_well_past_the_allowance_survives(self, allowance):
        later = STAMP.replace(microsecond=0) + timedelta(seconds=allowance + 1)
        assert session_is_invalidated(later, STAMP) is False

    def test_a_token_minted_much_later_survives(self, allowance):
        assert session_is_invalidated(STAMP + timedelta(hours=1), STAMP) is False

    def test_a_user_can_sign_in_again_immediately_after_a_password_change(self, allowance):
        """
        The behaviour a real user sees. Anything that refuses tokens for ever
        after one invalidation locks the account out permanently, and a password
        change is exactly when that must not happen.
        """
        signs_in_at = STAMP + timedelta(seconds=allowance + 2)
        assert session_is_invalidated(signs_in_at, STAMP) is False


class TestTheSkewAllowance:
    """
    ⚠️ THE ALLOWANCE IS WHY THIS CHECK WORKS AT ALL, AND IT COSTS SOMETHING.

    `iat` is minted by Python on the application host; the stamp is
    `clock_timestamp()` on the database host. Measured against the live project:
    a token created BEFORE a password change carried `iat = 20:03:43` while the
    stamp written afterwards read `20:03:41.88` — the database ran 1.1s behind,
    so the token looked as though it had been issued after its own invalidation
    and sailed through. Nothing failed; the feature was simply inert.
    """

    def test_it_absorbs_a_database_clock_running_behind(self, allowance):
        # The exact shape that shipped broken: the token predates the stamp in
        # wall-clock terms, but the stamp READS earlier because of skew.
        skewed_stamp = STAMP - timedelta(seconds=1.1)
        assert session_is_invalidated(STAMP, skewed_stamp) is True

    def test_it_fails_closed_inside_the_window(self, allowance):
        """
        The price, asserted rather than hoped for: a token issued shortly AFTER
        an invalidation is also refused. One extra sign-in, on a flow no human
        completes in under a second, in exchange for an invalidation that works.
        """
        just_after = STAMP.replace(microsecond=0) + timedelta(seconds=allowance - 1)
        assert session_is_invalidated(just_after, STAMP) is True

    def test_the_window_is_bounded(self, allowance):
        """It must not be so wide that invalidation becomes a long ban."""
        assert 0 < allowance <= 60
