from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    Configuration read from backend/.env.

    EVERY FIELD WHOSE ENV KEY DIFFERS FROM ITS NAME CARRIES AN EXPLICIT
    `validation_alias`. pydantic-settings matches on the field NAME, so
    `environment` looks for `ENVIRONMENT` — while `.env.example` set `APP_ENV`,
    which was therefore silently ignored, along with `JWT_ACCESS_TTL_MINUTES`
    and `JWT_REFRESH_TTL_DAYS`.

    That was not cosmetic. `environment` gates whether `/docs` is exposed and
    whether the refresh cookie gets its `secure` flag, so a deployment stayed in
    development mode no matter what the file said — and `extra="ignore"` meant
    nothing ever complained.
    """

    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "EduBridge AI"
    environment: str = Field(default="development", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    api_base_path: str = Field(default="/api", validation_alias="API_BASE_PATH")

    # Connects as app_backend (NOBYPASSRLS). Verified at startup by
    # `assert_backend_role_cannot_bypass_rls`, because "never connect as
    # postgres" is invisible when violated: everything works and every policy
    # is simply inert.
    database_url: str
    # Bypasses RLS. Background jobs only; no request path may use it.
    service_role_database_url: str

    jwt_secret: str
    jwt_refresh_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=15, validation_alias="JWT_ACCESS_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=7, validation_alias="JWT_REFRESH_TTL_DAYS")
    enrollment_token_ttl_seconds: int = 900
    pending_token_ttl_seconds: int = 300

    # TOTP secret encryption key for two_factor_enrollment.totp_secret_encrypted.
    # The key lives in application config, NOT in the database, so a database
    # dump alone does not yield usable secrets (tdd.md §6.9).
    #
    # REQUIRED, with no default, on purpose. A defaulted encryption key is worse
    # than a missing one: every deployment that forgot to set it would share the
    # same key and nobody would find out. This is a NEW required setting as of
    # KAN-10b — an existing environment will refuse to start until it is added,
    # which is the intended failure. See `_totp_key_must_be_a_fernet_key` for
    # the message that tells you what to run.
    totp_encryption_key: str = Field(validation_alias="TOTP_ENCRYPTION_KEY")

    # Cloudflare Turnstile secret (siteverify is called server-side on register
    # and login). SAME RULE AS TOTP: required, no default, and the app refuses
    # to start on the placeholder from .env.example. A defaulted or placeholder
    # secret key would silently verify nothing (or every) captcha.
    turnstile_secret_key: str = Field(validation_alias="TURNSTILE_SECRET_KEY")

    # Email delivery (tdd.md §3.1, KAN-10b).
    # "logging" writes metadata to the logger (development/CI).
    # "resend" sends via the Resend API, and needs `uv sync --extra email`.
    # No provider is settled; `logging` is the default so nothing is chosen by
    # accident.
    email_provider: str = Field(default="logging", validation_alias="EMAIL_PROVIDER")
    resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")
    email_from: str = Field(default="", validation_alias="EMAIL_FROM")
    app_base_url: str = Field(default="http://localhost:3000", validation_alias="APP_BASE_URL")

    # 2FA lockout thresholds (tdd.md §6.9, D7).
    # List of (failed_attempts_threshold, lockout_seconds) pairs, evaluated in
    # order. The HIGHEST threshold whose failed_attempts count is met or
    # exceeded determines the lockout duration.
    two_factor_lockout_thresholds: list[tuple[int, int]] = [
        (3, 300),
        (6, 900),
        (10, 3600),
    ]

    # No wildcard default. Combined with credentialed requests a wildcard does
    # NOT send `*` — Starlette echoes the caller's origin instead — so any site
    # could make authenticated cross-origin calls, and the refresh cookie is a
    # credential. Set the real origins explicitly.
    cors_origins: list[str] = ["http://localhost:3000"]

    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @field_validator("jwt_secret", "jwt_refresh_secret")
    @classmethod
    def _secret_is_strong_enough(cls, value: str, info: ValidationInfo) -> str:
        # `openssl rand -hex 32` produces 64 characters. Anything materially
        # shorter — or the placeholder copied straight out of the template — is
        # a signing key that can be guessed, and it would otherwise be accepted
        # in silence.
        if len(value) < 32 or value.startswith("CHANGE_ME"):
            raise ValueError(
                f"{info.field_name} must be a real secret of at least 32 characters "
                "(generate one with: openssl rand -hex 32)"
            )
        return value

    @field_validator("totp_encryption_key")
    @classmethod
    def _totp_key_must_be_a_fernet_key(cls, value: str) -> str:
        # Fernet is strict about its key format, and it raises at FIRST USE —
        # which would be the middle of a user's 2FA enrolment, long after
        # startup, as a 500. Validating here turns that into a boot failure with
        # an instruction attached.
        from cryptography.fernet import Fernet

        if value.startswith("CHANGE_ME"):
            raise ValueError(
                "TOTP_ENCRYPTION_KEY is still the placeholder from .env.example. "
                'Generate one with: python -c "from cryptography.fernet import '
                'Fernet; print(Fernet.generate_key().decode())"'
            )
        try:
            Fernet(value.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "TOTP_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe "
                'base64-encoded bytes). Generate one with: python -c "from '
                'cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from exc
        return value

    @field_validator("turnstile_secret_key")
    @classmethod
    def _turnstile_key_is_not_a_placeholder(cls, value: str) -> str:
        # Same refusal style as the TOTP key: the two keys have different
        # formats (Turnstile secrets are opaque), so this checks the placeholder
        # rather than pretending to validate a format we could never pin down.
        if value.startswith("CHANGE_ME"):
            raise ValueError(
                "TURNSTILE_SECRET_KEY is still the placeholder from .env.example. "
                "Create the widget in the Cloudflare dashboard, copy its secret "
                "key into backend/.env, and never commit it."
            )
        return value

    @model_validator(mode="after")
    def _production_is_actually_hardened(self) -> "Settings":
        if self.is_production and "*" in self.cors_origins:
            raise ValueError(
                "cors_origins must not contain '*' in production: credentialed "
                "requests would then be accepted from any origin."
            )
        if self.is_production and self.email_provider == "logging":
            raise ValueError(
                "EMAIL_PROVIDER=logging in production: verification links, reset "
                "links and 2FA codes would be written to the log and never sent, "
                "so nobody could complete sign-up."
            )
        if self.email_provider == "resend" and not self.email_from:
            raise ValueError("EMAIL_PROVIDER=resend requires EMAIL_FROM to be set.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
