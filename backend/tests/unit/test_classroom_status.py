"""
`derive_status` — the state of a student's work is computed, never stored.

The boundaries are the point: on the deadline is on time, and at the deadline
is not yet missing. Off-by-one here is what a student would dispute.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.classroom.status import derive_status

DUE = datetime(2026, 10, 10, 17, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)


def status(*, turned_in_at=None, due_at=DUE, returned_at=None, now=DUE - timedelta(days=1)):
    return derive_status(turned_in_at=turned_in_at, due_at=due_at, returned_at=returned_at, now=now)


class TestDeriveStatus:
    def test_nothing_yet_before_the_deadline_is_assigned(self):
        assert status() == "assigned"

    def test_exactly_at_the_deadline_is_not_yet_missing(self):
        assert status(now=DUE) == "assigned"

    def test_after_the_deadline_with_nothing_turned_in_is_missing(self):
        assert status(now=DUE + SECOND) == "missing"

    def test_turned_in_exactly_on_the_deadline_is_on_time(self):
        assert status(turned_in_at=DUE, now=DUE + timedelta(days=1)) == "turned_in"

    def test_turned_in_after_the_deadline_is_late(self):
        assert status(turned_in_at=DUE + SECOND, now=DUE + timedelta(days=1)) == "turned_in_late"

    def test_no_deadline_is_never_missing_or_late(self):
        far = DUE + timedelta(days=999)
        assert status(due_at=None, now=far) == "assigned"
        assert status(due_at=None, turned_in_at=far, now=far) == "turned_in"

    @pytest.mark.parametrize("turned_in_at", [None, DUE - SECOND, DUE + SECOND])
    def test_a_returned_grade_wins_over_everything(self, turned_in_at):
        # Graded missing work (a teacher's zero) is still "graded".
        assert (
            status(turned_in_at=turned_in_at, returned_at=DUE, now=DUE + timedelta(days=1))
            == "graded"
        )
