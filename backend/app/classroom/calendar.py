"""
The calendar — classroom Phase 5 (tdd.md §3.6, prd.md CL-9).

No table of its own and no migration: it reads the Phase 3 and Phase 4 tables
under the policies they already carry, so it shows only what the caller could
already see elsewhere — a member never receives a scheduled assignment
(`assignment_member_read`), a teacher sees only classrooms they own with live
scope, and a student who left a class stops seeing its deadlines. Archived
classrooms are left out: they are read-only and their work is finished.

Two kinds of entry:
  * `due`       — an assignment's deadline, for owner and member alike; a
                  student also gets their derived status for it;
  * `scheduled_assignment` / `scheduled_announcement` — the OWNER's own posts
                  that are not live yet, on the day they will go live.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.classroom.status import derive_status
from app.core.errors import validation_error

# A month view needs at most 42 days (six weeks); 62 leaves room for any grid
# while keeping a single request bounded.
MAX_RANGE = timedelta(days=62)
MAX_ITEMS = 500

_SQL = text(
    "SELECT 'due' AS kind, a.due_at AS at, a.space_id, sp.title AS space_title, "
    "       a.id AS ref_id, a.title, a.due_at, s.turned_in_at, g.returned_at, now() AS db_now "
    "  FROM assignment a "
    "  JOIN classroom_space sp ON sp.id = a.space_id AND sp.status = 'active' "
    "  LEFT JOIN assignment_submission s ON s.assignment_id = a.id AND s.student_id = :uid "
    "  LEFT JOIN submission_grade g ON g.assignment_id = a.id AND g.student_id = :uid "
    " WHERE a.due_at >= :start AND a.due_at < :end "
    "UNION ALL "
    "SELECT 'scheduled_assignment', a.publish_at, a.space_id, sp.title, a.id, a.title, "
    "       NULL, NULL, NULL, now() "
    "  FROM assignment a "
    "  JOIN classroom_space sp ON sp.id = a.space_id AND sp.status = 'active' "
    " WHERE a.publish_at > now() AND a.publish_at >= :start AND a.publish_at < :end "
    "   AND a.space_id IN (SELECT app.my_owned_space_ids()) "
    "UNION ALL "
    "SELECT 'scheduled_announcement', n.publish_at, n.space_id, sp.title, n.id, "
    r"       left(regexp_replace(btrim(n.body), '\s+', ' ', 'g'), 80), "
    "       NULL, NULL, NULL, now() "
    "  FROM announcement n "
    "  JOIN classroom_space sp ON sp.id = n.space_id AND sp.status = 'active' "
    " WHERE n.publish_at > now() AND n.publish_at >= :start AND n.publish_at < :end "
    "   AND n.space_id IN (SELECT app.my_owned_space_ids()) "
    " ORDER BY at, ref_id "
    " LIMIT :lim"
)


def items_between(db: Session, user_id: UUID, role: str, start: datetime, end: datetime) -> dict:
    if not (start < end <= start + MAX_RANGE):
        raise validation_error(
            message="Choose a range of at most 62 days.",
            details={"fields": {"to": "Must be after from, and at most 62 days later."}},
        )
    rows = (
        db.execute(_SQL, {"uid": user_id, "start": start, "end": end, "lim": MAX_ITEMS + 1})
        .mappings()
        .all()
    )
    # Teachers cannot enrol and students cannot own a classroom, so the role
    # says which view a `due` entry is: a student's carries their own status.
    is_student = role == "student"
    items: list[dict[str, Any]] = []
    for r in rows[:MAX_ITEMS]:
        item = {k: r[k] for k in ("kind", "at", "space_id", "space_title", "ref_id", "title")}
        if r["kind"] == "due" and is_student:
            item["my_status"] = derive_status(
                turned_in_at=r["turned_in_at"],
                due_at=r["due_at"],
                returned_at=r["returned_at"],
                now=r["db_now"],
            )
        items.append(item)
    return {"items": items, "truncated": len(rows) > MAX_ITEMS}
