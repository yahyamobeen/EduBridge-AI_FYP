"""Class 9 AI Tutor Routes.

Exposes endpoints for the Class 9 Physics AI Tutor:
- POST /api/tutor/class9/physics/chat
- GET  /api/tutor/class9/physics/pages/{page_num}
- GET  /api/tutor/class9/physics/info
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
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
from app.retrieval.physics9.retriever import BOOK_PAGES
from app.retrieval.physics9.service import answer_physics_query, get_physics_retriever

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
    gen_error: str | None = None


@router.post(
    "/class9/physics/chat",
    response_model=PhysicsChatResponse,
    dependencies=[
        Depends(require_role(UserRole.student.value)),
        Depends(require_guardian_verified),
        Depends(require_class_9_student),
    ],
)
def chat_class9_physics(
    payload: PhysicsChatRequest,
) -> PhysicsChatResponse:
    """Grounded conversation with the Class 9 Physics AI Tutor (PCTB)."""
    history_dicts = [{"role": m.role, "content": m.content} for m in payload.history]
    result = answer_physics_query(
        question=payload.message,
        lang=payload.lang,
        history=history_dicts,
        top_k=3,
    )

    citations = [
        PageCitation(
            page=h["page"],
            chapter=h.get("chapter"),
            score=h["score"],
            url=h["url"],
        )
        for h in result["pages"]
    ]

    return PhysicsChatResponse(
        reply=result["reply"],
        pages=citations,
        timings=result["timings"],
        gen_error=result["gen_error"],
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
        "has_real_embeddings": retriever.has_real_embeddings,
        "checkpoint": retriever.checkpoint,
    }
