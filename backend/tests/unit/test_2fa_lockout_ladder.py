"""
The 2FA lockout ladder (tdd.md §6.9 D7). Pure arithmetic, no database.

The ladder used to be written out inline inside `/2fa/verify` and NOT AT ALL
inside `/2fa/confirm` — so a six-digit code was rate-limited during a challenge
and unlimited during enrolment. These assert the shared helper both now use.
"""

from datetime import UTC, datetime

from app.auth.service import _lockout_after
from app.core.config import get_settings


class TestLockoutLadder:
    def test_no_lockout_below_the_first_threshold(self):
        assert _lockout_after(0) is None
        assert _lockout_after(1) is None
        assert _lockout_after(2) is None

    def test_the_first_threshold_locks(self):
        assert _lockout_after(3) is not None

    def test_the_penalty_escalates(self):
        """The HIGHEST threshold met wins, so repeat offenders wait longer."""
        before = datetime.now(UTC)
        short = _lockout_after(3)
        medium = _lockout_after(6)
        long = _lockout_after(10)

        assert short is not None and medium is not None and long is not None
        assert (short - before) < (medium - before) < (long - before)

    def test_attempts_between_thresholds_keep_the_lower_penalty(self):
        """4 and 5 have not earned the 6-failure penalty yet."""
        four, five, six = _lockout_after(4), _lockout_after(5), _lockout_after(6)
        assert four is not None and five is not None and six is not None
        assert (six - four).total_seconds() > 0

    def test_the_lockout_is_in_the_future(self):
        # `locked_until` is returned to the client, which counts down from it.
        # A timestamp in the past would render as an expired lock that never
        # actually held.
        assert _lockout_after(3) > datetime.now(UTC)

    def test_it_reads_the_configured_ladder_rather_than_a_literal(self):
        thresholds = get_settings().two_factor_lockout_thresholds
        assert thresholds, "the ladder must not be empty; that would disable lockout entirely"
        lowest = min(t for t, _ in thresholds)
        assert _lockout_after(lowest - 1) is None
        assert _lockout_after(lowest) is not None
