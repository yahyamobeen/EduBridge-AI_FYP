from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.core.db import get_service_db
from app.core.errors import unauthenticated

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service_db: Annotated[Session, Depends(get_service_db)],
) -> UUID:
    if credentials is None:
        raise unauthenticated("Missing bearer token.")
    try:
        user_id = decode_access_token(credentials.credentials)
    except ValueError:
        raise unauthenticated("Invalid or expired access token.") from None
    row = (
        service_db.execute(
            text("SELECT id, status FROM app_user WHERE id = :uid AND deleted_at IS NULL"),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["status"] != "active":
        raise unauthenticated("Invalid or expired access token.")
    request.state.user_id = user_id
    return user_id


def read_refresh_token_cookie(request: Request) -> str:
    token = request.cookies.get("refresh_token")
    if not token:
        raise unauthenticated("Missing refresh token.")
    return token
