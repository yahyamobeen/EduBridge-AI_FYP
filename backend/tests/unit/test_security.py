from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.auth import security


def test_hash_password_is_argon2id():
    hashed = security.hash_password("s3cret-password")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password("s3cret-password", hashed)


def test_verify_wrong_password_false():
    hashed = security.hash_password("right")
    assert not security.verify_password("wrong", hashed)


def test_verify_garbage_hash_false():
    assert not security.verify_password("x", "not-a-real-hash")


def test_opaque_token_unique_and_long():
    a = security.generate_opaque_token()
    b = security.generate_opaque_token()
    assert a != b
    assert len(a) >= 40


def test_hash_token_deterministic():
    token = security.generate_opaque_token()
    h1 = security.hash_token(token)
    h2 = security.hash_token(token)
    assert h1 == h2  # HMAC-SHA256 is deterministic so rows can be looked up by hash
    assert h1.startswith("hmac-sha256:")


def test_access_token_roundtrip():
    uid = uuid4()
    token, expires_in = security.create_access_token(uid)
    assert expires_in > 0
    assert security.decode_access_token(token) == uid


def test_access_token_expired():
    uid = uuid4()
    past = datetime.now(UTC) - timedelta(minutes=30)
    token, _ = security.create_access_token(uid, now=past)
    with pytest.raises(ValueError):
        security.decode_access_token(token)


def test_decode_wrong_type_rejected():
    import jwt

    from app.core.config import get_settings

    settings = get_settings()
    exp = datetime.now(UTC) + timedelta(minutes=5)
    payload = {"sub": str(uuid4()), "exp": exp, "type": "refresh"}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(ValueError):
        security.decode_access_token(token)
