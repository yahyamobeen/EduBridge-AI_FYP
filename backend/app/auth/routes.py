from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    AuthContext,
    authenticated,
    clear_refresh_cookie,
    read_refresh_token_cookie,
    require_role,
    set_refresh_cookie,
)
from app.auth.schemas import (
    AccessTokenResponse,
    EmailResendRequest,
    EmailVerifyRequest,
    EmailVerifyResponse,
    EnumsResponse,
    GuardianConfirmRequest,
    GuardianConfirmResponse,
    GuardianInviteRequest,
    GuardianInviteResponse,
    GuardianStatusResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MeUpdateRequest,
    PasswordChangeRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RegisterRequest,
    RegisterResponse,
    TwoFactorConfirmRequest,
    TwoFactorConfirmResponse,
    TwoFactorEnrollRequest,
    TwoFactorEnrollResponse,
    TwoFactorResendRequest,
    TwoFactorResendResponse,
    TwoFactorStatusResponse,
    TwoFactorVerifyRequest,
    TwoFactorVerifyResponse,
)
from app.auth.service import (
    change_password,
    enums,
    forgot_password,
    guardian_confirm,
    guardian_invite,
    guardian_status,
    login,
    logout,
    me,
    refresh,
    register,
    resend_email_verification,
    reset_password,
    two_factor_confirm,
    two_factor_enroll,
    two_factor_resend,
    two_factor_status,
    two_factor_verify,
    update_me,
    verify_email,
)
from app.core.db import get_db
from app.core.ratelimit import (
    ADMIN_LOGIN_LIMIT,
    EMAIL_RESEND_LIMIT,
    EMAIL_VERIFY_LIMIT,
    GUARDIAN_CONFIRM_LIMIT,
    GUARDIAN_INVITE_LIMIT,
    GUARDIAN_STATUS_LIMIT,
    LOGIN_LIMIT,
    ME_UPDATE_LIMIT,
    PASSWORD_CHANGE_LIMIT,
    PASSWORD_FORGOT_LIMIT,
    PASSWORD_RESET_LIMIT,
    REFRESH_LIMIT,
    REGISTER_LIMIT,
    TWO_FA_CONFIRM_LIMIT,
    TWO_FA_ENROLL_LIMIT,
    TWO_FA_RESEND_LIMIT,
    TWO_FA_STATUS_LIMIT,
    TWO_FA_VERIFY_LIMIT,
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
    # Administrators are refused here with an INDISTINGUISHABLE 401 — see the
    # role check in `login()` for why that is the requirement and not merely the
    # implementation.
    return login(db, payload)


@router.post("/auth/admin/login", response_model=LoginResponse)
def admin_login_endpoint(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Segregated administrator authentication (prd.md FR-A2a).

    Reached through an unlisted path that the frontend rewrites to its login
    page; the path is a server-only environment variable and never enters the
    browser bundle. ⚠️ THE PATH IS NOT THE CONTROL — this endpoint is. It
    refuses every non-administrator with the same 401 as a wrong password, so
    knowing the URL buys an attacker nothing.

    ONLY the entry point is segregated. `/auth/2fa/verify`, `/auth/2fa/resend`,
    `/auth/refresh` and `/auth/logout` are deliberately shared: the challenge
    token this endpoint issues is already bound to the user who will use it, so
    a second set of admin-only continuations would add no security and would
    fork a flow that is currently tested once. Do not "fix" that later.
    """
    # ITS OWN BUCKET. Sharing `login`'s would let anyone lock administrators out
    # by hammering the public endpoint until the shared counter is exhausted.
    enforce(request, bucket="admin_login", limit=ADMIN_LOGIN_LIMIT)
    return login(db, payload, admin_portal=True)


@router.post("/auth/refresh", response_model=AccessTokenResponse)
def refresh_endpoint(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    enforce(request, bucket="refresh", limit=REFRESH_LIMIT)
    old_token = read_refresh_token_cookie(request)
    result = refresh(db, old_token)
    set_refresh_cookie(response, result["refresh_token"])
    # The rotated token goes ONLY into the httpOnly cookie. It is deliberately
    # absent from AccessTokenResponse so it cannot reach a log or a client store.
    return AccessTokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(
    response: Response, ctx: Annotated[AuthContext, Depends(authenticated)]
) -> None:
    logout(ctx.session, ctx.user_id)
    # Finding A2. Revoking the rows without clearing the cookie left the browser
    # presenting a revoked token on the next refresh, which reuse detection
    # correctly read as theft -- so every sign-out revoked the family again and
    # wrote a false `refresh_token_reuse_detected` audit row.
    clear_refresh_cookie(response)
    return


@router.get("/auth/me", response_model=MeResponse)
def me_endpoint(ctx: Annotated[AuthContext, Depends(authenticated)]) -> MeResponse:
    return MeResponse(**me(ctx.session, ctx.user_id))


# ---------------------------------------------------------------------------
# FR-A8 — manage own account (prd.md:450, tdd.md §3.1). Role: ALL FOUR, so none
# of these is behind `require_role`.
#
# All three pass `subject=` to the limiter, for the reason in ratelimit.py: they
# are authenticated, and an address key would make one student in a shared
# school lab spend the whole building's allowance.
# ---------------------------------------------------------------------------


@router.patch("/auth/me", response_model=MeResponse)
def me_update_endpoint(
    request: Request,
    payload: MeUpdateRequest,
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> MeResponse:
    """
    `full_name` and `language_pref` only.

    `board`, `class_level` and `student_group` are absent from `MeUpdateRequest`
    AND unwritable at the database (20260816160000, finding B4) — a student who
    could set their own class would leave the parental-consent gate for ever.
    Two layers on purpose: this one gives a clear 400, that one holds if this
    model ever grows a field by accident.
    """
    enforce(request, bucket="me_update", limit=ME_UPDATE_LIMIT, subject=str(ctx.user_id))
    return MeResponse(**update_me(ctx.session, ctx.user_id, payload))


@router.post("/auth/password/change", status_code=status.HTTP_204_NO_CONTENT)
def password_change_endpoint(
    request: Request,
    payload: PasswordChangeRequest,
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> None:
    """
    Requires the current password (tdd.md:194, user-stories.md:115).

    204 rather than a body: the count of sessions ended is written to
    `audit_log`, and returning it would tell a caller who just proved they know
    the password something they can already learn, at the cost of a shape to
    maintain.

    ⚠️ EVERY REFRESH TOKEN IS REVOKED, including the caller's own. The client
    must expect its next refresh to fail and treat that as "sign in again",
    which is the intended behaviour and not an error to paper over. Access
    tokens survive up to their TTL; closing that window is Phase 4.
    """
    enforce(
        request, bucket="password_change", limit=PASSWORD_CHANGE_LIMIT, subject=str(ctx.user_id)
    )
    change_password(ctx.session, ctx.user_id, payload)


@router.get("/auth/2fa/status", response_model=TwoFactorStatusResponse)
def two_factor_status_endpoint(
    request: Request,
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> TwoFactorStatusResponse:
    """
    Own second-factor state. NEVER the secret (tdd.md:195) — the view it reads
    was built without that column, so the guarantee is structural.
    """
    enforce(request, bucket="2fa_status", limit=TWO_FA_STATUS_LIMIT, subject=str(ctx.user_id))
    return TwoFactorStatusResponse(**two_factor_status(ctx.session, ctx.user_id))


@router.get("/reference/enums", response_model=EnumsResponse)
def enums_endpoint(db: Session = Depends(get_db)) -> EnumsResponse:
    # Readable as app_backend since migration 20260802140000 gave the reference
    # tables a SELECT policy. Before that they were deny-all, which is why this
    # endpoint needed a privileged connection.
    return EnumsResponse(**enums(db))


# ============================================================================
# KAN-10b — 2FA Enrolment, Challenge, Email Verification, Password Reset
# ============================================================================


@router.post("/auth/2fa/enroll", response_model=TwoFactorEnrollResponse)
def two_factor_enroll_endpoint(
    request: Request,
    payload: TwoFactorEnrollRequest,
    db: Session = Depends(get_db),
):
    enforce(request, bucket="2fa_enroll", limit=TWO_FA_ENROLL_LIMIT)
    return two_factor_enroll(db, payload)


@router.post("/auth/2fa/confirm", response_model=TwoFactorConfirmResponse)
def two_factor_confirm_endpoint(
    request: Request,
    response: Response,
    payload: TwoFactorConfirmRequest,
    db: Session = Depends(get_db),
) -> TwoFactorConfirmResponse:
    enforce(request, bucket="2fa_confirm", limit=TWO_FA_CONFIRM_LIMIT)
    result = two_factor_confirm(db, payload)

    # The refresh token goes ONLY into the httpOnly cookie; it is deliberately
    # absent from the response model so it cannot reach a log or a client store.
    set_refresh_cookie(response, result["refresh_token"])

    # Return response without refresh_token
    return TwoFactorConfirmResponse(
        two_factor=result["two_factor"],
        backup_codes=result["backup_codes"],
        onboarding_state=result["onboarding_state"],
        access_token=result["access_token"],
        expires_in=result["expires_in"],
    )


@router.post("/auth/2fa/verify", response_model=TwoFactorVerifyResponse)
def two_factor_verify_endpoint(
    request: Request,
    response: Response,
    payload: TwoFactorVerifyRequest,
    db: Session = Depends(get_db),
) -> TwoFactorVerifyResponse:
    enforce(request, bucket="2fa_verify", limit=TWO_FA_VERIFY_LIMIT)
    result = two_factor_verify(db, payload)

    # The refresh token goes ONLY into the httpOnly cookie; it is deliberately
    # absent from the response model so it cannot reach a log or a client store.
    set_refresh_cookie(response, result["refresh_token"])

    # Return response without refresh_token
    return TwoFactorVerifyResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        onboarding_state=result["onboarding_state"],
    )


@router.post("/auth/2fa/resend", response_model=TwoFactorResendResponse)
def two_factor_resend_endpoint(
    request: Request,
    payload: TwoFactorResendRequest,
    db: Session = Depends(get_db),
) -> TwoFactorResendResponse:
    enforce(request, bucket="2fa_resend", limit=TWO_FA_RESEND_LIMIT)
    result = two_factor_resend(db, payload)
    return TwoFactorResendResponse(**result)


@router.post("/auth/email/verify", response_model=EmailVerifyResponse)
def email_verify_endpoint(
    request: Request,
    payload: EmailVerifyRequest,
    db: Session = Depends(get_db),
) -> EmailVerifyResponse:
    enforce(request, bucket="email_verify", limit=EMAIL_VERIFY_LIMIT)
    result = verify_email(db, payload)
    return EmailVerifyResponse(**result)


@router.post("/auth/email/resend", status_code=status.HTTP_204_NO_CONTENT)
def email_resend_endpoint(
    request: Request,
    payload: EmailResendRequest,
    db: Session = Depends(get_db),
) -> None:
    enforce(request, bucket="email_resend", limit=EMAIL_RESEND_LIMIT)
    resend_email_verification(db, payload)


@router.post("/auth/password/forgot", status_code=status.HTTP_204_NO_CONTENT)
def password_forgot_endpoint(
    request: Request,
    payload: PasswordForgotRequest,
    db: Session = Depends(get_db),
) -> None:
    enforce(request, bucket="password_forgot", limit=PASSWORD_FORGOT_LIMIT)
    forgot_password(db, payload)


@router.post("/auth/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def password_reset_endpoint(
    request: Request,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
) -> None:
    enforce(request, bucket="password_reset", limit=PASSWORD_RESET_LIMIT)
    reset_password(db, payload)


# ---------------------------------------------------------------------------
# Guardian gate (RBAC-002). Role-gated (NOT guardian-gated — a gated student
# must be able to reach these). invite/status are student-only; confirm is
# parent-only, so a student can never confirm their own gate through the API.
#
# All three pass `subject=` to the limiter so the bucket is per-USER. These are
# authenticated, and a shared school-lab or carrier-NAT address would otherwise
# make one student's polling spend the whole cohort's allowance (ratelimit.py).
# ---------------------------------------------------------------------------


@router.post("/auth/guardian/invite", response_model=GuardianInviteResponse)
def guardian_invite_endpoint(
    request: Request,
    payload: GuardianInviteRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> GuardianInviteResponse:
    enforce(
        request,
        bucket="guardian_invite",
        limit=GUARDIAN_INVITE_LIMIT,
        subject=str(ctx.user_id),
    )
    return GuardianInviteResponse(**guardian_invite(ctx.session, ctx.user_id, payload))


@router.get("/auth/guardian/status", response_model=GuardianStatusResponse)
def guardian_status_endpoint(
    request: Request,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.student.value))],
) -> GuardianStatusResponse:
    enforce(
        request,
        bucket="guardian_status",
        limit=GUARDIAN_STATUS_LIMIT,
        subject=str(ctx.user_id),
    )
    return GuardianStatusResponse(**guardian_status(ctx.session, ctx.user_id))


@router.post("/auth/guardian/confirm", response_model=GuardianConfirmResponse)
def guardian_confirm_endpoint(
    request: Request,
    payload: GuardianConfirmRequest,
    ctx: Annotated[AuthContext, Depends(require_role(UserRole.parent.value))],
) -> GuardianConfirmResponse:
    enforce(
        request,
        bucket="guardian_confirm",
        limit=GUARDIAN_CONFIRM_LIMIT,
        subject=str(ctx.user_id),
    )
    return GuardianConfirmResponse(**guardian_confirm(ctx.session, ctx.user_id, payload))
