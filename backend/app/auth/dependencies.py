from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.core.db import SessionLocal, set_current_user_id
from app.core.errors import unauthenticated

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """An authenticated request: a session already bound to the acting user."""

    session: Session
    user_id: UUID


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
                text("SELECT status FROM app_user WHERE id = :uid AND deleted_at IS NULL"),
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

        yield AuthContext(session=session, user_id=user_id)
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
