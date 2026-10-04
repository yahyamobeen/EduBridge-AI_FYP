"""
Classroom routes — `tdd.md` §3.6, classroom Phase 2 (spaces, codes, membership).

Thin by design: rate limit first, then one service call. Who may call is
decided by the dependency on each route (app/classroom/dependencies.py); which
SPACE they may touch is decided by the database, through the service.

Like `app/auth/routes.py`, no route here depends on `get_service_db`. If a new
endpoint appears to need it, add a narrow `app.*` function instead.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.auth.dependencies import AuthContext, authenticated
from app.classroom import announcements, service
from app.classroom.dependencies import AnyStudent, GatedStudent, Participant, Teacher
from app.classroom.schemas import (
    Announcement,
    AnnouncementCreateRequest,
    AnnouncementPage,
    AnnouncementUpdateRequest,
    JoinCodeRequest,
    JoinCodeResponse,
    JoinRequest,
    JoinResponse,
    PeopleResponse,
    SpaceCreateRequest,
    SpaceDetail,
    SpaceListResponse,
    SpaceUpdateRequest,
    SubjectsResponse,
)
from app.core.ratelimit import (
    CLASSROOM_JOIN_LIMIT,
    CLASSROOM_READ_LIMIT,
    CLASSROOM_WRITE_LIMIT,
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
