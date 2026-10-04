"""
Assignments, submissions and grades — classroom Phase 4 (tdd.md §3.6, prd.md CL-7).

Who may see what is decided by the policies in 20261004140000, not here:
  * a member sees an assignment only once it is published;
  * a teacher sees a student's work only while the student is an active member,
    and only once it is turned in — a draft is the student's own;
  * a student sees their own grade only once it is returned.
So the queries below are the same for every caller and the database narrows
them. This module pre-checks what makes a readable 400/403, maps each `app.*`
outcome to a catalogued error, and derives status (app/classroom/status.py).

Refusals that are a state rather than a bad field carry `details.reason`
(tdd.md §7.3): `graded` — the work is locked; `turned_in` — unsubmit first.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.classroom import file_service, storage
from app.classroom.pagination import decode_cursor, encode_cursor
from app.classroom.scheduling import check_schedule, db_now
from app.classroom.schemas import (
    AssignmentCreateRequest,
    AssignmentUpdateRequest,
    GradeRequest,
    SubmissionDraftRequest,
)
from app.classroom.service import audit, require_owner, rls_refusal_as_forbidden
from app.classroom.status import derive_status
from app.core.errors import forbidden_scope, validation_error

PAGE_SIZE = 20

# One query shape for list and detail. The submission and grade joins are on
# the CALLER: for a member they are their own row (RLS would hide anyone
# else's anyway); for the owner they match nothing. `turned_in_count` is
# filtered by RLS to active members' turned-in work.
_SELECT = (
    "SELECT a.id, a.space_id, a.title, a.instructions, a.due_at, a.points, a.publish_at, "
    "       a.publish_at > now() AS scheduled, a.created_at, a.updated_at, "
    "       c.id AS chapter_id, c.number AS chapter_number, c.title AS chapter_title, "
    "       s.body, s.link_url, s.turned_in_at, g.grade, g.feedback, g.returned_at, "
    "       now() AS db_now, "
    "       (SELECT count(*) FROM assignment_submission x "
    "         WHERE x.assignment_id = a.id AND x.turned_in_at IS NOT NULL) AS turned_in_count "
    "  FROM assignment a "
    "  LEFT JOIN chapter c ON c.id = a.chapter_id "
    "  LEFT JOIN assignment_submission s ON s.assignment_id = a.id AND s.student_id = :uid "
    "  LEFT JOIN submission_grade g ON g.assignment_id = a.id AND g.student_id = :uid "
)


def _viewer_role(db: Session, space_id: UUID) -> str:
    """'owner' or 'member'; anything else — including no such space — is the same 403."""
    row = (
        db.execute(
            text("SELECT app.owns_space(:sid) AS owner, app.is_enrolled_in(:sid) AS member"),
            {"sid": space_id},
        )
        .mappings()
        .one()
    )
    if row["owner"]:
        return "owner"
    if row["member"]:
        return "member"
    raise forbidden_scope()


def _grade(value: Any) -> float | None:
    return None if value is None else float(value)


def _my_submission(r: Any) -> dict:
    return {
        "body": r["body"] or "",
        "link_url": r["link_url"],
        "turned_in_at": r["turned_in_at"],
        "status": derive_status(
            turned_in_at=r["turned_in_at"],
            due_at=r["due_at"],
            returned_at=r["returned_at"],
            now=r["db_now"],
        ),
        # RLS returns the grade row only once it is returned.
        "grade": _grade(r["grade"]),
        "feedback": r["feedback"],
        "returned_at": r["returned_at"],
    }


def _summary(r: Any, role: str) -> dict:
    item: dict[str, Any] = {
        "id": r["id"],
        "title": r["title"],
        "due_at": r["due_at"],
        "points": r["points"],
        "chapter": (
            {"id": r["chapter_id"], "number": r["chapter_number"], "title": r["chapter_title"]}
            if r["chapter_id"] is not None
            else None
        ),
        "publish_at": r["publish_at"],
        "scheduled": r["scheduled"],
    }
    if role == "member":
        mine = _my_submission(r)
        item["my_status"] = mine["status"]
        item["my_grade"] = mine["grade"]
    else:
        item["turned_in_count"] = r["turned_in_count"]
    return item


# ── reads ───────────────────────────────────────────────────────────────────


def list_assignments(db: Session, user_id: UUID, space_id: UUID, cursor: str | None) -> dict:
    role = _viewer_role(db, space_id)
    params: dict[str, Any] = {"sid": space_id, "uid": user_id, "lim": PAGE_SIZE + 1}
    where = "a.space_id = :sid"
    if cursor:
        params["at"], params["cid"] = decode_cursor(cursor)
        where += " AND (a.publish_at, a.id) < (:at, :cid)"
    rows = (
        db.execute(
            text(
                f"{_SELECT} WHERE {where} "  # noqa: S608 -- fixed literals
                "ORDER BY a.publish_at DESC, a.id DESC LIMIT :lim"
            ),
            params,
        )
        .mappings()
        .all()
    )
    items = [_summary(r, role) for r in rows[:PAGE_SIZE]]
    has_more = len(rows) > PAGE_SIZE
    next_cursor = encode_cursor(items[-1]["publish_at"], items[-1]["id"]) if has_more else None
    return {"items": items, "next_cursor": next_cursor}


def get_assignment(db: Session, user_id: UUID, assignment_id: UUID) -> dict:
    row = (
        db.execute(
            text(f"{_SELECT} WHERE a.id = :aid"),  # noqa: S608 -- fixed literal
            {"aid": assignment_id, "uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:  # unpublished for a member, someone else's, or no such id
        raise forbidden_scope()
    role = _viewer_role(db, row["space_id"])
    detail = _summary(row, role)
    detail.update(
        space_id=row["space_id"],
        instructions=row["instructions"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        my_submission=(
            {
                **_my_submission(row),
                "files": file_service.files_for_submission(db, assignment_id, user_id),
            }
            if role == "member"
            else None
        ),
        attachments=file_service.attachments_for_assignment(db, assignment_id),
    )
    return detail


def list_chapters(db: Session, subject_id: UUID) -> dict:
    rows = (
        db.execute(
            text("SELECT id, number, title FROM chapter WHERE subject_id = :s ORDER BY number"),
            {"s": subject_id},
        )
        .mappings()
        .all()
    )
    return {"chapters": [dict(r) for r in rows]}


# ── teacher writes ──────────────────────────────────────────────────────────


def _check_chapter(db: Session, space_id: UUID, chapter_id: UUID | None) -> None:
    if chapter_id is None:
        return
    belongs = db.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM chapter c "
            "  JOIN classroom_space s ON s.subject_id = c.subject_id "
            " WHERE c.id = :ch AND s.id = :sid)"
        ),
        {"ch": chapter_id, "sid": space_id},
    ).scalar_one()
    if not belongs:
        raise validation_error(
            message="That chapter is not part of this classroom's subject.",
            details={"fields": {"chapter_id": "That chapter is not part of this subject."}},
        )


def _check_due(due_at: Any, publish_at: Any) -> None:
    if due_at is not None and due_at <= publish_at:
        raise validation_error(
            message="The due date must be after the assignment is posted.",
            details={"fields": {"due_at": "Must be after the assignment is posted."}},
        )


def create_assignment(
    db: Session, user_id: UUID, space_id: UUID, payload: AssignmentCreateRequest
) -> dict:
    require_owner(db, space_id)  # owner of a NON-archived space
    check_schedule(db, payload.publish_at)
    _check_due(payload.due_at, payload.publish_at or db_now(db))
    _check_chapter(db, space_id, payload.chapter_id)
    with rls_refusal_as_forbidden():
        new_id = db.execute(
            text(
                "INSERT INTO assignment (space_id, subject_id, author_id, title, instructions, "
                "                        due_at, points, chapter_id, publish_at) "
                "SELECT s.id, s.subject_id, :uid, :title, :instr, :due, :pts, :ch, "
                "       COALESCE(CAST(:pub AS timestamptz), now()) "
                "  FROM classroom_space s WHERE s.id = :sid "
                "RETURNING id"
            ),
            {
                "sid": space_id,
                "uid": user_id,
                "title": payload.title,
                "instr": payload.instructions,
                "due": payload.due_at,
                "pts": payload.points,
                "ch": payload.chapter_id,
                "pub": payload.publish_at,
            },
        ).scalar_one()
    return get_assignment(db, user_id, new_id)


def update_assignment(
    db: Session, user_id: UUID, assignment_id: UUID, payload: AssignmentUpdateRequest
) -> dict:
    changes = payload.changes()
    # FOR UPDATE first: a grade being saved holds FOR SHARE on this row
    # (app.save_grade), so the points check below cannot interleave with it.
    # RLS returns the row only to the author who owns the active classroom.
    current = (
        db.execute(
            text(
                "SELECT space_id, publish_at, due_at, publish_at > now() AS scheduled "
                "  FROM assignment WHERE id = :id FOR UPDATE"
            ),
            {"id": assignment_id},
        )
        .mappings()
        .one_or_none()
    )
    if current is None:
        raise forbidden_scope()

    if "publish_at" in changes:
        if not current["scheduled"]:
            raise validation_error(
                message="Only a scheduled assignment can be rescheduled.",
                details={"fields": {"publish_at": "This assignment is already posted."}},
            )
        check_schedule(db, changes["publish_at"])
    if "due_at" in changes or "publish_at" in changes:
        _check_due(
            changes.get("due_at", current["due_at"]),
            changes.get("publish_at", current["publish_at"]),
        )
    if "points" in changes:
        compatible = db.execute(
            text("SELECT app.points_compatible(:id, CAST(:pts AS smallint))"),
            {"id": assignment_id, "pts": changes["points"]},
        ).scalar_one()
        if not compatible:
            raise validation_error(
                message="Some grades are higher than these points.",
                details={"fields": {"points": "Some grades are higher than this."}},
            )
    if changes.get("chapter_id") is not None:
        _check_chapter(db, current["space_id"], changes["chapter_id"])

    # Column names come from the model's own field names, never from the client.
    sets = ", ".join(f"{name} = :{name}" for name in sorted(changes))
    with rls_refusal_as_forbidden():
        db.execute(
            text(f"UPDATE assignment SET {sets} WHERE id = :id"),  # noqa: S608 -- model field names
            {**changes, "id": assignment_id},
        )
    return get_assignment(db, user_id, assignment_id)


def delete_assignment(db: Session, user_id: UUID, assignment_id: UUID) -> None:
    row = (
        db.execute(
            text("SELECT deleted, object_keys FROM app.delete_assignment(:id)"),
            {"id": assignment_id},
        )
        .mappings()
        .one()
    )
    if not row["deleted"]:  # not the owner, archived, or no such assignment — one answer
        raise forbidden_scope()
    # Every stored object the cascade just orphaned — including files of
    # students who left, which the teacher could not even see (Phase 6).
    storage.delete_after_commit(db, list(row["object_keys"]))
    audit(db, user_id, "classroom.assignment_deleted", f"assignment/{assignment_id}")


# ── student writes ──────────────────────────────────────────────────────────


def _refuse(outcome: str) -> Exception:
    if outcome == "graded":
        return validation_error(
            message="Your teacher has graded this work, so it can no longer change.",
            details={"reason": "graded"},
        )
    if outcome == "turned_in":
        return validation_error(
            message="Unsubmit the work before editing it.", details={"reason": "turned_in"}
        )
    return forbidden_scope()  # not published, not a member, archived, or gated


def my_submission(db: Session, user_id: UUID, assignment_id: UUID) -> dict:
    row = (
        db.execute(
            text(
                "SELECT a.due_at, s.body, s.link_url, s.turned_in_at, "
                "       g.grade, g.feedback, g.returned_at, now() AS db_now "
                "  FROM assignment a "
                "  LEFT JOIN assignment_submission s "
                "         ON s.assignment_id = a.id AND s.student_id = :uid "
                "  LEFT JOIN submission_grade g ON g.assignment_id = a.id AND g.student_id = :uid "
                " WHERE a.id = :aid"
            ),
            {"aid": assignment_id, "uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise forbidden_scope()
    return {
        **_my_submission(row),
        "files": file_service.files_for_submission(db, assignment_id, user_id),
    }


def save_draft(
    db: Session, user_id: UUID, assignment_id: UUID, payload: SubmissionDraftRequest
) -> dict:
    outcome = db.execute(
        text("SELECT app.save_submission_draft(:a, :b, :l)"),
        {"a": assignment_id, "b": payload.body, "l": payload.link_url},
    ).scalar_one()
    if outcome != "saved":
        raise _refuse(outcome)
    return my_submission(db, user_id, assignment_id)


def turn_in(db: Session, user_id: UUID, assignment_id: UUID) -> dict:
    outcome = db.execute(
        text("SELECT app.turn_in_submission(:a)"), {"a": assignment_id}
    ).scalar_one()
    if outcome not in ("turned_in", "already_turned_in"):  # a repeat is not an error
        raise _refuse(outcome)
    return my_submission(db, user_id, assignment_id)


def unsubmit(db: Session, user_id: UUID, assignment_id: UUID) -> dict:
    outcome = db.execute(
        text("SELECT app.unsubmit_submission(:a)"), {"a": assignment_id}
    ).scalar_one()
    if outcome not in ("unsubmitted", "not_turned_in"):
        raise _refuse(outcome)
    return my_submission(db, user_id, assignment_id)


# ── teacher: submissions and grades ─────────────────────────────────────────

# Every ACTIVE member (app.space_people), with their turned-in work and grade
# where RLS shows one. A draft is invisible, so it reads as not turned in.
_WORK = (
    "SELECT p.user_id AS student_id, p.full_name, s.turned_in_at, s.body, s.link_url, "
    "       g.grade, g.feedback, g.returned_at, (g.student_id IS NOT NULL) AS graded, "
    "       a.due_at, now() AS db_now "
    "  FROM app.space_people(:sid) p "
    "  CROSS JOIN (SELECT due_at FROM assignment WHERE id = :aid) a "
    "  LEFT JOIN assignment_submission s "
    "         ON s.assignment_id = :aid AND s.student_id = p.user_id "
    "  LEFT JOIN submission_grade g ON g.assignment_id = :aid AND g.student_id = p.user_id "
    " WHERE NOT p.is_owner "
)


def _owned_assignment_space(db: Session, assignment_id: UUID) -> UUID:
    space_id = db.execute(
        text("SELECT space_id FROM assignment WHERE id = :a"), {"a": assignment_id}
    ).scalar_one_or_none()
    if space_id is None:
        raise forbidden_scope()
    require_owner(db, space_id, active=False)  # reading an archived classroom is fine
    return space_id


def _row(r: Any) -> dict:
    return {
        "student_id": r["student_id"],
        "full_name": r["full_name"],
        "status": derive_status(
            turned_in_at=r["turned_in_at"],
            due_at=r["due_at"],
            returned_at=r["returned_at"],
            now=r["db_now"],
        ),
        "turned_in_at": r["turned_in_at"],
        "grade": _grade(r["grade"]),
        "returned_at": r["returned_at"],
        "graded": r["graded"],
    }


def submissions_table(db: Session, assignment_id: UUID) -> dict:
    space_id = _owned_assignment_space(db, assignment_id)
    rows = (
        db.execute(
            text(f"{_WORK} ORDER BY lower(p.full_name) NULLS LAST, p.user_id"),  # noqa: S608
            {"sid": space_id, "aid": assignment_id},
        )
        .mappings()
        .all()
    )
    return {"rows": [_row(r) for r in rows]}


def student_work(db: Session, assignment_id: UUID, student_id: UUID) -> dict:
    space_id = _owned_assignment_space(db, assignment_id)
    r = (
        db.execute(
            text(f"{_WORK} AND p.user_id = :stu"),  # noqa: S608 -- fixed literals
            {"sid": space_id, "aid": assignment_id, "stu": student_id},
        )
        .mappings()
        .one_or_none()
    )
    if r is None:  # not an active member of this classroom
        raise forbidden_scope()
    return {
        **_row(r),
        "body": r["body"],
        "link_url": r["link_url"],
        "feedback": r["feedback"] or "",
        # RLS returns nothing until the work is turned in, like the body.
        "files": file_service.files_for_submission(db, assignment_id, student_id),
    }


def save_grade(
    db: Session, user_id: UUID, assignment_id: UUID, student_id: UUID, payload: GradeRequest
) -> dict:
    outcome = db.execute(
        text("SELECT app.save_grade(:a, :s, :g, :f, :r)"),
        {
            "a": assignment_id,
            "s": student_id,
            "g": payload.grade,
            "f": payload.feedback,
            "r": payload.return_to_student,
        },
    ).scalar_one()
    if outcome == "invalid_grade":
        raise validation_error(
            message="The grade must be between 0 and the assignment's points.",
            details={"fields": {"grade": "Must be between 0 and the assignment's points."}},
        )
    if outcome != "saved":
        raise forbidden_scope()
    if payload.return_to_student:
        audit(
            db,
            user_id,
            "classroom.grade_returned",
            f"assignment/{assignment_id}/student/{student_id}",
        )
    return student_work(db, assignment_id, student_id)
