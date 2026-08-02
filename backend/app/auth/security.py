import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_password_hasher = PasswordHasher(
    time_cost=get_settings().argon2_time_cost,
    memory_cost=get_settings().argon2_memory_cost,
    parallelism=get_settings().argon2_parallelism,
)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
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


def create_access_token(user_id: UUID, *, now: datetime | None = None) -> tuple[str, int]:
    settings = get_settings()
    now = now or datetime.now(UTC)
    expires_in = settings.access_token_ttl_minutes * 60
    exp = now + timedelta(seconds=expires_in)
    payload = {
        "sub": str(user_id),
        "exp": exp,
        "iat": now,
        "type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise ValueError("invalid or expired token") from None
    if payload.get("type") != "access":
        raise ValueError("not an access token")
    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError):
        raise ValueError("invalid subject") from None
