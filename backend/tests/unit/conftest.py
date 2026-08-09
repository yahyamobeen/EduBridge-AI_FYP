"""
Config for the unit tests — dummy values, no database, no secrets.

`security.py` needs argon2 parameters and JWT secrets. Those are configuration,
not infrastructure, so the unit tests supply their own rather than requiring a
real `.env`. Set in `os.environ` at IMPORT time because pydantic-settings reads
the environment when `Settings` is first constructed, and `get_settings` is
cached — a fixture would run too late.

Nothing here reaches a database. That is the point: these tests must run on a
fork, in a fresh clone, and in CI without secrets.
"""

import os

_TEST_ENV = {
    # Never a real connection string. Nothing in tests/unit opens a connection;
    # these exist only so `Settings` validates.
    "DATABASE_URL": "postgresql+psycopg://app_backend:unit@localhost:5432/unit",
    "SERVICE_ROLE_DATABASE_URL": "postgresql+psycopg://service:unit@localhost:5432/unit",
    # 64 hex characters, matching what `openssl rand -hex 32` produces, so the
    # minimum-length validator sees a realistic value.
    "JWT_SECRET": "0" * 64,
    "JWT_REFRESH_SECRET": "1" * 64,
    "APP_ENV": "test",
    # Valid Fernet key for TOTP encryption tests. This is a test-only key —
    # never used in production. Generated with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    "TOTP_ENCRYPTION_KEY": "ZmDfcTF7_60GrrY167zOSPd1kGKO6g49S0kOZkSOb0A=",
    # The default cost is deliberately expensive; these tests hash repeatedly and
    # are asserting behaviour, not tuning.
    "ARGON2_TIME_COST": "1",
    "ARGON2_MEMORY_COST": "8192",
    "ARGON2_PARALLELISM": "1",
    # Fake Turnstile secret for tests/unit only. The config validator only
    # refuses a CHANGE_ME placeholder — never start with that prefix — and the
    # value is otherwise opaque, so a fixed string is as real as it needs to be.
    # No unit test ever calls siteverify; this exists only so Settings validates.
    "TURNSTILE_SECRET_KEY": "0" * 40,
}

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)
