"""
Classroom business logic — spaces, codes, membership.

Every WRITE here goes through one of the `app.*` functions from 20261004120100
or a narrowly granted column; `app_backend` has no other way in (database.md,
invariant 9). The functions RETURN an outcome rather than raising, and this
module turns each outcome into a catalogued error (tdd.md §7.3).

THE ONE RULE FOR READS: an id the caller may not see and an id that does not
exist must produce the SAME response, so existence never leaks. Both are
`forbidden_scope()`, byte for byte.

No `commit()` anywhere: the user binding is transaction-scoped, and a stray
commit would silently unbind it (backend/CLAUDE.md §3). `authenticated` commits.
"""

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.classroom.codes import generate_join_code
from app.classroom.schemas import JoinRequest, SpaceCreateRequest, SpaceUpdateRequest
from app.core.errors import forbidden_scope, gate_pending, validation_error

logger = logging.getLogger("edubridge.classroom")

# A 2^40 code space: five consecutive collisions means something other than
# chance is wrong, and a 500 is the honest answer.
_MAX_CODE_ATTEMPTS = 5

# Mirrors the cap inside app.create_space. Unarchiving goes through the column
# grant rather than a function, so without this check a teacher could create
# 50, archive them, create 50 more and unarchive everything.
_MAX_ACTIVE_CLASSROOMS = 50


# ── shared helpers ──────────────────────────────────────────────────────────


def audit(db: Session, actor_id: UUID, action: str, target: str) -> None:
    """Same shape as the `password_changed` row in auth/service.py, under the existing policy."""
    db.execute(
        text("INSERT INTO audit_log (actor_id, action, target) VALUES (:a, :act, :t)"),
        {"a": actor_id, "act": action, "t": target},
    )


@contextmanager
def rls_refusal_as_forbidden() -> Iterator[None]:
    """
    The backstop, not the check. Every write is pre-checked, so SQLSTATE 42501
    (insufficient privilege / RLS violation) here means an application check was
    MISSED and the database caught it — which is the database doing its job.
    Logged loudly, answered as 403, never as a 500.
    """
    try:
        yield
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "42501":
            logger.warning("database refused a classroom write the service had allowed")
            raise forbidden_scope() from None
        raise


def require_owner(db: Session, space_id: UUID, *, active: bool = True) -> None:
    """403 unless the caller owns the space (and, by default, it is not archived)."""
    fn = "app.owns_active_space" if active else "app.owns_space"
    allowed = db.execute(
        text(f"SELECT {fn}(:sid)"),  # noqa: S608 -- one of two fixed literals
        {"sid": space_id},
    ).scalar_one()
    if not allowed:
        raise forbidden_scope()


def _summary(row: Mapping[str, Any]) -> dict:
    return {
        "id": row["space_id"],
        "title": row["title"],
        "status": str(row["status"]),
        "subject": {
            "id": row["subject_id"],
            "name": row["subject_name"],
            "board": str(row["board"]),
            "class_level": row["class_level"],
        },
        "owner_name": row["owner_name"],
        "viewer_role": row["viewer_role"],
        "can_manage": row["can_manage"],
        "member_count": row["member_count"],
        "joined_at": row["joined_at"],
    }


# ── spaces ──────────────────────────────────────────────────────────────────


def list_spaces(db: Session) -> dict:
    rows = (
        db.execute(text("SELECT * FROM app.my_spaces() ORDER BY status, lower(title)"))
        .mappings()
        .all()
    )
    return {"spaces": [_summary(r) for r in rows]}


