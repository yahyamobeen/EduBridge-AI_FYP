from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import generate_opaque_token, hash_token
from app.core.config import get_settings
from app.models.enums import TokenKind
from app.models.identity import AuthToken


def issue_refresh_token(
    session: Session, user_id: UUID, *, now: datetime | None = None
) -> tuple[str, AuthToken]:
    settings = get_settings()
    now = now or datetime.now(UTC)
    plain = generate_opaque_token()
    row = AuthToken(
        user_id=user_id,
        kind=TokenKind.refresh.value,
        token_hash=hash_token(plain),
        revoked=False,
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(row)
    session.flush()
    return plain, row


def _find_token(session: Session, token_hash: str) -> AuthToken | None:
    stmt = select(AuthToken).where(AuthToken.token_hash == token_hash)
    return session.execute(stmt).scalar_one_or_none()


def rotate_refresh_token(
    session: Session, plain_old: str, *, now: datetime | None = None
) -> tuple[str, AuthToken] | None:
    now = now or datetime.now(UTC)
    row = _find_token(session, hash_token(plain_old))
    if row is None or row.revoked or row.expires_at <= now or row.kind != TokenKind.refresh.value:
        return None
    row.revoked = True
    plain_new, new_row = issue_refresh_token(session, row.user_id, now=now)
    return plain_new, new_row


def revoke_user_tokens(session: Session, user_id: UUID, *, kind: str | None = None) -> int:
    from sqlalchemy import update

    stmt = (
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.revoked.is_(False))
        .values(revoked=True)
    )
    if kind is not None:
        stmt = stmt.where(AuthToken.kind == kind)
    result = session.execute(stmt)
    return result.rowcount or 0


def issue_pending_token(
    session: Session,
    user_id: UUID,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> tuple[str, AuthToken]:
    now = now or datetime.now(UTC)
    plain = generate_opaque_token()
    row = AuthToken(
        user_id=user_id,
        kind=TokenKind.two_factor_pending.value,
        token_hash=hash_token(plain),
        revoked=False,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    session.add(row)
    session.flush()
    return plain, row
