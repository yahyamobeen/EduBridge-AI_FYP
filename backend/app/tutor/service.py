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
from app.retrieval.physics9.base import PHYSICS_BOOK, Timings, page_url

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


def student_profile(db: Session, user_id: UUID) -> dict[str, Any] | None:
    """The caller's board, class and group - fixed at signup, never editable by the app."""
    row = (
        db.execute(
            text(
                "SELECT board::text AS board, class_level, student_group::text AS student_group "
                "FROM student_profile WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def student_subjects(
    db: Session, board: str, class_level: int, student_group: str
) -> list[dict[str, Any]]:
    """The subjects of this board and class that the student's group takes.

    The same rule `app.join_space_by_code` applies to classrooms - board, class, and the
    subject in the student's group (`subject_group`). The reference tables are readable
    by `app_backend` in a bound session (`20260802140000`), so no SECURITY DEFINER
    function is needed; `/reference/subjects` already reads them the same way.
    """
    rows = (
        db.execute(
            text(
                "SELECT s.id, s.name, s.content_strategy::text AS content_strategy "
                "  FROM subject s "
                "  JOIN class_level cl ON cl.id = s.class_level_id "
                "  JOIN board b ON b.id = cl.board_id "
                "  JOIN subject_group sg ON sg.subject_id = s.id "
                " WHERE b.code = CAST(:board AS board_code) AND cl.level = :lvl "
                "   AND sg.student_group = CAST(:grp AS student_group) "
                " ORDER BY s.name"
            ),
            {"board": board, "lvl": class_level, "grp": student_group},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def session_meta(db: Session, session_id: UUID) -> dict[str, Any]:
    """`subject`, `class_level` and `chapter` of one of the caller's sessions.

    The session's book is derived from these (tdd.md §3.2a "Many books"). RLS filters
    another student's session out, so it answers exactly like a missing one.
    """
    row = (
        db.execute(
            text("SELECT id, subject, class_level, chapter FROM chat_session WHERE id = :sid"),
            {"sid": session_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise forbidden_scope("That chat session is not available.")
    return dict(row)


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
    figure: Any = None,
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

    if pages or figure is not None:
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
                            for hit in (pages or [])
                        ],
                        # The validated crop region, so the figure survives a reload.
                        # Stored already clamped and bounded - `parse_box` ran before
                        # this, and nothing downstream re-validates.
                        **(
                            {
                                "figure": {
                                    "page": figure.page,
                                    "box": [figure.x0, figure.y0, figure.x1, figure.y1],
                                    "caption": figure.caption,
                                }
                            }
                            if figure is not None
                            else {}
                        ),
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


def last_turn_pages(db: Session, session_id: UUID, book=None) -> list[dict[str, Any]]:
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
    # The session's own book - a follow-up in Chemistry must cite Chemistry pages.
    book_id = book.book_id if book is not None else PHYSICS_BOOK
    return [
        {
            "page": page["page"],
            "chapter": page.get("chapter"),
            "score": page.get("score"),
            "url": page_url(page["page"], book_id),
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
    book=None,
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
    from app.retrieval.physics9.heuristic import TOPIC_TERMS
    from app.retrieval.physics9.service import search as neural_search
    from app.retrieval.physics9.service import search_index
    from app.tutor.turns import classify

    physics = book is None or book.book_id == PHYSICS_BOOK
    # Only Physics 9 has a syllabus vocabulary; every other book gets the stricter
    # "nothing but fillers and markers" test (tdd.md §3.2a, turn routing).
    intent = classify(
        question, has_prior_turn=has_prior_turn, topic_terms=TOPIC_TERMS if physics else None
    )

    if intent == "followup":
        reused = last_turn_pages(db, session_id, book)
        if reused:
            # No retrieval at all: the student is still looking at these pages.
            return reused, Timings(), "reused", intent
        # Classified as a follow-up but there is nothing stored to follow up on - a
        # session whose first answer produced no citations. Retrieve rather than answer
        # from nothing.
        intent = "retrieve"

    if intent == "reference" and physics:
        hits, timings = search_index(question, top_k=top_k, chapter=anchor, book=book)
        return hits, timings, "heuristic", intent
    if intent == "reference":
        # No syllabus index for this book, so an exercise reference is a similarity
        # search like any other question.
        intent = "retrieve"

    # Raises RetrievalUnavailableError for a book other than Physics 9 when its tier is
    # down - the route turns that into 503 MODEL_UNAVAILABLE.
    hits, timings, tier = neural_search(question, top_k=top_k, chapter=anchor, book=book)
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


def message_figure(db: Session, message_id: UUID) -> dict[str, Any] | None:
    """The stored crop region for one assistant turn, with its session's subject and
    class (from which the book is derived), or None.

    Read under RLS through `visual_aid_owner` and `chat_session_owner`, so a message
    belonging to another student simply is not found - which is why this endpoint is
    safe in a way the legacy page-scan endpoint is not (defect P1).
    """
    row = (
        db.execute(
            text(
                "SELECT v.payload, s.subject, s.class_level "
                "  FROM visual_aid v "
                "  JOIN message m ON m.id = v.message_id "
                "  JOIN chat_session s ON s.id = m.session_id "
                " WHERE v.message_id = :mid AND v.kind = 'figure' LIMIT 1"
            ),
            {"mid": message_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    figure = (row["payload"] or {}).get("figure")
    if not isinstance(figure, dict):
        return None
    return {"figure": figure, "subject": row["subject"], "class_level": row["class_level"]}
