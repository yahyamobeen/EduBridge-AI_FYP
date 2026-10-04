"""
Announcements — the classroom stream (classroom Phase 3, tdd.md §3.6).

Who may write is enforced by the policies in 20261004130000: the author must be
the caller and must own the (non-archived) space. Who may READ a scheduled post
is enforced there too — a member's query simply never returns it. This module
pre-checks so a refusal is a readable 403/400 rather than a database error, and
keeps the one rule the database cannot express: a post already published cannot
be moved back into the future (that would hide what students have already seen).

Times are compared against the DATABASE clock, never Python's — Phase 4
measured the two 1.1 s apart, and a "future" check against the wrong clock is
exactly the boundary that drifts.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.classroom.pagination import decode_cursor, encode_cursor
from app.classroom.schemas import AnnouncementCreateRequest, AnnouncementUpdateRequest
from app.classroom.service import audit, require_owner, rls_refusal_as_forbidden
from app.core.errors import forbidden_scope, validation_error

PAGE_SIZE = 20
_MAX_SCHEDULE_AHEAD = timedelta(days=365)
_COLUMNS = (
    "id, body, author_id, publish_at, publish_at > now() AS scheduled, created_at, updated_at"
)


def _require_participant(db: Session, space_id: UUID) -> None:
    """Owner or active member; anything else — including no such space — is the same 403."""
    row = (
        db.execute(
            text("SELECT app.owns_space(:sid) AS owner, app.is_enrolled_in(:sid) AS member"),
            {"sid": space_id},
        )
        .mappings()
        .one()
    )
    if not (row["owner"] or row["member"]):
        raise forbidden_scope()


def _check_schedule(db: Session, publish_at: datetime | None) -> None:
    if publish_at is None:
        return
    db_now = db.execute(text("SELECT now()")).scalar_one()
    if publish_at <= db_now or publish_at > db_now + _MAX_SCHEDULE_AHEAD:
        raise validation_error(
            message="Choose a future time within the next year.",
            details={"fields": {"publish_at": "Choose a future time within the next year."}},
        )


def list_announcements(db: Session, space_id: UUID, cursor: str | None) -> dict:
    _require_participant(db, space_id)
    params: dict[str, Any] = {"sid": space_id, "lim": PAGE_SIZE + 1}
    where = "space_id = :sid"
    if cursor:
        params["at"], params["cid"] = decode_cursor(cursor)
        where += " AND (publish_at, id) < (:at, :cid)"
    rows = (
        db.execute(
            text(
                f"SELECT {_COLUMNS} FROM announcement WHERE {where} "  # noqa: S608 -- fixed literals
                "ORDER BY publish_at DESC, id DESC LIMIT :lim"
            ),
            params,
        )
        .mappings()
        .all()
    )
    # Row-Level Security has already removed scheduled posts from a member's
    # result, so this is the same query for both roles.
    items = [dict(r) for r in rows[:PAGE_SIZE]]
    has_more = len(rows) > PAGE_SIZE
    next_cursor = encode_cursor(items[-1]["publish_at"], items[-1]["id"]) if has_more else None
    return {"items": items, "next_cursor": next_cursor}


def create_announcement(
    db: Session, user_id: UUID, space_id: UUID, payload: AnnouncementCreateRequest
) -> dict:
    require_owner(db, space_id)  # owner of a NON-archived space
    _check_schedule(db, payload.publish_at)
    with rls_refusal_as_forbidden():
        row = (
            db.execute(
                text(
                    "INSERT INTO announcement (space_id, author_id, body, publish_at) "  # noqa: S608 -- fixed literal column list
                    "VALUES (:sid, :uid, :body, COALESCE(CAST(:pub AS timestamptz), now())) "
                    f"RETURNING {_COLUMNS}"
                ),
                {"sid": space_id, "uid": user_id, "body": payload.body, "pub": payload.publish_at},
            )
            .mappings()
            .one()
        )
    return dict(row)


def update_announcement(
    db: Session, announcement_id: UUID, payload: AnnouncementUpdateRequest
) -> dict:
    payload.validate_at_least_one_field()
    current = (
        db.execute(
            text(
                "SELECT space_id, publish_at > now() AS scheduled FROM announcement WHERE id = :id"
            ),
            {"id": announcement_id},
        )
        .mappings()
        .one_or_none()
    )
    if current is None:  # not visible to the caller, or does not exist
        raise forbidden_scope()
    require_owner(db, current["space_id"])

    if payload.publish_at is not None:
        if not current["scheduled"]:
            raise validation_error(
                message="Only a scheduled post can be rescheduled.",
                details={"fields": {"publish_at": "This post is already published."}},
            )
        _check_schedule(db, payload.publish_at)

    sets, params = [], {"id": announcement_id}
    if payload.body is not None:
        sets.append("body = :body")
        params["body"] = payload.body
    if payload.publish_at is not None:
        sets.append("publish_at = :pub")
        params["pub"] = payload.publish_at
    with rls_refusal_as_forbidden():
        row = (
            db.execute(
                text(
                    f"UPDATE announcement SET {', '.join(sets)} "  # noqa: S608 -- fixed literals
                    f"WHERE id = :id RETURNING {_COLUMNS}"
                ),
                params,
            )
            .mappings()
            .one_or_none()
        )
    if row is None:  # authored by someone else: the policy matched no row
        raise forbidden_scope()
    return dict(row)


def delete_announcement(db: Session, user_id: UUID, announcement_id: UUID) -> None:
    with rls_refusal_as_forbidden():
        space_id = db.execute(
            text("DELETE FROM announcement WHERE id = :id RETURNING space_id"),
            {"id": announcement_id},
        ).scalar_one_or_none()
    if space_id is None:  # not the author, archived, or no such post — one answer
        raise forbidden_scope()
    audit(
        db,
        user_id,
        "classroom.announcement_deleted",
        f"classroom_space/{space_id}/announcement/{announcement_id}",
    )
