"""Class 9 AI Tutor Routes.

Exposes endpoints for the Class 9 Physics AI Tutor:
- POST /api/tutor/class9/physics/chat
- GET  /api/tutor/sessions
- GET  /api/tutor/sessions/{session_id}
- GET  /api/tutor/class9/physics/pages/{page_num}
- GET  /api/tutor/class9/physics/info
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth.dependencies import (
    AuthContext,
    authenticated,
    require_guardian_verified,
    require_role,
)
from app.core.errors import forbidden_scope, model_unavailable, not_grounded
from app.core.ratelimit import TUTOR_ASK_LIMIT, TUTOR_SESSIONS_LIMIT, enforce
from app.models.enums import UserRole
from app.retrieval.physics9.base import BOOK_PAGES
from app.retrieval.physics9.service import (
    answer_physics_query,
    get_physics_generator,
    get_physics_retriever,
)
from app.tutor import service as tutor_service
from app.tutor.figures import crop_page, parse_box
from app.tutor.streaming import SSE_HEADERS, event_stream

logger = logging.getLogger("edubridge.tutor.routes")

router = APIRouter(prefix="/tutor", tags=["tutor"])


def require_class_9_student(
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> AuthContext:
    """Verifies that the acting user is a student currently enrolled in Class 9."""
    if ctx.role != UserRole.student.value:
        raise forbidden_scope("AI Tutor is accessible to students only.")

    profile = (
        ctx.session.execute(
            text("SELECT class_level FROM student_profile WHERE user_id = :uid"),
            {"uid": ctx.user_id},
        )
        .mappings()
        .one_or_none()
    )
    if profile is None or profile.get("class_level") != 9:
        raise forbidden_scope("Class 9 Physics Tutor is restricted to Class 9 students.")
    return ctx


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class PhysicsChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    lang: Literal["en", "ur", "ur-Latn"] = "en"
    # `session_id` null opens a session; `chapter` sets its anchor, on that first turn
    # only. ⚠️ `history` is accepted but IGNORED when `session_id` is given: the stored
    # transcript is the source of truth, and trusting a client-supplied transcript would
    # let a caller put words in the assistant's mouth and have the model treat them as
    # its own prior answer.
    session_id: UUID | None = None
    chapter: int | None = Field(default=None, ge=1, le=9)
    history: list[ChatMessage] = Field(default_factory=list)


class PageCitation(BaseModel):
    page: int
    chapter: int | None
    score: float
    url: str


class PhysicsChatResponse(BaseModel):
    reply: str
    pages: list[PageCitation]
    timings: dict[str, float]
    # Which tier answered: `remote`, `local` or `heuristic`. A degraded answer must be
    # visibly degraded (tdd.md §3.2a).
    retriever: str
    session_id: UUID
    message_id: UUID
    gen_error: str | None = None


class SessionSummary(BaseModel):
    id: UUID
    subject: str | None
    class_level: int | None
    chapter: int | None
    started_at: datetime
    message_count: int
    last_message_at: datetime | None
    opening_question: str | None


class TranscriptMessage(BaseModel):
    id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
    pages: list[dict] = Field(default_factory=list)


class SessionDetail(BaseModel):
    id: UUID
    subject: str | None
    class_level: int | None
    chapter: int | None
    started_at: datetime
    ended_at: datetime | None
    messages: list[TranscriptMessage]


@router.post(
    "/class9/physics/chat",
    response_model=PhysicsChatResponse,
    dependencies=[
        Depends(require_guardian_verified),
        Depends(require_class_9_student),
    ],
)
def chat_class9_physics(
    request: Request,
    payload: PhysicsChatRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> PhysicsChatResponse:
    """Grounded conversation with the Class 9 Physics AI Tutor (PCTB).

    `ctx` is a parameter rather than a bare dependency because this handler needs the
    bound session to persist the turn. The guards that only need to refuse stay in
    `dependencies=[...]`.
    """
    # Shares the `tutor_ask` bucket with /tutor/ask on purpose: separate buckets would
    # let a client double its budget by alternating the two routes.
    enforce(request, bucket="tutor_ask", limit=TUTOR_ASK_LIMIT, subject=str(ctx.user_id))

    session_id, anchor = tutor_service.open_or_resume_session(
        ctx.session,
        ctx.user_id,
        payload.session_id,
        subject="physics",
        class_level=9,
        chapter=payload.chapter,
    )

    # The stored transcript wins over anything the client sent. On a brand-new session
    # there is nothing stored, so the client's `history` is accepted - it has no prior
    # turn to contradict.
    history = (
        tutor_service.recent_history(ctx.session, session_id)
        if payload.session_id is not None
        else [{"role": m.role, "content": m.content} for m in payload.history]
    )

    tutor_service.append_message(ctx.session, session_id, "user", payload.message)

    result = answer_physics_query(
        question=payload.message,
        lang=payload.lang,
        history=history,
        top_k=3,
        chapter=anchor,
    )

    message_id = tutor_service.append_message(
        ctx.session,
        session_id,
        "assistant",
        result["reply"],
        pages=result["pages"],
    )

    return PhysicsChatResponse(
        reply=result["reply"],
        pages=[
            PageCitation(page=h["page"], chapter=h.get("chapter"), score=h["score"], url=h["url"])
            for h in result["pages"]
        ],
        timings=result["timings"],
        retriever=result["retriever"],
        session_id=session_id,
        message_id=message_id,
        gen_error=result["gen_error"],
    )


class AskRequest(BaseModel):
    """`POST /api/tutor/ask` (tdd.md §3.2).

    No `history` field, unlike the older `/chat`: a streamed session always reads its
    transcript from the database, so there is nothing for a client to supply and
    nothing for a client to forge.
    """

    message: str = Field(min_length=1, max_length=2000)
    lang: Literal["en", "ur", "ur-Latn"] = "en"
    session_id: UUID | None = None
    chapter: int | None = Field(default=None, ge=1, le=9)


@router.post(
    "/ask",
    dependencies=[
        Depends(require_guardian_verified),
        Depends(require_class_9_student),
    ],
)
def ask(
    request: Request,
    payload: AskRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> StreamingResponse:
    """A streamed, grounded answer (`tdd.md` §3.2, specified as SSE since v0.1).

    Everything that can fail outright happens HERE, before the response starts, so it
    can still be a §7.3 envelope with a real status code. Once the first byte is on the
    wire that is impossible - which is why retrieval and the generator's readiness are
    both checked up front and only token production happens inside the stream.
    """
    # First statement, before any work: one serialised model answers one query at a
    # time, so an unbounded caller is a denial of service against the rest of the class,
    # not merely a waste (see TUTOR_ASK_LIMIT).
    enforce(request, bucket="tutor_ask", limit=TUTOR_ASK_LIMIT, subject=str(ctx.user_id))

    session_id, anchor = tutor_service.open_or_resume_session(
        ctx.session,
        ctx.user_id,
        payload.session_id,
        subject="physics",
        class_level=9,
        chapter=payload.chapter,
    )

    history = (
        tutor_service.recent_history(ctx.session, session_id)
        if payload.session_id is not None
        else []
    )

    hits, timings, tier, intent = tutor_service.retrieve_for_turn(
        ctx.session,
        session_id,
        payload.message,
        anchor=anchor,
        top_k=3,
        has_prior_turn=bool(history),
    )
    if not hits:
        # ⚠️ This is the DEFENSIVE case only. A real grounding gate compares the top
        # score gap against `SIM_THRESHOLD`, which is still [PROPOSED] (tdd.md §8.2)
        # because only 5 of 53 labelled questions have been scored. Inventing a number
        # here would read as a measured threshold and be neither. Until the eval set
        # runs, retrieval always returns pages and this branch does not fire.
        raise not_grounded()

    generator = get_physics_generator()
    if not generator.api_key:
        # Before the first byte, so this is an honest 503 rather than citations with
        # silence after them. ⚠️ It deliberately does NOT reach the old path's
        # from-memory fallback (defect P2) - a student who cannot be answered is told.
        raise model_unavailable()

    return StreamingResponse(
        event_stream(
            db=ctx.session,
            session_id=session_id,
            question=payload.message,
            hits=hits,
            retriever=tier,
            intent=intent,
            timings={"encode": round(timings.encode, 3), "search": round(timings.search, 4)},
            token_source=generator.stream_tokens(payload.message, hits, history),
        ),
        # charset is explicit: an Urdu answer is utf-8 and a client that guesses
        # latin-1 renders it as mojibake.
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )


@router.get(
    "/sessions",
    response_model=list[SessionSummary],
    dependencies=[Depends(require_guardian_verified)],
)
def list_tutor_sessions(
    request: Request,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SessionSummary]:
    """The caller's own tutor sessions, newest first (`tdd.md` §3.2).

    Ownership is enforced by Row-Level Security, not by a predicate in the query - so
    there is no `student_id` filter here to forget.
    """
    enforce(
        request,
        bucket="tutor_sessions",
        limit=TUTOR_SESSIONS_LIMIT,
        subject=str(ctx.user_id),
    )
    return [SessionSummary(**row) for row in tutor_service.list_sessions(ctx.session, limit)]


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetail,
    dependencies=[Depends(require_guardian_verified)],
)
def get_tutor_session(
    request: Request,
    session_id: UUID,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> SessionDetail:
    """One session with its transcript and the pages each answer cited.

    A session belonging to another student and a session that does not exist both answer
    `403 FORBIDDEN_SCOPE`, deliberately: answering differently would confirm that a given
    id exists, and §7.3 catalogues no 404 to reach for.
    """
    enforce(
        request,
        bucket="tutor_sessions",
        limit=TUTOR_SESSIONS_LIMIT,
        subject=str(ctx.user_id),
    )
    return SessionDetail(**tutor_service.get_session(ctx.session, session_id))


@router.get(
    "/figures/{message_id}",
    dependencies=[Depends(require_guardian_verified)],
)
def get_tutor_figure(
    message_id: UUID,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> Response:
    """The cropped figure for one answer (`tdd.md` §3.2a, `prd.md` MM-1).

    ⚠️ Unlike the page-scan endpoint beside it, this one IS authenticated and
    owner-scoped: the box is read through `visual_aid_owner`, so another student's
    figure is simply not found. Served same-origin because the frontend CSP is
    `img-src 'self' data:` — an external URL in an `<img>` would be blocked.
    """
    stored = tutor_service.message_figure(ctx.session, message_id)
    if stored is None:
        raise forbidden_scope("That figure is not available.")

    # Re-validated on the way out, not trusted because it was validated on the way in.
    # A row written by an older revision, or by anything other than this code path, is
    # still untrusted input by the time it reaches `Image.crop`.
    box = parse_box(stored, book_pages=BOOK_PAGES)
    retriever = get_physics_retriever()
    if box is None or not retriever.pages_dir:
        raise forbidden_scope("That figure is not available.")

    image = crop_page(retriever.pages_dir, box)
    if image is None:
        raise forbidden_scope("That figure is not available.")

    return Response(
        content=image,
        media_type="image/jpeg",
        # Private: this is a crop of a specific student's answer, and a shared cache
        # holding it would serve it to the next person behind the same proxy.
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/class9/physics/pages/{page_num}")
def get_physics_page_image(page_num: int):
    """Serves a 150 DPI textbook page scan for citation previews."""
    if page_num < 1 or page_num > BOOK_PAGES:
        raise HTTPException(
            status_code=404, detail=f"Page {page_num} out of book range (1-{BOOK_PAGES})"
        )

    retriever = get_physics_retriever()
    if not retriever.pages_dir or not retriever.pages_dir.exists():
        raise HTTPException(status_code=404, detail="Textbook page scans directory not configured")

    img_path = retriever.pages_dir / f"p{page_num:03}.jpeg"
    if not img_path.exists():
        raise HTTPException(status_code=404, detail=f"Page scan p{page_num:03}.jpeg not found")

    return FileResponse(img_path, media_type="image/jpeg")


@router.get("/class9/physics/info")
def get_physics_tutor_info():
    """Returns metadata about the Class 9 Physics tutor module."""
    retriever = get_physics_retriever()
    return {
        "subject": "Physics",
        "class_level": 9,
        "board": "PCTB",
        "book_pages": BOOK_PAGES,
        # `retriever` replaces the previous `has_real_embeddings` boolean, which could
        # not distinguish the three tiers — and a boolean that reads "no" for both "the
        # service is cold" and "this host has no model at all" hides the one thing this
        # endpoint exists to tell you. `checkpoint` is empty unless the local tier
        # loaded a file, so it never implies a model that is not resident.
        "retriever": retriever.name,
        "checkpoint": getattr(retriever, "checkpoint", ""),
    }
