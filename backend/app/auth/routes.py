from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, authenticated, read_refresh_token_cookie
from app.auth.schemas import (
    AccessTokenResponse,
    BackupCodesRegenerateResponse,
    EmailResendRequest,
    EmailVerifyRequest,
    EmailVerifyResponse,
    EnumsResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
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
    TwoFactorVerifyRequest,
    TwoFactorVerifyResponse,
)
from app.auth.service import (
    enums,
    forgot_password,
    login,
    logout,
    me,
    refresh,
    register,
    resend_email_verification,
    reset_password,
    two_factor_confirm,
    two_factor_enroll,
    two_factor_regenerate_backup_codes,
    two_factor_resend,
    two_factor_verify,
    verify_email,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import (
    BACKUP_CODES_REGENERATE_LIMIT,
    EMAIL_RESEND_LIMIT,
    EMAIL_VERIFY_LIMIT,
    LOGIN_LIMIT,
    PASSWORD_FORGOT_LIMIT,
    PASSWORD_RESET_LIMIT,
    REFRESH_LIMIT,
    REGISTER_LIMIT,
    TWO_FA_CONFIRM_LIMIT,
    TWO_FA_ENROLL_LIMIT,
    TWO_FA_RESEND_LIMIT,
    TWO_FA_VERIFY_LIMIT,
    enforce,
)

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


# ============================================================================
# KAN-10b — 2FA Enrolment, Challenge, Email Verification, Password Reset
# ============================================================================


@router.post("/auth/2fa/enroll", response_model=TwoFactorEnrollResponse)
def two_factor_enroll_endpoint(
    request: Request,
    payload: TwoFactorEnrollRequest,
    db: Session = Depends(get_db),
) -> TwoFactorEnrollResponse:
    enforce(request, bucket="2fa_enroll", limit=TWO_FA_ENROLL_LIMIT)
    result = two_factor_enroll(db, payload)
    return TwoFactorEnrollResponse(**result)


@router.post("/auth/2fa/confirm", response_model=TwoFactorConfirmResponse)
def two_factor_confirm_endpoint(
    request: Request,
    response: Response,
    payload: TwoFactorConfirmRequest,
    db: Session = Depends(get_db),
) -> TwoFactorConfirmResponse:
    enforce(request, bucket="2fa_confirm", limit=TWO_FA_CONFIRM_LIMIT)
    result = two_factor_confirm(db, payload)

    # Set refresh token as httpOnly cookie
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86400,
        path="/api/auth/refresh",
    )

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

    # Set refresh token as httpOnly cookie
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86400,
        path="/api/auth/refresh",
    )

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


@router.post(
    "/auth/2fa/backup-codes",
    response_model=BackupCodesRegenerateResponse,
)
def backup_codes_regenerate_endpoint(
    request: Request,
    ctx: Annotated[AuthContext, Depends(authenticated)],
) -> BackupCodesRegenerateResponse:
    enforce(request, bucket="backup_codes_regenerate", limit=BACKUP_CODES_REGENERATE_LIMIT)
    result = two_factor_regenerate_backup_codes(ctx.session, ctx.user_id)
    return BackupCodesRegenerateResponse(**result)
