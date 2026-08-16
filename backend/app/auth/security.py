import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings


@lru_cache(maxsize=1)
def _password_hasher() -> PasswordHasher:
    """
    Built on first use, not at import.

    Reading settings at module scope means importing ANYTHING that transitively
    reaches this module requires a complete `.env` — which made the unit tests
    impossible to run without database credentials they never touch. Cached, so
    the parameters are still resolved exactly once.
    """
    settings = get_settings()
    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )


def hash_password(password: str) -> str:
    return _password_hasher().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher().verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    settings = get_settings()
    digest = hmac.new(
        settings.jwt_refresh_secret.encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def create_access_token(
    user_id: UUID,
    *,
    token_type: str = "access",  # noqa: S107 -- a JWT claim value, not a secret
    now: datetime | None = None,
) -> tuple[str, int]:
    settings = get_settings()
    now = now or datetime.now(UTC)
    expires_in = settings.access_token_ttl_minutes * 60
    exp = now + timedelta(seconds=expires_in)
    payload = {
        "sub": str(user_id),
        "exp": exp,
        "iat": now,
        "type": token_type,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def create_onboarding_token(user_id: UUID, *, now: datetime | None = None) -> tuple[str, int]:
    """
    Issue an onboarding-scoped access token (``type: "onboarding"``).

    This token is accepted ONLY by endpoints that explicitly check for
    ``expected_type="onboarding"``. The default ``decode_access_token`` call
    (which checks ``type == "access"``) REJECTS it — so every business
    endpoint, including ``/auth/me``, refuses onboarding tokens. This is the
    enforcement mechanism for the tdd.md §3.1 rule that the email-verify
    token must not reach protected resources.
    """
    return create_access_token(user_id, token_type="onboarding", now=now)  # noqa: S106


@dataclass(frozen=True)
class AccessClaims:
    """
    The claims a caller needs, rather than just the subject.

    Added in Phase 4 for `sessions_invalidated_at`: deciding whether a token
    predates an invalidation event needs its ISSUE TIME, and
    `decode_access_token` returns a bare `UUID`.
    """

    user_id: UUID
    issued_at: datetime


def decode_access_claims(token: str, *, expected_type: str = "access") -> AccessClaims:
    """
    Verify a token and return its subject AND issue time.

    ⚠️ A MISSING `iat` FAILS CLOSED. Every token this application mints carries
    one (`create_access_token`), so its absence means either a token from
    another issuer or one crafted by hand — and treating "no issue time" as
    "issued now" would make session invalidation trivially bypassable by
    stripping a claim.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise ValueError("invalid or expired token") from None
    if payload.get("type") != expected_type:
        raise ValueError("not an access token")
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise ValueError("invalid subject") from None
    try:
        issued_at = datetime.fromtimestamp(payload["iat"], tz=UTC)
    except (KeyError, TypeError, ValueError, OSError):
        raise ValueError("missing or malformed issue time") from None
    return AccessClaims(user_id=user_id, issued_at=issued_at)


def decode_access_token(token: str, *, expected_type: str = "access") -> UUID:
    """
    The subject alone.

    ⚠️ KEPT, AND ITS RETURN TYPE IS NOT NEGOTIABLE — a bare `UUID` is asserted
    directly across `test_onboarding_token.py` and `test_security.py`
    (`== user_id`, `== uid`). Phase 4 added `decode_access_claims` ALONGSIDE it
    rather than widening this, and this now delegates so there is exactly one
    decode and one set of rules.
    """
    return decode_access_claims(token, expected_type=expected_type).user_id


def session_is_invalidated(issued_at: datetime, invalidated_at: datetime | None) -> bool:
    """
    Was this token issued at or before the user's last invalidation event?

    ⚠️ THE SHARED HELPER, AND IT MUST STAY SHARED. The onboarding token carries
    an issue time too, so any endpoint decoding with `expected_type="onboarding"`
    becomes a bypass the moment this logic is written out a second time and one
    copy is forgotten.

    ⚠️ NEVER EXPRESS THIS AS A SQL `WHERE` CLAUSE. `sessions_invalidated_at` is
    NULL until a user's first event; comparing against NULL yields NULL, the row
    is filtered out, the caller reads "no such user", and EVERY REQUEST 401s FOR
    EVERYONE — with the same message as a bad token, so it presents as a client
    bug. Select the column and compare here.

    ⚠️ THE TWO SIDES COME FROM DIFFERENT MACHINES, AND WITHOUT THE ALLOWANCE
    BELOW THIS CHECK SILENTLY DOES NOTHING.

    `issued_at` is minted by Python on the application host. `invalidated_at` is
    `clock_timestamp()` on the database host. **Measured against the live project
    while building this**: a token created BEFORE a password change carried
    `iat = 20:03:43` while the stamp written afterwards read `20:03:41.88` — the
    database ran 1.1s behind, so the token appeared to have been issued after its
    own invalidation and sailed through. Nothing failed; the feature was simply
    inert. (An earlier skew measurement said 0.79s the OTHER way, but it included
    a 3.6s round trip and was measuring latency, not skew. It varies.)

    A JWT `iat` is an integer besides, so the token side is floored to whole
    seconds and there is no sub-second precision left to compare with anyway.

    ⚠️ SO THE COMPARISON IS `<=` AGAINST A WIDENED, TRUNCATED CUTOFF, AND EVERY
    PART OF THAT FAILS CLOSED. A strict `<` would fail OPEN on the truncation
    boundary — a token issued at 10:00:00.7 (`iat` 10:00:00) against an
    invalidation at 10:00:00.9 would survive, though it plainly predates it. The
    allowance then absorbs the cross-host skew. Both choices cost the same thing:
    a token issued shortly AFTER an invalidation is also refused, so a user gets
    one extra sign-in. That is the right price for an invalidation that works.

    The principled fix is to stop mixing clocks — mint `iat` from the database on
    the paths that already touch it, or thread the returned stamp into
    `create_access_token(now=...)`. Recorded in the deferred log; the allowance
    is what makes the check correct today.
    """
    if invalidated_at is None:
        return False
    allowance = timedelta(seconds=get_settings().session_invalidation_skew_seconds)
    return issued_at <= invalidated_at.replace(microsecond=0) + allowance
