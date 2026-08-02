from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.auth.security import generate_opaque_token, hash_token
from app.core.config import get_settings
from app.models.enums import TokenKind
from app.models.identity import AuthToken

# ----------------------------------------------------------------------------
# Refresh and challenge tokens are handled BEFORE a session exists, so the
# owner-scoped `auth_token_owner` policy cannot be satisfied — there is no
# `app.current_user_id()` to match against yet. These paths therefore go
# through the narrow SECURITY DEFINER functions from migration 20260802140000,
# which expose exactly these columns and nothing else, rather than through an
# RLS-bypassing connection.
#
# Anything reachable AFTER authentication (logout) uses the ORM against the
# request's own bound session, where the policy applies normally.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredToken:
    id: UUID
    user_id: UUID
    kind: str
    revoked: bool
    expires_at: datetime


class RefreshTokenReuseError(Exception):
    """
    An already-revoked refresh token was presented.

    Rotation means a valid token is used exactly once, so a second use is not a
    mistake — it means two parties hold the same token and one of them is not
    the user. Raised so the caller can revoke the whole family rather than
    quietly returning 401 and letting the thief keep the chain they took.
    """

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        super().__init__("refresh token reuse detected")


def _insert_token(
    session: Session, user_id: UUID, kind: TokenKind, token_hash: str, expires_at: datetime
) -> UUID:
    return session.execute(
        text("SELECT app.insert_auth_token(:uid, CAST(:kind AS token_kind), :hash, :expires)"),
        {"uid": str(user_id), "kind": kind.value, "hash": token_hash, "expires": expires_at},
    ).scalar_one()


def issue_refresh_token(
    session: Session, user_id: UUID, *, now: datetime | None = None
) -> tuple[str, UUID]:
    """Returns the plaintext token (given to the client once) and the row id."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    plain = generate_opaque_token()
    row_id = _insert_token(
        session,
        user_id,
        TokenKind.refresh,
        hash_token(plain),
        now + timedelta(days=settings.refresh_token_ttl_days),
    )
    return plain, row_id


def find_token(session: Session, plain: str) -> StoredToken | None:
    row = (
        session.execute(
            text(
                "SELECT id, user_id, kind, revoked, expires_at FROM app.lookup_refresh_token(:hash)"
            ),
            {"hash": hash_token(plain)},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return StoredToken(
        id=row["id"],
        user_id=row["user_id"],
        kind=str(row["kind"]),
        revoked=row["revoked"],
        expires_at=row["expires_at"],
    )


def rotate_refresh_token(
    session: Session, plain_old: str, *, now: datetime | None = None
) -> tuple[str, UUID] | None:
    """
    Exchange a refresh token for a new one, revoking the old.

    Returns None when the token is unknown, expired or of the wrong kind.
    Raises `RefreshTokenReuseError` when the token exists but was already revoked —
    that is a different situation and deserves a different response.
    """
    now = now or datetime.now(UTC)
    stored = find_token(session, plain_old)

    if stored is None or stored.kind != TokenKind.refresh.value:
        return None
    if stored.revoked:
        raise RefreshTokenReuseError(stored.user_id)
    if stored.expires_at <= now:
        return None

    session.execute(
        text("SELECT app.revoke_auth_token(:id)"),
        {"id": str(stored.id)},
    )
    return issue_refresh_token(session, stored.user_id, now=now)


def revoke_refresh_family(session: Session, user_id: UUID) -> int:
    """
    Revoke every live refresh token for a user, and record why.

    Called on reuse detection. Without it, a stolen token that the attacker
    redeemed first leaves them with a valid rotating chain while the real user
    just sees 401s — and nothing anywhere records that it happened.
    """
    revoked = session.execute(
        text("SELECT app.revoke_refresh_family(:uid)"),
        {"uid": str(user_id)},
    ).scalar_one()

    # `audit_insert` is WITH CHECK (true), so this works without a bound user —
    # which matters, because this path runs before any session exists.
    session.execute(
        text(
            "INSERT INTO audit_log (actor_id, action, target) "
            "VALUES (:uid, 'refresh_token_reuse_detected', 'auth_token')"
        ),
        {"uid": str(user_id)},
    )
    return int(revoked)


def revoke_user_tokens(session: Session, user_id: UUID, *, kind: str | None = None) -> int:
    """
    Logout. Authenticated, so this runs under `auth_token_owner` on the
    request's own session and needs no privileged path.
    """
    stmt = (
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.revoked.is_(False))
        .values(revoked=True)
    )
    if kind is not None:
        stmt = stmt.where(AuthToken.kind == kind)
    return session.execute(stmt).rowcount or 0


def issue_challenge_token(
    session: Session,
    user_id: UUID,
    *,
    kind: TokenKind,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    """
    Issue an enrolment or pending 2FA token.

    `kind` is REQUIRED and must be `two_factor_enrollment` or
    `two_factor_pending`. Both used to be stored as `two_factor_pending`, which
    meant `/2fa/verify` — the endpoint that exchanges a pending token for a full
    session — could not tell one from the other, and would have accepted the
    longer-lived enrolment token. The kinds are the only thing that can enforce
    that boundary, so the caller has to say which it means.
    """
    if kind not in (TokenKind.two_factor_enrollment, TokenKind.two_factor_pending):
        raise ValueError(f"{kind} is not a 2FA challenge kind")

    now = now or datetime.now(UTC)
    plain = generate_opaque_token()
    _insert_token(session, user_id, kind, hash_token(plain), now + timedelta(seconds=ttl_seconds))
    return plain


def issue_guardian_invite_token(
    session: Session,
    student_id: UUID,
    *,
    ttl_seconds: int = 7 * 86400,
    now: datetime | None = None,
) -> str:
    """
    Issue the one-time invite a student's guardian redeems via
    POST /api/auth/guardian/confirm.

    Stored hashed under `kind = 'guardian_invite'` through the existing
    SECURITY DEFINER `app.insert_auth_token` (the pre-session pattern — the
    token's `user_id` is the STUDENT, the gate subject, and the parent resolves
    it by hash at confirm). 7 days by default. Deliberately NOT the
    `issue_challenge_token` path, which is kind-restricted to the two 2FA
    challenge kinds by design.
    """
    now = now or datetime.now(UTC)
    plain = generate_opaque_token()
    _insert_token(
        session,
        student_id,
        TokenKind.guardian_invite,
        hash_token(plain),
        now + timedelta(seconds=ttl_seconds),
    )
    return plain