def get_space(db: Session, space_id: UUID) -> dict:
    row = (
        db.execute(text("SELECT * FROM app.my_spaces() WHERE space_id = :sid"), {"sid": space_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise forbidden_scope()
    detail = _summary(row)
    # `join_code_owner_read` returns the row only to a scoped owner. A member,
    # or an owner whose scope was revoked, gets None from the database itself.
    detail["join_code"] = db.execute(
        text("SELECT code FROM join_code WHERE space_id = :sid AND revoked = false"),
        {"sid": space_id},
    ).scalar_one_or_none()
    return detail


def _rotate(db: Session, space_id: UUID) -> str:
    for _ in range(_MAX_CODE_ATTEMPTS):
        row = (
            db.execute(
                text("SELECT outcome, new_code FROM app.rotate_join_code(:sid, :code)"),
                {"sid": space_id, "code": generate_join_code()},
            )
            .mappings()
            .one()
        )
        if row["outcome"] == "rotated":
            return row["new_code"]
        if row["outcome"] == "forbidden":
            raise forbidden_scope()
    raise RuntimeError("join code generation collided repeatedly")


def create_space(db: Session, user_id: UUID, payload: SpaceCreateRequest) -> dict:
    row = (
        db.execute(
            text("SELECT outcome, new_space_id FROM app.create_space(:title, :subject)"),
            {"title": payload.title, "subject": payload.subject_id},
        )
        .mappings()
        .one()
    )
    outcome = row["outcome"]
    if outcome == "unknown_subject":
        raise validation_error(
            message="Unknown subject.", details={"fields": {"subject_id": "Unknown subject."}}
        )
    if outcome == "classroom_limit":
        raise validation_error(
            message="You have reached the limit of active classrooms. Archive one first.",
            details={"reason": "classroom_limit"},
        )
    if outcome != "created":  # not_teacher | scope_revoked
        raise forbidden_scope()

    space_id = row["new_space_id"]
    _rotate(db, space_id)
    audit(db, user_id, "classroom.created", f"classroom_space/{space_id}")
    return get_space(db, space_id)


def update_space(db: Session, space_id: UUID, payload: SpaceUpdateRequest) -> dict:
    payload.validate_at_least_one_field()
    # Not `active=True`: unarchiving must work on an archived space.
    require_owner(db, space_id, active=False)

    if payload.status == "active":
        current = db.execute(
            text("SELECT status FROM classroom_space WHERE id = :sid"), {"sid": space_id}
        ).scalar_one()
        if str(current) == "archived":
            active_count = db.execute(
                text(
                    "SELECT count(*) FROM classroom_space "
                    "WHERE owner_id = app.current_user_id() AND status = 'active'"
                )
            ).scalar_one()
            if active_count >= _MAX_ACTIVE_CLASSROOMS:
                raise validation_error(
                    message="You have reached the limit of active classrooms. Archive one first.",
                    details={"reason": "classroom_limit"},
                )

    sets, params = [], {"sid": space_id}
    if payload.title is not None:
        sets.append("title = :title")
        params["title"] = payload.title
    if payload.status is not None:
        sets.append("status = CAST(:status AS space_status)")
        params["status"] = payload.status.value
    with rls_refusal_as_forbidden():
        db.execute(
            text(f"UPDATE classroom_space SET {', '.join(sets)} WHERE id = :sid"),  # noqa: S608 -- fixed literals
            params,
        )
    return get_space(db, space_id)


def change_join_code(db: Session, user_id: UUID, space_id: UUID, action: str) -> dict:
    if action == "rotate":
        code: str | None = _rotate(db, space_id)
    else:
        disabled = db.execute(
            text("SELECT app.disable_join_code(:sid)"), {"sid": space_id}
        ).scalar_one()
        if not disabled:
            raise forbidden_scope()
        code = None
    audit(db, user_id, f"classroom.code_{action}d", f"classroom_space/{space_id}")
    return {"join_code": code}


# ── membership ──────────────────────────────────────────────────────────────


def join_space(db: Session, payload: JoinRequest) -> dict:
    row = (
        db.execute(text("SELECT * FROM app.join_space_by_code(:code)"), {"code": payload.code})
        .mappings()
        .one()
    )
    outcome = row["outcome"]
    if outcome in ("joined", "already_member"):
        return {"space_id": row["joined_space_id"], "already_member": outcome == "already_member"}
    if outcome == "gate_pending":
        raise gate_pending()
    if outcome == "class_mismatch":
        # The student holds the code, so naming the class is not a leak — and it
        # is the only way they can understand the refusal.
        raise validation_error(
            message="This classroom is for a different class.",
            details={
                "reason": "class_mismatch",
                "space": {
                    "title": row["space_title"],
                    "subject_name": row["space_subject"],
                    "board": str(row["space_board"]),
                    "class_level": row["space_class_level"],
                },
            },
        )
    if outcome == "classroom_full":
        raise validation_error(
            message="This classroom is full.", details={"reason": "classroom_full"}
        )
    if outcome == "not_student":
        raise forbidden_scope()
    # invalid_code — also an unknown, revoked, expired or archived code, and a
    # REMOVED student: deliberately indistinguishable.
    raise validation_error(
        message="That class code is not valid.",
        details={"reason": "invalid_code", "fields": {"code": "That class code is not valid."}},
    )


def leave_space(db: Session, space_id: UUID) -> None:
    # Idempotent and silent: the same 204 whether or not the caller was a
    # member, so this endpoint cannot be used to probe which spaces exist.
    db.execute(text("SELECT app.leave_space(:sid)"), {"sid": space_id})


def people(db: Session, space_id: UUID) -> dict:
    rows = (
        db.execute(text("SELECT * FROM app.space_people(:sid)"), {"sid": space_id}).mappings().all()
    )
    owner = next((r for r in rows if r["is_owner"]), None)
    if owner is None:  # not a member, not the owner, or no such space
        raise forbidden_scope()
    members = sorted(
        (
            {
                "user_id": r["user_id"],
                "full_name": r["full_name"],
                "joined_at": r["joined_at"],
                "muted": r["muted"],
            }
            for r in rows
            if not r["is_owner"]
        ),
        key=lambda m: (m["full_name"] or "").casefold(),
    )
    return {
        "owner": {"user_id": owner["user_id"], "full_name": owner["full_name"]},
        "members": members,
    }


def remove_student(db: Session, user_id: UUID, space_id: UUID, student_id: UUID) -> None:
    removed = db.execute(
        text("SELECT app.remove_student(:sid, :stu)"), {"sid": space_id, "stu": student_id}
    ).scalar_one()
    if not removed:
        raise forbidden_scope()
    audit(
        db, user_id, "classroom.student_removed", f"classroom_space/{space_id}/student/{student_id}"
    )


# ── reference ───────────────────────────────────────────────────────────────


def list_subjects(db: Session, board: str, class_level: int) -> dict:
    rows = (
        db.execute(
            text(
                "SELECT s.id, s.name, "
                "       COALESCE(array_agg(sg.student_group::text ORDER BY sg.student_group) "
                "                FILTER (WHERE sg.student_group IS NOT NULL), '{}') AS groups "
                "  FROM subject s "
                "  JOIN class_level cl ON cl.id = s.class_level_id "
                "  JOIN board b ON b.id = cl.board_id "
                "  LEFT JOIN subject_group sg ON sg.subject_id = s.id "
                " WHERE b.code = CAST(:board AS board_code) AND cl.level = :lvl "
                " GROUP BY s.id, s.name ORDER BY s.name"
            ),
            {"board": board, "lvl": class_level},
        )
        .mappings()
        .all()
    )
    return {
        "subjects": [{"id": r["id"], "name": r["name"], "groups": list(r["groups"])} for r in rows]
    }
