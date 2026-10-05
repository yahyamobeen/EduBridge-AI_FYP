"""
The parent's read-only classroom overview — classroom Phase 8 (prd.md CL-10,
tdd.md §3.6).

One call to `app.guardian_classroom_overview()` (20261005140000), which is
anchored on the caller and returns only what CL-10 allows: each VERIFIED
child, their classrooms and teachers, published assignments with deadlines,
the turn-in time (used here to derive a status, never sent), and a grade once
it is returned. Parents have no read policy on any classroom table, so there is
nothing else this module could read even by mistake.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.classroom.status import derive_status


def overview(db: Session) -> dict:
    rows = (
        db.execute(
            text(
                "SELECT o.*, now() AS db_now FROM app.guardian_classroom_overview() o "
                "ORDER BY lower(o.student_name), o.student_id, lower(o.space_title), o.space_id, "
                "         o.due_at NULLS LAST, o.assignment_id"
            )
        )
        .mappings()
        .all()
    )
    children: dict[UUID, dict[str, Any]] = {}
    for r in rows:
        child = children.setdefault(
            r["student_id"],
            {"student_id": r["student_id"], "full_name": r["student_name"], "classrooms": {}},
        )
        if r["space_id"] is None:  # a verified child in no classroom yet
            continue
        room = child["classrooms"].setdefault(
            r["space_id"],
            {
                "space_id": r["space_id"],
                "title": r["space_title"],
                "status": str(r["space_status"]),
                "subject_name": r["subject_name"],
                "teacher_name": r["teacher_name"],
                "assignments": [],
            },
        )
        if r["assignment_id"] is not None:
            room["assignments"].append(
                {
                    "id": r["assignment_id"],
                    "title": r["assignment_title"],
                    "due_at": r["due_at"],
                    "points": r["points"],
                    "status": derive_status(
                        turned_in_at=r["turned_in_at"],
                        due_at=r["due_at"],
                        returned_at=r["returned_at"],
                        now=r["db_now"],
                    ),
                    "grade": r["grade"],
                }
            )
    return {
        "children": [{**c, "classrooms": list(c["classrooms"].values())} for c in children.values()]
    }
