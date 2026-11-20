"""AI Tutor routes (tdd.md §3.2, §3.2a).

The tutor serves every book a student is entitled to (tdd.md §3.2a "Many books"):

- GET  /api/tutor/books                       the caller's subjects and their books
- POST /api/tutor/ask                         a streamed, grounded answer (SSE)
- GET  /api/tutor/books/{book_id}/pages/{n}   one page scan of one of the caller's books
- GET  /api/tutor/sessions                    the caller's sessions
- GET  /api/tutor/sessions/{session_id}       one session with its transcript
- GET  /api/tutor/figures/{message_id}        the cropped figure for one answer

Legacy Physics 9 pilot routes, kept unchanged and no longer used by the frontend:

- POST /api/tutor/class9/physics/chat         superseded by /ask
- GET  /api/tutor/class9/physics/pages/{n}    unauthenticated (defect P1)
- GET  /api/tutor/class9/physics/info
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
from app.core.errors import forbidden_scope, model_unavailable, not_grounded, validation_error
from app.core.ratelimit import TUTOR_ASK_LIMIT, TUTOR_SESSIONS_LIMIT, enforce
from app.models.enums import UserRole
from app.retrieval.physics9.base import BOOK_PAGES, PHYSICS_BOOK, RetrievalUnavailableError
from app.retrieval.physics9.catalogue import Book, get_catalogue
from app.retrieval.physics9.service import (
    answer_physics_query,
    get_physics_generator,
    get_physics_retriever,
    pages_directory,
)
from app.tutor import service as tutor_service
from app.tutor.figures import crop_page, parse_box
from app.tutor.streaming import SSE_HEADERS, event_stream

logger = logging.getLogger("edubridge.tutor.routes")

router = APIRouter(prefix="/tutor", tags=["tutor"])


def require_class_9_student(
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> AuthContext:
    """The legacy `/class9/physics/chat` guard: a student currently in Class 9."""
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


@dataclass(frozen=True)
class BookContext:
    """The book a request is about, checked against the caller."""

    book: Book
    board: str
    class_level: int
    content_strategy: str | None


def resolve_book(ctx: AuthContext, *, book_id: str | None, session_id: UUID | None) -> BookContext:
    """The book for this request, or a §7.3 error. A plain function, not a `Depends`:
    `/ask` must call `enforce()` first, and tests replace this one name.

    A resumed session brings its own book (derived from its subject and class); a new
    one takes `book_id`, defaulting to Physics 9. Either way the book must be the
    caller's - board, class and group, the rule `app.join_space_by_code` applies to
    classrooms - and available on this host.

    Errors (tdd.md §3.2): unknown or unowned book → 403 FORBIDDEN_SCOPE; a `book_id`
    that differs from the resumed session's → 400 VALIDATION_ERROR; the caller's book
    but not servable here → 503 MODEL_UNAVAILABLE.
    """
    profile = tutor_service.student_profile(ctx.session, ctx.user_id)
    if profile is None:
        raise forbidden_scope("The tutor needs a student profile.")
    catalogue = get_catalogue()

    if session_id is not None:
        meta = tutor_service.session_meta(ctx.session, session_id)
        book = catalogue.for_session(profile["board"], meta["class_level"], meta["subject"])
        if book is None:
            raise forbidden_scope("That chat session is not available.")
        if book_id is not None and book_id != book.book_id:
            raise validation_error(
                message="A conversation stays with one book.",
                details={"fields": {"book_id": "does not match this conversation's book"}},
            )
    else:
        book = catalogue.get(book_id or PHYSICS_BOOK)
        if book is None:
            raise forbidden_scope("That book is not available.")

    subjects = tutor_service.student_subjects(
        ctx.session, profile["board"], profile["class_level"], profile["student_group"]
    )
    subject_row = next((s for s in subjects if s["name"] == book.subject), None)
    if (
        book.board != profile["board"]
        or profile["class_level"] not in book.classes
        or subject_row is None
    ):
        raise forbidden_scope("That book is not one of your subjects.")
    if not book.available:
        raise model_unavailable("That book is not available right now.")
    return BookContext(
        book=book,
        board=profile["board"],
        class_level=profile["class_level"],
        content_strategy=subject_row.get("content_strategy"),
    )


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
    book_id: str | None = None
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
    book_id: str | None = None
    subject: str | None
    class_level: int | None
    chapter: int | None
    started_at: datetime
    ended_at: datetime | None
    messages: list[TranscriptMessage]


class TutorBook(BaseModel):
    book_id: str | None
    subject: str
    available: bool


class TutorBooksResponse(BaseModel):
    board: str
    class_level: int
    books: list[TutorBook]


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
    """Grounded conversation with the Class 9 Physics AI Tutor (PCTB). Legacy.

    `ctx` is a parameter rather than a bare dependency because this handler needs the
    bound session to persist the turn. The guards that only need to refuse stay in
    `dependencies=[...]`.
    """
    # Shares the `tutor_ask` bucket with /tutor/ask on purpose: separate buckets would
    # let a client double its budget by alternating the two routes.
    enforce(request, bucket="tutor_ask", limit=TUTOR_ASK_LIMIT, subject=str(ctx.user_id))

    # This route only ever served Physics 9, so it resumes only the sessions it opened
    # (subject `physics`) - never a session /ask opened for another book.
    if payload.session_id is not None:
        meta = tutor_service.session_meta(ctx.session, payload.session_id)
        if meta["subject"] != "physics":
            raise forbidden_scope("That chat session is not available.")

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
    # Checked against the book's own chapters - only Physics 9 has any today.
    chapter: int | None = Field(default=None, ge=1)
    # The book for a NEW session; defaults to Physics 9. On resume it must match the
    # session's book or be omitted (tdd.md §3.2).
    book_id: str | None = Field(default=None, min_length=1, max_length=64)


@router.post("/ask", dependencies=[Depends(require_guardian_verified)])
def ask(
    request: Request,
    payload: AskRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> StreamingResponse:
    """A streamed, grounded answer (`tdd.md` §3.2, specified as SSE since v0.1).

    Everything that can fail outright happens HERE, before the response starts, so it
    can still be a §7.3 envelope with a real status code. Once the first byte is on the
    wire that is impossible - which is why the book, retrieval and the generator's
    readiness are all checked up front and only token production happens inside the
    stream.
    """
    # First statement, before any work: one serialised model answers one query at a
    # time, so an unbounded caller is a denial of service against the rest of the class,
    # not merely a waste (see TUTOR_ASK_LIMIT).
    enforce(request, bucket="tutor_ask", limit=TUTOR_ASK_LIMIT, subject=str(ctx.user_id))

    context = resolve_book(ctx, book_id=payload.book_id, session_id=payload.session_id)
    book = context.book
    if (
        payload.session_id is None
        and payload.chapter is not None
        and book.anchor(payload.chapter) is None
    ):
        raise validation_error(
            message="That chapter is not in this book.",
            details={"fields": {"chapter": "not a chapter of this book"}},
        )

    session_id, anchor = tutor_service.open_or_resume_session(
        ctx.session,
        ctx.user_id,
        payload.session_id,
        subject=book.subject,
        class_level=context.class_level,
        chapter=payload.chapter,
    )

    history = (
        tutor_service.recent_history(ctx.session, session_id)
        if payload.session_id is not None
        else []
    )

    try:
        hits, timings, tier, intent = tutor_service.retrieve_for_turn(
            ctx.session,
            session_id,
            payload.message,
            anchor=anchor,
            top_k=3,
            has_prior_turn=bool(history),
            book=book,
        )
    except RetrievalUnavailableError as exc:
        # Only a book other than Physics 9 gets here: it has no keyword fallback, and
        # answering from another book's pages is never an option (owner decision 2).
        raise model_unavailable("That book's search is not available right now.") from exc
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
            token_source=generator.stream_tokens(
                payload.message,
                hits,
                history,
                book=book,
                class_level=context.class_level,
                content_strategy=context.content_strategy,
            ),
            book_pages=book.pages,
        ),
        # charset is explicit: an Urdu answer is utf-8 and a client that guesses
        # latin-1 renders it as mojibake.
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )


@router.get(
    "/books",
    response_model=TutorBooksResponse,
    dependencies=[Depends(require_guardian_verified)],
)
def list_tutor_books(
    request: Request,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> TutorBooksResponse:
    """The caller's subjects - their board, class and group - each with its book.

    A subject with no book, or one that is hidden (Quran Translation, prd.md FR-17), is
    listed with `available: false`, so the student sees "coming soon" rather than a
    missing subject (prd.md FR-19).
    """
    enforce(
        request,
        bucket="tutor_sessions",
        limit=TUTOR_SESSIONS_LIMIT,
        subject=str(ctx.user_id),
    )
    profile = tutor_service.student_profile(ctx.session, ctx.user_id)
    if profile is None:
        raise forbidden_scope("The tutor needs a student profile.")
    catalogue = get_catalogue()
    books = []
    for subject in tutor_service.student_subjects(
        ctx.session, profile["board"], profile["class_level"], profile["student_group"]
    ):
        book = catalogue.for_subject(profile["board"], profile["class_level"], subject["name"])
        books.append(
            TutorBook(
                book_id=book.book_id if book else None,
                subject=subject["name"],
                available=bool(book and book.available),
            )
        )
    return TutorBooksResponse(
        board=profile["board"], class_level=profile["class_level"], books=books
    )


@router.get(
    "/books/{book_id}/pages/{page}",
    dependencies=[Depends(require_guardian_verified)],
)
def get_book_page(
    request: Request,
    book_id: str,
    page: int,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> FileResponse:
    """One page scan of one of the caller's books, for a citation preview.

    Authenticated and owner-scoped, unlike the legacy Physics route (defect P1): the
    book must be the caller's (`resolve_book`). The file path comes from the catalogue
    entry, never from `book_id` itself.
    """
    enforce(
        request,
        bucket="tutor_sessions",
        limit=TUTOR_SESSIONS_LIMIT,
        subject=str(ctx.user_id),
    )
    book = resolve_book(ctx, book_id=book_id, session_id=None).book
    if not 1 <= page <= book.pages:
        raise validation_error(
            message=f"This book has pages 1 to {book.pages}.",
            details={"fields": {"page": f"must be between 1 and {book.pages}"}},
        )
    path = book.page_path(page)
    if path is None:
        raise forbidden_scope("That page is not available.")
    # Private: a shared cache must not serve one student's textbook page to the next.
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )


def _session_book_id(board: str | None, row: dict) -> str | None:
    if board is None:
        return None
    book = get_catalogue().for_session(board, row.get("class_level"), row.get("subject"))
    return book.book_id if book else None


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
    there is no `student_id` filter here to forget. Each row carries its book, derived
    from its subject and class (tdd.md §3.2a "Many books").
    """
    enforce(
        request,
        bucket="tutor_sessions",
        limit=TUTOR_SESSIONS_LIMIT,
        subject=str(ctx.user_id),
    )
    profile = tutor_service.student_profile(ctx.session, ctx.user_id)
    board = profile["board"] if profile else None
    return [
        SessionSummary(**row, book_id=_session_book_id(board, row))
        for row in tutor_service.list_sessions(ctx.session, limit)
    ]


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
    detail = tutor_service.get_session(ctx.session, session_id)
    profile = tutor_service.student_profile(ctx.session, ctx.user_id)
    board = profile["board"] if profile else None
    return SessionDetail(**detail, book_id=_session_book_id(board, detail))


