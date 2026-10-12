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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth.dependencies import (
    AuthContext,
    authenticated,
    require_guardian_verified,
    require_role,
)
from app.core.errors import forbidden_scope
from app.models.enums import UserRole
from app.retrieval.physics9.base import BOOK_PAGES
from app.retrieval.physics9.service import answer_physics_query, get_physics_retriever
from app.tutor import service as tutor_service

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
    payload: PhysicsChatRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> PhysicsChatResponse:
    """Grounded conversation with the Class 9 Physics AI Tutor (PCTB).

    `ctx` is a parameter rather than a bare dependency because this handler needs the
    bound session to persist the turn. The guards that only need to refuse stay in
    `dependencies=[...]`.
    """
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


@router.get(
    "/sessions",
    response_model=list[SessionSummary],
    dependencies=[Depends(require_guardian_verified)],
)
def list_tutor_sessions(
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SessionSummary]:
    """The caller's own tutor sessions, newest first (`tdd.md` §3.2).

    Ownership is enforced by Row-Level Security, not by a predicate in the query - so
    there is no `student_id` filter here to forget.
    """
    return [SessionSummary(**row) for row in tutor_service.list_sessions(ctx.session, limit)]


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetail,
    dependencies=[Depends(require_guardian_verified)],
)
def get_tutor_session(
    session_id: UUID,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> SessionDetail:
    """One session with its transcript and the pages each answer cited.

    A session belonging to another student and a session that does not exist both answer
    `403 FORBIDDEN_SCOPE`, deliberately: answering differently would confirm that a given
    id exists, and §7.3 catalogues no 404 to reach for.
    """
    return SessionDetail(**tutor_service.get_session(ctx.session, session_id))


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
