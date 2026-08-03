from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.gate import is_guardian_gate_pending
from app.auth.security import decode_access_token
from app.core.db import SessionLocal, set_current_user_id
from app.core.errors import forbidden_scope, gate_pending, unauthenticated
from app.models.enums import UserRole

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """An authenticated request: a session already bound to the acting user."""

    session: Session
    user_id: UUID
    role: str


def authenticated(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Generator[AuthContext, None, None]:
    """
    The single dependency for every authenticated route.

    It verifies the bearer token, binds the user to the transaction, and only
    then reads the row — so the identity check itself runs UNDER Row Level
    Security instead of around it. `app_user_self_read` is
    `USING (id = app.current_user_id())`, which is satisfied once the user is
    bound, so answering "does this user exist and is it active" needs no
    privileged connection at all.

    THIS REPLACED A DESIGN THAT LEAKED IN TWO WAYS. The previous version
    resolved the token against an RLS-BYPASSING service session, so every
    authenticated request opened a connection with all policies disabled before
    the real one was even created; and it handed the user id to the session
    factory through `request.state`, which made correctness depend on FastAPI
    resolving two parameters in declaration order. Swapping those two arguments
    in a route signature would have left the GUC unset and returned zero rows
    everywhere, with nothing failing loudly.

    One session per request now, and the ordering hazard is gone because there
    is only one dependency to order.
    """
    if credentials is None:
        raise unauthenticated("Missing bearer token.")

    try:
        user_id = decode_access_token(credentials.credentials)
    except ValueError:
        raise unauthenticated("Invalid or expired access token.") from None

    session = SessionLocal()
    try:
        # Bind first, read second. The read proves the token's subject is a
        # real, active user; RLS is what stops it being anyone else's row.
        set_current_user_id(session, user_id)

        row = (
            session.execute(
                text("SELECT status, role FROM app_user WHERE id = :uid AND deleted_at IS NULL"),
                {"uid": user_id},
            )
            .mappings()
            .one_or_none()
        )
        # A signed token for a deleted or suspended account is not a session.
        # Deliberately the same message as a malformed token: which of the two
        # it was is not the caller's business.
        if row is None or row["status"] != "active":
            raise unauthenticated("Invalid or expired access token.")

        yield AuthContext(session=session, user_id=user_id, role=str(row["role"]))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def read_refresh_token_cookie(request: Request) -> str:
    token = request.cookies.get("refresh_token")
    if not token:
        raise unauthenticated("Missing refresh token.")
    return token


# ----------------------------------------------------------------------------
# RBAC-002: the role / subject-scope / guardian-gate dependencies. Each wraps
# `authenticated`, so the user is bound and the identity check has already run
# UNDER RLS before any of these read another row. None of them opens a
# privileged connection — every read satisfies an existing policy as the acting
# user (app_user_self_read, tss_read, student_profile_read,
# guardian_link_participants).
# ----------------------------------------------------------------------------


def require_role(*roles: str):
    """
    The first gate: role, not subject. A non-admin is never allowed through a
    role they lack, so an endpoint that takes `require_role("parent")` is
    unreachable by a student before any subject logic runs.
    """

    def _dep(ctx: Annotated[AuthContext, Depends(authenticated)]) -> AuthContext:
        if ctx.role not in roles:
            raise forbidden_scope()
        return ctx

    return _dep


def require_subject_scope(
    subject_id: UUID,
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> AuthContext:
    """
    Teacher-only. The acting teacher must have a `teacher_subject_scope` row for
    the subject — readable under `tss_read` (teacher_id = current user). Zero
    rows means the teacher does not teach this subject: 403 FORBIDDEN_SCOPE.
    Exported for the classroom routes to wire (scope D); no classroom endpoint
    exists in this repo yet.

    USE IT AS `Depends(require_subject_scope)` ON A ROUTE THAT DECLARES
    `{subject_id}` IN ITS PATH. FastAPI resolves `subject_id` from the request,
    which is the entire point: this was previously a factory taking the id as a
    closure argument, fixed when the route was DEFINED, so it could never see a
    per-request path parameter. Written as a factory it also read as though it
    worked —

        @app.get("/subjects/{subject_id}/roster")
        def roster(subject_id: UUID, ctx = Depends(require_subject_scope(subject_id))):

    — because Python evaluates default arguments in the ENCLOSING scope at `def`
    time, so `subject_id` there is whatever module-level name happens to exist,
    never the path parameter. A route with no `{subject_id}` segment will make
    FastAPI demand it as a query parameter instead, which fails visibly.
    """
    row = ctx.session.execute(
        text("SELECT 1 FROM teacher_subject_scope WHERE teacher_id = :tid AND subject_id = :sid"),
        {"tid": ctx.user_id, "sid": subject_id},
    ).one_or_none()
    if row is None:
        raise forbidden_scope()
    return ctx


def require_guardian_verified(
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> AuthContext:
    """
    The parental-consent gate for learning endpoints (prd.md §4.3). Applied to
    /api/tutor/*, /api/practice/adaptive, /api/quiz/*/attempts* and
    /api/reports/*. The DECISION is the pure function in gate.py; this
    dependency only supplies the inputs, all read under RLS as the student:
    class_level from student_profile, representative guardian status from
    guardian_link. Class 11-12 students, teachers, parents and admins pass
    without any guardian requirement.
    """
    if ctx.role != UserRole.student.value:
        return ctx

    profile = (
        ctx.session.execute(
            text("SELECT class_level FROM student_profile WHERE user_id = :uid"),
            {"uid": ctx.user_id},
        )
        .mappings()
        .one_or_none()
    )
    link = (
        ctx.session.execute(
            text(
                "SELECT status FROM guardian_link "
                "WHERE student_id = :uid "
                "ORDER BY (status = 'verified') DESC, created_at DESC "
                "LIMIT 1"
            ),
            {"uid": ctx.user_id},
        )
        .mappings()
        .one_or_none()
    )

    guardian_status = str(link["status"]) if link is not None else None
    if is_guardian_gate_pending(
        is_student=True,
        class_level=profile["class_level"] if profile is not None else None,
        guardian_status=guardian_status,
    ):
        raise gate_pending()
    return ctx
