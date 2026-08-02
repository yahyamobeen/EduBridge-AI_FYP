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

    @model_validator(mode="after")
    def _production_is_actually_hardened(self) -> "Settings":
        if self.is_production and "*" in self.cors_origins:
            raise ValueError(
                "cors_origins must not contain '*' in production: credentialed "
                "requests would then be accepted from any origin."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
