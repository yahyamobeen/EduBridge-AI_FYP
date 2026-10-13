"""
The class chat — classroom Phase 7 (prd.md CL-5, tdd.md §3.6).

Class-public by design: every message is visible to the whole class, and there
is no private messaging. Who may post is the INSERT policy on `space_message`
(20261005130000, through `app.can_post_message`); this module asks the same
function first so a refusal is a reason the student can act on —
`details.reason ∈ {archived, muted, chat_locked}` — rather than a database
error. Moderation (delete, mute) goes through `app.*` functions only.

Polling, not a socket: the poll's cursor is the DATABASE clock (`now()` of the
reading transaction), never Python's, and each catch-up re-reads an OVERLAP
window, because the order in which messages are inserted is not the order in
which their transactions commit. The client de-duplicates by id. Messages
deleted since the last poll come back as ids only (`deleted_ids`), because a
member cannot read a deleted row at all. SSE or WebSockets, and a shared
rate-limit store, are the scale-out path (tdd.md §3.6).

The same byte-identical 403 for a classroom that does not exist and one the
caller is not part of, as everywhere in this package.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.classroom.pagination import decode_cursor, encode_cursor
from app.classroom.service import audit, rls_refusal_as_forbidden
from app.core.errors import forbidden_scope, validation_error

PAGE_SIZE = 50
# A catch-up poll this far behind starts again from the newest page instead
# (`reset`), so a long-hidden tab never shows the oldest of what it missed and
# skips the newest.
CATCH_UP_LIMIT = 200
# Insert order is not commit order: a message inserted just before a poll read
# the clock can commit just after. Every catch-up re-reads this window.
OVERLAP = timedelta(seconds=15)

_COLUMNS = "id, author_id, body, created_at, deleted_at IS NOT NULL AS deleted"

_REFUSALS = {
    "archived": "This classroom is archived, so its chat is read-only.",
    "muted": "Your teacher has turned off your messages in this chat.",
    "chat_locked": "Your teacher has locked the chat.",
}


def _state(db: Session, space_id: UUID) -> Mapping[str, Any]:
    """The caller's place in the chat, in one round trip; 403 for anyone outside it."""
    row = (
        db.execute(
            text(
                "SELECT s.status, s.chat_locked, now() AS server_time, "
                "       app.owns_space(s.id) AS owner, app.is_enrolled_in(s.id) AS member, "
                "       app.can_post_message(s.id) AS can_post, "
                "       EXISTS (SELECT 1 FROM enrollment e "
                "                WHERE e.space_id = s.id AND e.student_id = app.current_user_id() "
                "                  AND e.left_at IS NULL AND e.muted_at IS NOT NULL) AS muted "
                "  FROM classroom_space s WHERE s.id = :sid"
            ),
            {"sid": space_id},
        )
        .mappings()
        .one_or_none()
    )
    # A teacher whose subject scope was revoked still SEES the classroom row
    # (space_visible), but owns_space is false: outside the chat, like anyone.
    if row is None or not (row["owner"] or row["member"]):
        raise forbidden_scope()
    return row


def _newest(db: Session, space_id: UUID, before: str | None) -> tuple[list[dict], str | None]:
    """A page of PAGE_SIZE, read newest first and returned oldest first."""
    params: dict[str, Any] = {"sid": space_id, "lim": PAGE_SIZE + 1}
    where = "space_id = :sid"
    if before:
        params["at"], params["mid"] = decode_cursor(before)
        where += " AND (created_at, id) < (:at, :mid)"
    rows = (
        db.execute(
            text(
                f"SELECT {_COLUMNS} FROM space_message WHERE {where} "  # noqa: S608 -- fixed literals
                "ORDER BY created_at DESC, id DESC LIMIT :lim"
            ),
            params,
        )
        .mappings()
        .all()
    )
    page = [dict(r) for r in reversed(rows[:PAGE_SIZE])]
    older = encode_cursor(page[0]["created_at"], page[0]["id"]) if len(rows) > PAGE_SIZE else None
    return page, older


def poll(db: Session, space_id: UUID, after: datetime | None, before: str | None) -> dict:
    if after is not None and before is not None:
        raise validation_error(
            message="Send either after or before, not both.",
            details={"fields": {"before": "Send either after or before, not both."}},
        )
    state = _state(db, space_id)
    messages: list[dict] = []
    deleted_ids: list[UUID] = []
    older: str | None = None
    reset = False

    if after is not None:
        since = after - OVERLAP
        rows = (
            db.execute(
                text(
                    f"SELECT {_COLUMNS} FROM space_message "  # noqa: S608 -- fixed literals
                    "WHERE space_id = :sid AND created_at > :since "
                    "ORDER BY created_at, id LIMIT :lim"
                ),
                {"sid": space_id, "since": since, "lim": CATCH_UP_LIMIT + 1},
            )
            .mappings()
            .all()
        )
        if len(rows) > CATCH_UP_LIMIT:
            reset = True
        else:
            messages = [dict(r) for r in rows]
            deleted_ids = list(
                db.execute(
                    text("SELECT message_id FROM app.space_message_tombstones(:sid, :since)"),
                    {"sid": space_id, "since": since},
                ).scalars()
            )
    if after is None or reset:
        messages, older = _newest(db, space_id, before)

    return {
        "messages": messages,
        "deleted_ids": deleted_ids,
        "older_cursor": older,
        "server_time": state["server_time"],
        "reset": reset,
        "chat_locked": state["chat_locked"],
        "can_post": state["can_post"],
        "muted": state["muted"],
    }


def post(db: Session, user_id: UUID, space_id: UUID, body: str) -> dict:
    state = _state(db, space_id)
    if not state["can_post"]:
        if str(state["status"]) != "active":
            reason = "archived"
        elif state["muted"]:
            reason = "muted"
        elif state["chat_locked"]:
            reason = "chat_locked"
        else:
            raise forbidden_scope()
        raise validation_error(message=_REFUSALS[reason], details={"reason": reason})
    with rls_refusal_as_forbidden():
        row = (
            db.execute(
                text(
                    "INSERT INTO space_message (space_id, author_id, body) "  # noqa: S608 -- fixed literals
                    "VALUES (:sid, :uid, :body) "
                    f"RETURNING {_COLUMNS}"
                ),
                {"sid": space_id, "uid": user_id, "body": body},
            )
            .mappings()
            .one()
        )
    return dict(row)


def delete(db: Session, user_id: UUID, message_id: UUID) -> None:
    """Soft, retained, and idempotent: deleting twice is one deletion and one audit row."""
    outcome = db.execute(
        text("SELECT app.delete_space_message(:m)"), {"m": message_id}
    ).scalar_one()
    if outcome == "forbidden":
        raise forbidden_scope()
    if outcome == "deleted":
        audit(db, user_id, "classroom.message_deleted", f"space_message/{message_id}")


def set_muted(db: Session, user_id: UUID, space_id: UUID, student_id: UUID, muted: bool) -> None:
    changed = db.execute(
        text("SELECT app.set_student_muted(:sid, :stu, :m)"),
        {"sid": space_id, "stu": student_id, "m": muted},
    ).scalar_one()
    if not changed:
        raise forbidden_scope()
    action = "classroom.student_muted" if muted else "classroom.student_unmuted"
    audit(db, user_id, action, f"classroom_space/{space_id}/student/{student_id}")
