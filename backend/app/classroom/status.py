"""
The state of a student's work on an assignment — DERIVED, never stored.

A stored status column would have to be kept in step with three timestamps
owned by two different people (the student's `turned_in_at`, the teacher's
`returned_at`, and the assignment's `due_at`, which the teacher can move). It
would drift the first time a deadline was extended. Deriving it from the
timestamps on every read cannot drift.

`now` is the DATABASE clock, passed in by the caller (`SELECT now()` in the
same query), so "missing" flips at the moment PostgreSQL agrees the deadline
has passed — and so this module stays pure and testable without a database.
"""

from datetime import datetime
from typing import Literal

WorkStatus = Literal["assigned", "turned_in", "turned_in_late", "missing", "graded"]


def derive_status(
    *,
    turned_in_at: datetime | None,
    due_at: datetime | None,
    returned_at: datetime | None,
    now: datetime,
) -> WorkStatus:
    if returned_at is not None:
        return "graded"
    if turned_in_at is not None:
        # Exactly on the deadline is on time.
        return "turned_in_late" if due_at is not None and turned_in_at > due_at else "turned_in"
    # Exactly at the deadline is not yet missing.
    if due_at is not None and now > due_at:
        return "missing"
    return "assigned"