@router.get(
    "/figures/{message_id}",
    dependencies=[Depends(require_guardian_verified)],
)
def get_tutor_figure(
    message_id: UUID,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> Response:
    """The cropped figure for one answer (`tdd.md` §3.2a, `prd.md` MM-1).

    ⚠️ Authenticated and owner-scoped: the box is read through `visual_aid_owner` and
    `chat_session_owner`, so another student's figure is simply not found. The page it
    is cropped from belongs to the answer's own session's book. Served same-origin
    because the frontend CSP is `img-src 'self' data:` — an external URL in an `<img>`
    would be blocked.
    """
    stored = tutor_service.message_figure(ctx.session, message_id)
    if stored is None:
        raise forbidden_scope("That figure is not available.")

    profile = tutor_service.student_profile(ctx.session, ctx.user_id)
    book = get_catalogue().for_session(
        profile["board"] if profile else "", stored["class_level"], stored["subject"]
    )
    if book is None or book.pages_dir is None:
        raise forbidden_scope("That figure is not available.")

    # Re-validated on the way out, not trusted because it was validated on the way in.
    # A row written by an older revision, or by anything other than this code path, is
    # still untrusted input by the time it reaches `Image.crop`.
    box = parse_box(stored["figure"], book_pages=book.pages)
    if box is None:
        raise forbidden_scope("That figure is not available.")

    image = crop_page(book.pages_dir, box)
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
    """Serves a 150 DPI textbook page scan for citation previews. Legacy, unauthenticated
    (defect P1); the frontend uses `/books/{book_id}/pages/{n}`."""
    if page_num < 1 or page_num > BOOK_PAGES:
        raise HTTPException(
            status_code=404, detail=f"Page {page_num} out of book range (1-{BOOK_PAGES})"
        )

    pages_dir = pages_directory()
    if pages_dir is None or not pages_dir.exists():
        raise HTTPException(status_code=404, detail="Textbook page scans directory not configured")

    img_path = pages_dir / f"p{page_num:03}.jpeg"
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
