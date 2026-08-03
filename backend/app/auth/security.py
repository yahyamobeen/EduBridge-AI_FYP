import hashlib
import hmac
import secrets
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


def decode_access_token(token: str, *, expected_type: str = "access") -> UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise ValueError("invalid or expired token") from None
    if payload.get("type") != expected_type:
        raise ValueError("not an access token")
    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError):
        raise ValueError("invalid subject") from None
