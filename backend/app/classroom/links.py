"""
Links on a student's work — classroom Phase 6b (prd.md CL-7, amended 2026-10-05).

Up to five https links per piece of work, "like Google Classroom", each its own
row in `submission_link` (20261005120000). Written only by
`app.add_submission_link` / `app.remove_submission_link` — the gate, the lock and
the graded/turned-in refusals of a submission file. Who may read a link is RLS:
the student always, the teacher once the work is turned in. A read that RLS
hides is the same 403 as an id that does not exist.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import forbidden_scope, validation_error

# Outcomes that are a state of the work, not a bad link. `graded` and
# `turned_in` match the Phase 4 submission refusals.
_STATE_MESSAGES = {
    "graded": "Your teacher has graded this work, so it can no longer change.",
    "turned_in": "Unsubmit the work before changing its links.",
    "too_many_links": "There are already as many links here as are allowed.",
}


def _refuse(outcome: str) -> Exception:
    if outcome == "invalid_url":
        # The request schema refuses these first; this is the database's backstop.
        return validation_error(
            message="Enter a full https:// link.",
            details={"fields": {"url": "must be a full https:// link"}},
        )
    if outcome in _STATE_MESSAGES:
        return validation_error(message=_STATE_MESSAGES[outcome], details={"reason": outcome})
    return forbidden_scope()


def links_for_submission(db: Session, assignment_id: UUID, student_id: UUID) -> list[dict]:
    """In the order they were added. RLS returns nothing the caller may not see."""
    rows = (
        db.execute(
            text(
                "SELECT l.id, l.url, l.created_at FROM submission_link l "
                "  JOIN assignment_submission s ON s.id = l.submission_id "
                " WHERE s.assignment_id = :a AND s.student_id = :s "
                " ORDER BY l.created_at, l.id"
            ),
            {"a": assignment_id, "s": student_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def add_link(db: Session, assignment_id: UUID, url: str) -> dict:
    row = (
        db.execute(
            text("SELECT outcome, new_link_id FROM app.add_submission_link(:a, :u)"),
            {"a": assignment_id, "u": url},
        )
        .mappings()
        .one()
    )
    if row["outcome"] != "added":
        raise _refuse(row["outcome"])
    return dict(
        db.execute(
            text("SELECT id, url, created_at FROM submission_link WHERE id = :id"),
            {"id": row["new_link_id"]},
        )
        .mappings()
        .one()
    )


def remove_link(db: Session, link_id: UUID) -> None:
    outcome = db.execute(
        text("SELECT app.remove_submission_link(:id)"), {"id": link_id}
    ).scalar_one()
    if outcome != "removed":
        raise _refuse(outcome)
