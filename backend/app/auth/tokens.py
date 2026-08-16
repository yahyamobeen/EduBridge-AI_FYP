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


class RefreshTokenRaceError(Exception):
    """
    Two refreshes raced on the same token and this one lost.

    ⚠️ NOT THE SAME AS REUSE, AND CONFLATING THEM SIGNS INNOCENT USERS OUT.
    The client's single-flight guard is per browser TAB (`client.ts`), so two
    tabs refreshing together present the same token twice. Read as theft that
    revokes the whole family and logs the user out of every device, and writes
    an audit row claiming a security incident that did not happen.

    `app.rotate_refresh_token` reports this only when the old token was revoked
    moments ago AND a live sibling of the same family still exists — i.e. the
    winner of a concurrent refresh has already replaced it. A captured token
    replayed later fails both conditions and is still reuse.

    The caller answers a plain 401 and revokes nothing. That is self-healing:
    the winner's response already overwrote the httpOnly cookie, so the client's
    retry carries the new token.

    ⚠️ It carries `user_id` for the same reason `RefreshTokenReuseError` does.
    A thief replaying inside the grace window lands here rather than in reuse
    detection, so this is the only record that it happened — and a record with
    no subject is not one.
    """

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        super().__init__("refresh token rotation race")


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
    """
    Mint the token that STARTS a rotating family.

    Returns the plaintext token (given to the client once) and the row id.

    ⚠️ `app.insert_refresh_token`, NOT `app.insert_auth_token`. The new function
    stamps `family_started_at`, which is what bounds a chain absolutely rather
    than per token. It is a separate NAME rather than an extra argument on the
    existing function because `CREATE OR REPLACE` with an added defaulted
    argument creates a SECOND function, and the four-argument call in
    `_insert_token` would then match both — "function name is not unique", at
    runtime rather than at migration time.
    """
    settings = get_settings()
    now = now or datetime.now(UTC)
    plain = generate_opaque_token()
    row_id = session.execute(
        text("SELECT app.insert_refresh_token(:uid, :hash, :expires)"),
        {
            "uid": str(user_id),
            "hash": hash_token(plain),
            "expires": now + timedelta(days=settings.refresh_token_ttl_days),
        },
    ).scalar_one()
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
    Exchange a refresh token for a new one, revoking the old. ONE statement.

    Returns `(plaintext, user_id)`, or None when the token is unknown, expired,
    of the wrong kind, or its family has passed the absolute ceiling.
    Raises `RefreshTokenReuseError` on a genuine replay and
    `RefreshTokenRaceError` when two refreshes simply collided.

    ⚠️ THIS WAS FINDING D2 AND IT WAS FOUR ROUND TRIPS WITH NO LOCK: read, check
    `revoked`, revoke, insert. Two concurrent refreshes presenting the same
    token could BOTH pass the check — one forked the family (defeating any
    absolute cap, since the fork restarted the chain) and the other tripped
    reuse detection on a legitimate refresh. Two browser tabs reproduce it,
    because the client's single-flight guard is per tab.

    `app.rotate_refresh_token` does all of it under a `FOR UPDATE` lock, so the
    second caller blocks and then re-reads the row the winner just revoked. It
    also enforces the family ceiling where the data is, and tells a race from a
    theft — neither of which is expressible from here without another round trip
    that would race in turn.

    ⚠️ `now` NO LONGER DRIVES THE COMPARISONS. The function uses
    `clock_timestamp()`; this argument survives only to set the NEW token's
    expiry, which is what `test_tokens.py::test_expired_token_is_rejected`
    relies on. Passing a far-future `now` therefore no longer makes an existing
    token look expired -- that test asserts the DATABASE's view of expiry now.
    """
    settings = get_settings()
    now = now or datetime.now(UTC)
    plain_new = generate_opaque_token()

    result = (
        session.execute(
            text(
                "SELECT outcome, token_user_id FROM app.rotate_refresh_token("
                "  :old, :new, :expires,"
                "  CAST(:cap AS interval), CAST(:grace AS interval))"
            ),
            {
                "old": hash_token(plain_old),
                "new": hash_token(plain_new),
                "expires": now + timedelta(days=settings.refresh_token_ttl_days),
                "cap": f"{settings.session_absolute_ttl_days} days",
                "grace": f"{settings.refresh_race_grace_seconds} seconds",
            },
        )
        .mappings()
        .one()
    )

    outcome = str(result["outcome"])
    if outcome == "rotated":
        return plain_new, result["token_user_id"]
    if outcome == "raced":
        raise RefreshTokenRaceError(result["token_user_id"])
    if outcome == "reuse":
        raise RefreshTokenReuseError(result["token_user_id"])
    # not_found, expired, family_expired -- all "sign in again", and deliberately
    # indistinguishable to the caller. Which of the three it was is not the
    # client's business, and `family_expired` in particular must not tell an
    # attacker they found a live account whose session merely aged out.
    return None


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


def issue_preauth_token(
    session: Session,
    user_id: UUID,
    *,
    kind: TokenKind,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    """
    Issue a pre-authentication token for email verification or password reset.

    Unlike ``issue_challenge_token`` (which is restricted to 2FA kinds), this
    function accepts ``email_verify`` and ``password_reset`` kinds. These tokens
    are single-use, short-lived, and consumed by their respective SECURITY
    DEFINER functions (``consume_token_and_verify_email``,
    ``consume_password_reset_token``).

    The separation exists on purpose: a ``password_reset`` token presented at
    ``/2fa/verify`` would be nonsensical, and the kind guard in
    ``issue_challenge_token`` is what prevents that confusion at issuance time.
    """
    if kind not in (TokenKind.email_verify, TokenKind.password_reset):
        raise ValueError(f"{kind} is not a pre-auth token kind; use issue_challenge_token for 2FA")

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
