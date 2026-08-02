from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    AuthContext,
    authenticated,
    read_refresh_token_cookie,
    require_role,
)
from app.auth.schemas import (
    AccessTokenResponse,
    EnumsResponse,
    GuardianConfirmRequest,
    GuardianConfirmResponse,
    GuardianInviteRequest,
    GuardianInviteResponse,
    GuardianStatusResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.auth.service import (
    enums,
    guardian_confirm,
    guardian_invite,
    guardian_status,
    login,
    logout,
    me,
    refresh,
    register,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import (
    GUARDIAN_CONFIRM_LIMIT,
    GUARDIAN_INVITE_LIMIT,
    GUARDIAN_STATUS_LIMIT,
    LOGIN_LIMIT,
    REFRESH_LIMIT,
    REGISTER_LIMIT,
    enforce,
)
from app.models.enums import UserRole

router = APIRouter(tags=["auth"])

# NOTE: no route here depends on `get_service_db`. The pre-authentication paths
# (login, refresh) reach the rows they need through the narrow SECURITY DEFINER
# functions in migration 20260802140000; everything else runs under Row Level
# Security as app_backend. If a new endpoint appears to need the service
# session, that is the signal to add another narrow function instead.


@router.post(
    "/auth/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_endpoint(
    request: Request, payload: RegisterRequest, db: Session = Depends(get_db)
) -> RegisterResponse:
    enforce(request, bucket="register", limit=REGISTER_LIMIT)
    result = register(db, payload)
    return RegisterResponse(**result)


@router.post("/auth/login", response_model=LoginResponse)
def login_endpoint(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    # The brute-force surface of the whole system. `429 RATE_LIMITED` was in the
    # contract and in errors.py from the start, and nothing enforced it.
    enforce(request, bucket="login", limit=LOGIN_LIMIT)
    return login(db, payload)


@router.post("/auth/refresh", response_model=AccessTokenResponse)
def refresh_endpoint(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    enforce(request, bucket="refresh", limit=REFRESH_LIMIT)
    old_token = read_refresh_token_cookie(request)
    result = refresh(db, old_token)
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=settings.is_production,
        # Lax is correct while the site and the API share a registrable domain.
        # If they are ever split across sites this must become
        # `SameSite=None; Secure`, or the cookie stops being sent and refresh
        # fails in production only.
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86400,
        # Scoped, so the cookie is not attached to every API call.
        path="/api/auth/refresh",
    )
    # The rotated token goes ONLY into the httpOnly cookie. It is deliberately
    # absent from AccessTokenResponse so it cannot reach a log or a client store.
    return AccessTokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(ctx: Annotated[AuthContext, Depends(authenticated)]) -> None:
    logout(ctx.session, ctx.user_id)
    return


@router.get("/auth/me", response_model=MeResponse)
def me_endpoint(ctx: Annotated[AuthContext, Depends(authenticated)]) -> MeResponse:
    return MeResponse(**me(ctx.session, ctx.user_id))


@router.get("/reference/enums", response_model=EnumsResponse)
def enums_endpoint(db: Session = Depends(get_db)) -> EnumsResponse:
    # Readable as app_backend since migration 20260802140000 gave the reference
    # tables a SELECT policy. Before that they were deny-all, which is why this
    # endpoint needed a privileged connection.
    return EnumsResponse(**enums(db))


# ---------------------------------------------------------------------------
# Guardian gate (RBAC-002). Role-gated (NOT guardian-gated — a gated student
# must be able to reach these). invite/status are student-only; confirm is
# parent-only, so a student can never confirm their own gate through the API.
# ---------------------------------------------------------------------------


@router.post("/auth/guardian/invite", response_model=GuardianInviteResponse)
def guardian_invite_endpoint(
    request: Request,
    payload: GuardianInviteRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> GuardianInviteResponse:
    enforce(request, bucket="guardian_invite", limit=GUARDIAN_INVITE_LIMIT)
    return GuardianInviteResponse(**guardian_invite(ctx.session, ctx.user_id, payload))


@router.get("/auth/guardian/status", response_model=GuardianStatusResponse)
def guardian_status_endpoint(
    request: Request,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> GuardianStatusResponse:
    enforce(request, bucket="guardian_status", limit=GUARDIAN_STATUS_LIMIT)
    return GuardianStatusResponse(**guardian_status(ctx.session, ctx.user_id))


@router.post("/auth/guardian/confirm", response_model=GuardianConfirmResponse)
def guardian_confirm_endpoint(
    request: Request,
    payload: GuardianConfirmRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.parent.value))],
) -> GuardianConfirmResponse:
    enforce(request, bucket="guardian_confirm", limit=GUARDIAN_CONFIRM_LIMIT)
    return GuardianConfirmResponse(**guardian_confirm(ctx.session, ctx.user_id, payload))
