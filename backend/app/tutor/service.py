"""Tutor chat persistence (tdd.md §3.2a, §5.3f).

Every statement here runs on `ctx.session`, which is already bound to the acting user,
so Row-Level Security is what enforces ownership - not a `WHERE student_id = :me` that a
future caller could forget. `chat_session_owner`, `message_owner` and `visual_aid_owner`
are each a single `FOR ALL` policy keyed on `app.current_user_id()`, and chat content has
no teacher, parent or admin read path at all (prd.md §4.2, TEL-3).

⚠️ NOTHING HERE COMMITS. `set_current_user_id()` uses `set_config(..., is_local => true)`,
which is transaction-scoped: a `commit()` mid-request ends that transaction and silently
discards the binding, after which every subsequent query returns zero rows with no error
raised anywhere. `get_db` commits once, after the handler returns (backend/CLAUDE.md §3).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import forbidden_scope
from app.retrieval.physics9.base import Timings, page_url

logger = logging.getLogger("edubridge.tutor.service")

# How many prior turns are replayed to the generator. Bounded on purpose: an unbounded
# window grows the prompt without limit and, with a hosted generator, grows the exposure
# with it (tdd.md §4.1, deviation V3).
HISTORY_TURNS = 4

# `message_role` is ('student','assistant','system') -- the first label is `student`,
# NOT `user`. The API speaks `user` because that is what every chat client and every
# generation API calls it. Mapped here, at the boundary, rather than migrating an enum
# that three other planned consumers already read.
_ROLE_TO_DB = {"user": "student", "assistant": "assistant", "system": "system"}
_ROLE_FROM_DB = {"student": "user", "assistant": "assistant", "system": "system"}


def open_or_resume_session(
    db: Session,
    student_id: UUID,
    session_id: UUID | None,
    *,
    subject: str | None = None,
    class_level: int | None = None,
    chapter: int | None = None,
) -> tuple[UUID, int | None]:
    """Return `(session_id, anchor_chapter)`, creating the session when needed.

    The anchor is set once, when the session is opened, and is NOT overwritten on
    resume: a student who opened a session from chapter 7 and then asks about chapter 2
    has asked a prerequisite question, which the prior is meant to survive - silently
    re-anchoring to wherever the last question landed would make the anchor follow the
    student around instead of holding the session's subject.
    """
    if session_id is not None:
        row = (
            db.execute(
                text("SELECT id, chapter FROM chat_session WHERE id = :sid"),
                {"sid": session_id},
            )
            .mappings()
            .one_or_none()
        )
        # RLS already filtered this, so an invisible row and an absent row are
        # indistinguishable here - which is the point. Answering differently for
        # "someone else's session" than for "no such session" would confirm that a
        # given id exists, and the error catalogue has no 404 to reach for anyway.
        if row is None:
            raise forbidden_scope("That chat session is not available.")
        return row["id"], row["chapter"]

    created = (
        db.execute(
            text(
                "INSERT INTO chat_session (student_id, subject, class_level, chapter) "
                "VALUES (:student_id, :subject, :class_level, :chapter) "
                "RETURNING id, chapter"
            ),
            {
                "student_id": student_id,
                "subject": subject,
                "class_level": class_level,
                "chapter": chapter,
            },
        )
        .mappings()
        .one()
    )
    return created["id"], created["chapter"]


def append_message(
    db: Session,
    session_id: UUID,
    role: str,
    content: str,
    pages: list[dict[str, Any]] | None = None,
) -> UUID:
    """Persist one turn, with its cited pages when it has any.

    Citations go in a `visual_aid` row with `kind='figure'` rather than in
    `message.slo_refs`, which references `slo` rows that do not exist - the whole
    knowledge-base layer is deferred. `slo_refs` therefore stays NULL and unmisused.
    """
    message_id = (
        db.execute(
            text(
                "INSERT INTO message (session_id, role, content) "
                "VALUES (:session_id, :role, :content) RETURNING id"
            ),
            {
                "session_id": session_id,
                "role": _ROLE_TO_DB[role],
                "content": content,
            },
        )
        .scalars()
        .one()
    )

    if pages:
        db.execute(
            text(
                "INSERT INTO visual_aid (message_id, kind, payload) "
                "VALUES (:message_id, 'figure', CAST(:payload AS jsonb))"
            ),
            {
                "message_id": message_id,
                # Only the fields a client needs to render a citation. The MaxSim score
                # is kept because it is the only confidence signal the retriever offers,
                # and `retriever` is kept because a degraded answer must stay visibly
                # degraded after a reload, not just in the response that produced it.
                "payload": json.dumps(
                    {
                        "pages": [
                            {
                                "page": hit["page"],
                                "chapter": hit.get("chapter"),
                                "score": hit.get("score"),
                            }
                            for hit in pages
                        ]
                    }
                ),
            },
        )

    return message_id


def recent_history(
    db: Session, session_id: UUID, turns: int = HISTORY_TURNS
) -> list[dict[str, str]]:
    """The last `turns` messages, oldest first, for replay to the generator.

    ⚠️ Returns ONLY `role` and `content`. No ids, no timestamps, no student reference -
    this is the value that leaves the platform for a third-party generator, and deviation
    V3 turns on it carrying nothing that ties a prompt to a child (tdd.md §14.2).
    """
    rows = (
        db.execute(
            text(
                "SELECT role, content FROM message WHERE session_id = :sid "
                "ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"sid": session_id, "limit": turns},
        )
        .mappings()
        .all()
    )
    return [
        {"role": _ROLE_FROM_DB[row["role"]], "content": row["content"]} for row in reversed(rows)
    ]


def last_turn_pages(db: Session, session_id: UUID) -> list[dict[str, Any]]:
    """The pages the previous answer cited, or `[]`.

    What a follow-up reuses instead of retrieving again (`app.tutor.turns`). Reusing
    them is not only cheaper - it is more correct. Re-retrieving on "explain that again"
    can return a DIFFERENT page set, and the tutor then explains something adjacent to
    what the student is actually looking at, appearing to contradict itself.

    `url` is rebuilt rather than stored: a stored URL is a route shape frozen into the
    database, and it would be wrong the day the route moves.
    """
    row = (
        db.execute(
            text(
                "SELECT v.payload FROM visual_aid v "
                "JOIN message m ON m.id = v.message_id "
                "WHERE m.session_id = :sid AND m.role = 'assistant' AND v.kind = 'figure' "
                "ORDER BY m.created_at DESC, m.id DESC LIMIT 1"
            ),
            {"sid": session_id},
        )
        .scalars()
        .one_or_none()
    )
    if not row:
        return []
    return [
        {
            "page": page["page"],
            "chapter": page.get("chapter"),
            "score": page.get("score"),
            "url": page_url(page["page"]),
        }
        for page in (row or {}).get("pages", [])
    ]


def retrieve_for_turn(
    db: Session,
    session_id: UUID,
    question: str,
    *,
    anchor: int | None = None,
    top_k: int = 3,
    has_prior_turn: bool = False,
) -> tuple[list[dict[str, Any]], Timings, str, str]:
    """Route the turn, then retrieve. Returns `(hits, timings, tier, intent)`.

    One place, used by both the streaming and non-streaming handlers, so the two cannot
    drift in how they classify a turn - which would show up as the same question being
    answered from different pages depending on which route the client happened to call.

    ⚠️ `tier` and `intent` are reported SEPARATELY and both reach the client. A
    reference lookup legitimately answers from the keyword index, and without the intent
    a client cannot tell that apart from the retrieval service being down. One is
    correct behaviour; the other is a degraded answer.
    """
    from app.retrieval.physics9.service import search as neural_search
    from app.retrieval.physics9.service import search_index
    from app.tutor.turns import classify

    intent = classify(question, has_prior_turn=has_prior_turn)

    if intent == "followup":
        reused = last_turn_pages(db, session_id)
        if reused:
            # No retrieval at all: the student is still looking at these pages.
            return reused, Timings(), "reused", intent
        # Classified as a follow-up but there is nothing stored to follow up on - a
        # session whose first answer produced no citations. Retrieve rather than answer
        # from nothing.
        intent = "retrieve"

    if intent == "reference":
        hits, timings = search_index(question, top_k=top_k, chapter=anchor)
        return hits, timings, "heuristic", intent

    hits, timings, tier = neural_search(question, top_k=top_k, chapter=anchor)
    return hits, timings, tier, intent


def list_sessions(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    """The caller's own sessions, newest first.

    No `student_id` predicate: RLS supplies it. `ix_chat_session_student
    (student_id, started_at DESC)` already serves this ordering.
    """
    rows = (
        db.execute(
            text(
                "SELECT s.id, s.subject, s.class_level, s.chapter, s.started_at, "
                "       count(m.id) AS message_count, "
                "       max(m.created_at) AS last_message_at, "
                "       (SELECT m2.content FROM message m2 "
                "         WHERE m2.session_id = s.id AND m2.role = 'student' "
                "         ORDER BY m2.created_at LIMIT 1) AS opening_question "
                "FROM chat_session s LEFT JOIN message m ON m.session_id = s.id "
                "GROUP BY s.id "
                "ORDER BY s.started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def get_session(db: Session, session_id: UUID) -> dict[str, Any]:
    """One session with its full transcript and the pages each answer cited."""
    session = (
        db.execute(
            text(
                "SELECT id, subject, class_level, chapter, started_at, ended_at "
                "FROM chat_session WHERE id = :sid"
            ),
            {"sid": session_id},
        )
        .mappings()
        .one_or_none()
    )
    if session is None:
        raise forbidden_scope("That chat session is not available.")

    rows = (
        db.execute(
            text(
                "SELECT m.id, m.role, m.content, m.created_at, v.payload "
                "FROM message m "
                "LEFT JOIN visual_aid v ON v.message_id = m.id AND v.kind = 'figure' "
                "WHERE m.session_id = :sid "
                "ORDER BY m.created_at, m.id"
            ),
            {"sid": session_id},
        )
        .mappings()
        .all()
    )

    return {
        **dict(session),
        "messages": [
            {
                "id": row["id"],
                "role": _ROLE_FROM_DB[row["role"]],
                "content": row["content"],
                "created_at": row["created_at"],
                "pages": (row["payload"] or {}).get("pages", []),
            }
            for row in rows
        ],
    }
