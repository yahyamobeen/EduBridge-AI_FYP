from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, read_refresh_token_cookie
from app.auth.schemas import (
    AccessTokenResponse,
    EnumsResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.auth.service import enums, login, logout, me, refresh, register
from app.core.config import get_settings
from app.core.db import get_db, get_service_db

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_endpoint(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    result = register(db, payload)
    return RegisterResponse(**result)


@router.post("/auth/login", response_model=LoginResponse)
def login_endpoint(payload: LoginRequest, db: Session = Depends(get_service_db)):
    return login(db, payload)


@router.post("/auth/refresh", response_model=AccessTokenResponse)
def refresh_endpoint(
    request: Request,
    response: Response,
    db: Session = Depends(get_service_db),
) -> AccessTokenResponse:
    old_token = read_refresh_token_cookie(request)
    result = refresh(db, old_token)
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86400,
        path="/api/auth/refresh",
    )
    return AccessTokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(
    user_id: Annotated[UUID, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> None:
    logout(db, user_id)
    return


@router.get("/auth/me", response_model=MeResponse)
def me_endpoint(
    user_id: Annotated[UUID, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> MeResponse:
    return MeResponse(**me(db, user_id))


@router.get("/reference/enums", response_model=EnumsResponse)
def enums_endpoint(db: Session = Depends(get_service_db)) -> EnumsResponse:
    result = enums(db)
    return EnumsResponse(**result)
