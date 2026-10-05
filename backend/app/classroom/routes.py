"""
Classroom routes — `tdd.md` §3.6: spaces, codes and membership (Phase 2), the
stream (Phase 3), assignments, submissions and grades (Phase 4), the calendar
(Phase 5), files (Phase 6) and the class chat (Phase 7).

Thin by design: rate limit first, then one service call. Who may call is
decided by the dependency on each route (app/classroom/dependencies.py); which
SPACE they may touch is decided by the database, through the service.

Like `app/auth/routes.py`, no route here depends on `get_service_db`. If a new
endpoint appears to need it, add a narrow `app.*` function instead.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import AuthContext, authenticated
from app.classroom import (
    announcements,
    assignments,
    calendar,
    chat,
    file_service,
    links,
    service,
    storage,
)
from app.classroom.dependencies import AnyStudent, GatedStudent, Participant, Teacher
from app.classroom.files import download_headers, read_bounded_body
from app.classroom.schemas import (
    Announcement,
    AnnouncementCreateRequest,
    AnnouncementPage,
    AnnouncementUpdateRequest,
    AssignmentCreateRequest,
    AssignmentDetail,
    AssignmentPage,
    AssignmentUpdateRequest,
    CalendarResponse,
    ChaptersResponse,
    ChatMessage,
    ChatPage,
    FileMeta,
    GradeRequest,
    JoinCodeRequest,
    JoinCodeResponse,
    JoinRequest,
    JoinResponse,
    LinkMeta,
    LinkRequest,
    MessageCreateRequest,
    MuteRequest,
    MySubmission,
    PeopleResponse,
    SpaceCreateRequest,
    SpaceDetail,
    SpaceListResponse,
    SpaceUpdateRequest,
    StudentWork,
    SubjectsResponse,
    SubmissionDraftRequest,
    SubmissionsResponse,
    ViewLink,
)
from app.core.config import get_settings
from app.core.ratelimit import (
    CHAT_POLL_LIMIT,
    CHAT_POST_LIMIT,
    CLASSROOM_JOIN_LIMIT,
    CLASSROOM_READ_LIMIT,
    CLASSROOM_WRITE_LIMIT,
    FILE_DOWNLOAD_LIMIT,
    FILE_UPLOAD_LIMIT,
    enforce,
)

router = APIRouter(tags=["classroom"])


def _read(request: Request, ctx: AuthContext) -> None:
    enforce(request, bucket="classroom_read", limit=CLASSROOM_READ_LIMIT, subject=str(ctx.user_id))


def _write(request: Request, ctx: AuthContext) -> None:
    enforce(
        request, bucket="classroom_write", limit=CLASSROOM_WRITE_LIMIT, subject=str(ctx.user_id)
    )


# Declared before `/spaces/{space_id}` routes. `space_id` is typed UUID so
# "join" could never match it anyway, but order should not be the thing a
# reader has to reason about.
@router.post("/spaces/join", response_model=JoinResponse)
def join_space_endpoint(request: Request, payload: JoinRequest, ctx: GatedStudent) -> JoinResponse:
    # Its own, tight bucket: this is the one brute-force surface in the module.
    enforce(request, bucket="classroom_join", limit=CLASSROOM_JOIN_LIMIT, subject=str(ctx.user_id))
    return JoinResponse(**service.join_space(ctx.session, payload))


@router.get("/spaces", response_model=SpaceListResponse)
def list_spaces_endpoint(request: Request, ctx: Participant) -> SpaceListResponse:
    _read(request, ctx)
    return SpaceListResponse(**service.list_spaces(ctx.session))


@router.post("/spaces", response_model=SpaceDetail, status_code=status.HTTP_201_CREATED)
def create_space_endpoint(
    request: Request, payload: SpaceCreateRequest, ctx: Teacher
) -> SpaceDetail:
    _write(request, ctx)
    return SpaceDetail(**service.create_space(ctx.session, ctx.user_id, payload))


@router.get("/spaces/{space_id}", response_model=SpaceDetail)
def get_space_endpoint(request: Request, space_id: UUID, ctx: Participant) -> SpaceDetail:
    _read(request, ctx)
    return SpaceDetail(**service.get_space(ctx.session, space_id))


@router.patch("/spaces/{space_id}", response_model=SpaceDetail)
def update_space_endpoint(
    request: Request, space_id: UUID, payload: SpaceUpdateRequest, ctx: Teacher
) -> SpaceDetail:
    _write(request, ctx)
    return SpaceDetail(**service.update_space(ctx.session, space_id, payload))


@router.post("/spaces/{space_id}/join-code", response_model=JoinCodeResponse)
def join_code_endpoint(
    request: Request, space_id: UUID, payload: JoinCodeRequest, ctx: Teacher
) -> JoinCodeResponse:
    _write(request, ctx)
    return JoinCodeResponse(
        **service.change_join_code(ctx.session, ctx.user_id, space_id, payload.action)
    )


@router.delete("/spaces/{space_id}/membership", status_code=status.HTTP_204_NO_CONTENT)
def leave_space_endpoint(request: Request, space_id: UUID, ctx: AnyStudent) -> None:
    _write(request, ctx)
    service.leave_space(ctx.session, space_id)


@router.get("/spaces/{space_id}/people", response_model=PeopleResponse)
def people_endpoint(request: Request, space_id: UUID, ctx: Participant) -> PeopleResponse:
    _read(request, ctx)
    return PeopleResponse(**service.people(ctx.session, space_id))


@router.delete("/spaces/{space_id}/members/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member_endpoint(
    request: Request, space_id: UUID, student_id: UUID, ctx: Teacher
) -> None:
    _write(request, ctx)
    service.remove_student(ctx.session, ctx.user_id, space_id, student_id)


@router.get("/reference/subjects", response_model=SubjectsResponse)
def subjects_endpoint(
    request: Request,
    # Authenticated, unlike /reference/enums: the curriculum tables are already
    # readable without a session (finding B13), and a new endpoint should not
    # widen that.
    ctx: Annotated[AuthContext, Depends(authenticated)],
    board: Literal["PCTB", "STBB"],
    class_level: Annotated[int, Query(ge=9, le=12)],
) -> SubjectsResponse:
    _read(request, ctx)
    return SubjectsResponse(**service.list_subjects(ctx.session, board, class_level))


# ── Phase 3: the stream ─────────────────────────────────────────────────────


@router.get("/spaces/{space_id}/announcements", response_model=AnnouncementPage)
def list_announcements_endpoint(
    request: Request,
    space_id: UUID,
    ctx: Participant,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AnnouncementPage:
    _read(request, ctx)
    return AnnouncementPage(**announcements.list_announcements(ctx.session, space_id, cursor))


@router.post(
    "/spaces/{space_id}/announcements",
    response_model=Announcement,
    status_code=status.HTTP_201_CREATED,
)
def create_announcement_endpoint(
    request: Request, space_id: UUID, payload: AnnouncementCreateRequest, ctx: Teacher
) -> Announcement:
    _write(request, ctx)
    return Announcement(
        **announcements.create_announcement(ctx.session, ctx.user_id, space_id, payload)
    )


@router.patch("/announcements/{announcement_id}", response_model=Announcement)
def update_announcement_endpoint(
    request: Request, announcement_id: UUID, payload: AnnouncementUpdateRequest, ctx: Teacher
) -> Announcement:
    _write(request, ctx)
    return Announcement(**announcements.update_announcement(ctx.session, announcement_id, payload))


@router.delete("/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_announcement_endpoint(request: Request, announcement_id: UUID, ctx: Teacher) -> None:
    _write(request, ctx)
    announcements.delete_announcement(ctx.session, ctx.user_id, announcement_id)


# ── Phase 4: assignments, submissions and grades ───────────────────────────


@router.get("/spaces/{space_id}/assignments", response_model=AssignmentPage)
def list_assignments_endpoint(
    request: Request,
    space_id: UUID,
    ctx: Participant,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AssignmentPage:
    _read(request, ctx)
    return AssignmentPage(
        **assignments.list_assignments(ctx.session, ctx.user_id, space_id, cursor)
    )


@router.post(
    "/spaces/{space_id}/assignments",
    response_model=AssignmentDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_assignment_endpoint(
    request: Request, space_id: UUID, payload: AssignmentCreateRequest, ctx: Teacher
) -> AssignmentDetail:
    _write(request, ctx)
    return AssignmentDetail(
        **assignments.create_assignment(ctx.session, ctx.user_id, space_id, payload)
    )


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetail)
def get_assignment_endpoint(
    request: Request, assignment_id: UUID, ctx: Participant
) -> AssignmentDetail:
    _read(request, ctx)
    return AssignmentDetail(**assignments.get_assignment(ctx.session, ctx.user_id, assignment_id))


@router.patch("/assignments/{assignment_id}", response_model=AssignmentDetail)
def update_assignment_endpoint(
    request: Request, assignment_id: UUID, payload: AssignmentUpdateRequest, ctx: Teacher
) -> AssignmentDetail:
    _write(request, ctx)
    return AssignmentDetail(
        **assignments.update_assignment(ctx.session, ctx.user_id, assignment_id, payload)
    )


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment_endpoint(request: Request, assignment_id: UUID, ctx: Teacher) -> None:
    _write(request, ctx)
    assignments.delete_assignment(ctx.session, ctx.user_id, assignment_id)


@router.put("/assignments/{assignment_id}/submission", response_model=MySubmission)
def save_submission_endpoint(
    request: Request, assignment_id: UUID, payload: SubmissionDraftRequest, ctx: GatedStudent
) -> MySubmission:
    _write(request, ctx)
    return MySubmission(**assignments.save_draft(ctx.session, ctx.user_id, assignment_id, payload))


@router.post("/assignments/{assignment_id}/submission/turn-in", response_model=MySubmission)
def turn_in_endpoint(request: Request, assignment_id: UUID, ctx: GatedStudent) -> MySubmission:
    _write(request, ctx)
    return MySubmission(**assignments.turn_in(ctx.session, ctx.user_id, assignment_id))


@router.post("/assignments/{assignment_id}/submission/unsubmit", response_model=MySubmission)
def unsubmit_endpoint(request: Request, assignment_id: UUID, ctx: GatedStudent) -> MySubmission:
    _write(request, ctx)
    return MySubmission(**assignments.unsubmit(ctx.session, ctx.user_id, assignment_id))


@router.get("/assignments/{assignment_id}/submissions", response_model=SubmissionsResponse)
def submissions_endpoint(
    request: Request, assignment_id: UUID, ctx: Teacher
) -> SubmissionsResponse:
    _read(request, ctx)
    return SubmissionsResponse(**assignments.submissions_table(ctx.session, assignment_id))


@router.get("/assignments/{assignment_id}/submissions/{student_id}", response_model=StudentWork)
def student_work_endpoint(
    request: Request, assignment_id: UUID, student_id: UUID, ctx: Teacher
) -> StudentWork:
    _read(request, ctx)
    return StudentWork(**assignments.student_work(ctx.session, assignment_id, student_id))


@router.put("/assignments/{assignment_id}/grades/{student_id}", response_model=StudentWork)
def save_grade_endpoint(
    request: Request,
    assignment_id: UUID,
    student_id: UUID,
    payload: GradeRequest,
    ctx: Teacher,
) -> StudentWork:
    _write(request, ctx)
    return StudentWork(
        **assignments.save_grade(ctx.session, ctx.user_id, assignment_id, student_id, payload)
    )


@router.get("/reference/subjects/{subject_id}/chapters", response_model=ChaptersResponse)
def chapters_endpoint(request: Request, subject_id: UUID, ctx: Teacher) -> ChaptersResponse:
    _read(request, ctx)
    return ChaptersResponse(**assignments.list_chapters(ctx.session, subject_id))


# ── Phase 5: the calendar ───────────────────────────────────────────────────


# Not under /spaces: it spans every classroom the caller is in.
@router.get("/calendar", response_model=CalendarResponse)
def calendar_endpoint(
    request: Request,
    ctx: Participant,
    start: Annotated[AwareDatetime, Query(alias="from")],
    end: Annotated[AwareDatetime, Query(alias="to")],
) -> CalendarResponse:
    _read(request, ctx)
    return CalendarResponse(
        **calendar.items_between(ctx.session, ctx.user_id, ctx.role, start, end)
    )


# ── Phase 6: files ──────────────────────────────────────────────────────────
#
# Uploads are a RAW body, never multipart: Starlette's multipart parser puts no
# cap on a file part. The bytes are counted against Content-Length
# (files.read_bounded_body) after a cheap authorization check, so an outsider
# never gets to send 5 MB. The handlers are `async` only to read that stream;
# every database step runs in the threadpool, as the sync routes above do.

UploadName = Annotated[str, Header(alias="X-Upload-Filename", max_length=1024)]


def _upload_limit(request: Request, ctx: AuthContext) -> None:
    enforce(request, bucket="file_upload", limit=FILE_UPLOAD_LIMIT, subject=str(ctx.user_id))


def _download(request: Request, ctx: AuthContext, kind: str, file_id: UUID) -> StreamingResponse:
    enforce(request, bucket="file_download", limit=FILE_DOWNLOAD_LIMIT, subject=str(ctx.user_id))
    meta = file_service.readable_file(ctx.session, kind, file_id)  # RLS decides
    return StreamingResponse(
        storage.get_object_storage().open(meta["object_key"]),
        media_type=meta["content_type"],
        headers=download_headers(meta["filename"], meta["size_bytes"]),
    )


@router.post(
    "/assignments/{assignment_id}/submission/files",
    response_model=FileMeta,
    status_code=status.HTTP_201_CREATED,
)
async def upload_submission_file_endpoint(
    request: Request, assignment_id: UUID, ctx: GatedStudent, filename: UploadName
) -> FileMeta:
    _upload_limit(request, ctx)
    space_id = await run_in_threadpool(
        file_service.submission_upload_space, ctx.session, assignment_id
    )
    data = await read_bounded_body(request, get_settings().max_upload_bytes)
    return FileMeta(
        **await run_in_threadpool(
            file_service.store_submission_file,
            ctx.session,
            ctx.user_id,
            assignment_id,
            space_id,
            data,
            filename,
        )
    )


async def _upload_material(
    request: Request, ctx: AuthContext, parent: str, parent_id: UUID, filename: str
) -> FileMeta:
    _upload_limit(request, ctx)
    space_id = await run_in_threadpool(
        file_service.material_upload_space, ctx.session, parent, parent_id
    )
    data = await read_bounded_body(request, get_settings().max_upload_bytes)
    return FileMeta(
        **await run_in_threadpool(
            file_service.store_material, ctx.session, parent, parent_id, space_id, data, filename
        )
    )


@router.post(
    "/assignments/{assignment_id}/attachments",
    response_model=FileMeta,
    status_code=status.HTTP_201_CREATED,
)
async def upload_assignment_attachment_endpoint(
    request: Request, assignment_id: UUID, ctx: Teacher, filename: UploadName
) -> FileMeta:
    return await _upload_material(request, ctx, "assignment", assignment_id, filename)


@router.post(
    "/announcements/{announcement_id}/attachments",
    response_model=FileMeta,
    status_code=status.HTTP_201_CREATED,
)
async def upload_announcement_attachment_endpoint(
    request: Request, announcement_id: UUID, ctx: Teacher, filename: UploadName
) -> FileMeta:
    return await _upload_material(request, ctx, "announcement", announcement_id, filename)


@router.get("/submission-files/{file_id}/content", response_class=StreamingResponse)
def download_submission_file_endpoint(
    request: Request, file_id: UUID, ctx: Participant
) -> StreamingResponse:
    return _download(request, ctx, "submission", file_id)


@router.get("/attachments/{file_id}/content", response_class=StreamingResponse)
def download_attachment_endpoint(
    request: Request, file_id: UUID, ctx: Participant
) -> StreamingResponse:
    return _download(request, ctx, "material", file_id)


@router.delete("/submission-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission_file_endpoint(request: Request, file_id: UUID, ctx: GatedStudent) -> None:
    _write(request, ctx)
    file_service.remove_submission_file(ctx.session, file_id)


@router.delete("/attachments/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment_endpoint(request: Request, file_id: UUID, ctx: Teacher) -> None:
    _write(request, ctx)
    file_service.remove_material(ctx.session, file_id)


# ── Phase 6b: links on a piece of work, and viewing in the browser ──────────


@router.post(
    "/assignments/{assignment_id}/submission/links",
    response_model=LinkMeta,
    status_code=status.HTTP_201_CREATED,
)
def add_link_endpoint(
    request: Request, assignment_id: UUID, payload: LinkRequest, ctx: GatedStudent
) -> LinkMeta:
    _write(request, ctx)
    return LinkMeta(**links.add_link(ctx.session, assignment_id, payload.url))


@router.delete("/submission-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link_endpoint(request: Request, link_id: UUID, ctx: GatedStudent) -> None:
    _write(request, ctx)
    links.remove_link(ctx.session, link_id)


def _view(
    request: Request, response: Response, ctx: AuthContext, kind: str, file_id: UUID
) -> ViewLink:
    enforce(request, bucket="file_download", limit=FILE_DOWNLOAD_LIMIT, subject=str(ctx.user_id))
    # The body is a five-minute pass to the file: never cached on the way.
    response.headers["Cache-Control"] = "private, no-store"
    return ViewLink(**file_service.view_link(ctx.session, kind, file_id))  # RLS decides


@router.get("/submission-files/{file_id}/view", response_model=ViewLink)
def view_submission_file_endpoint(
    request: Request, response: Response, file_id: UUID, ctx: Participant
) -> ViewLink:
    return _view(request, response, ctx, "submission", file_id)


@router.get("/attachments/{file_id}/view", response_model=ViewLink)
def view_attachment_endpoint(
    request: Request, response: Response, file_id: UUID, ctx: Participant
) -> ViewLink:
    return _view(request, response, ctx, "material", file_id)


# ── Phase 7: the class chat ─────────────────────────────────────────────────


@router.get("/spaces/{space_id}/messages", response_model=ChatPage)
def poll_messages_endpoint(
    request: Request,
    space_id: UUID,
    ctx: Participant,
    # The previous answer's `server_time`: a catch-up poll.
    after: AwareDatetime | None = None,
    # The previous answer's `older_cursor`: the page before it.
    before: Annotated[str | None, Query(max_length=200)] = None,
) -> ChatPage:
    enforce(request, bucket="chat_poll", limit=CHAT_POLL_LIMIT, subject=str(ctx.user_id))
    return ChatPage(**chat.poll(ctx.session, space_id, after, before))


@router.post(
    "/spaces/{space_id}/messages", response_model=ChatMessage, status_code=status.HTTP_201_CREATED
)
def post_message_endpoint(
    request: Request, space_id: UUID, payload: MessageCreateRequest, ctx: Participant
) -> ChatMessage:
    enforce(request, bucket="chat_post", limit=CHAT_POST_LIMIT, subject=str(ctx.user_id))
    return ChatMessage(**chat.post(ctx.session, ctx.user_id, space_id, payload.body))


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message_endpoint(request: Request, message_id: UUID, ctx: Teacher) -> None:
    _write(request, ctx)
    chat.delete(ctx.session, ctx.user_id, message_id)


@router.put("/spaces/{space_id}/members/{student_id}/mute", status_code=status.HTTP_204_NO_CONTENT)
def mute_member_endpoint(
    request: Request, space_id: UUID, student_id: UUID, payload: MuteRequest, ctx: Teacher
) -> None:
    _write(request, ctx)
    chat.set_muted(ctx.session, ctx.user_id, space_id, student_id, payload.muted)
