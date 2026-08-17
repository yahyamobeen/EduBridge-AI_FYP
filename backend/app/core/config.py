from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]

# Providers that actually put mail on the wire, and therefore need a sender
# address. `logging` is the only member of `email_provider`'s Literal missing
# from this set, and that is deliberate: it writes to a log, which has no From.
_PROVIDERS_NEEDING_SENDER = frozenset({"resend", "sendgrid"})


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
    # Finding A4. This was a bare `str` compared with `== "production"`, so
    # `APP_ENV=prod`, `Production` or a value with a trailing space read as
    # DEVELOPMENT in a production deployment: `/docs` served, the logging email
    # sender permitted, and -- worst -- `secure` dropped from the refresh cookie,
    # putting a live credential on the wire in cleartext. A `Literal` turns every
    # one of those typos into a boot failure instead.
    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
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

    # ---- Session policy (Phase 4) -------------------------------------------
    # The ABSOLUTE ceiling on a rotating refresh chain. Rotation without one
    # means a chain can be extended for ever, seven days at a time, so "the
    # session expires" is not true of any session anybody keeps using.
    #
    # ⚠️ DEFAULTED, NOT REQUIRED — unlike `totp_encryption_key` above, and for a
    #    specific reason: `tests/unit/conftest.py` sets environment variables at
    #    IMPORT time, so a new required setting breaks collection rather than
    #    failing a test. A defaulted ceiling is also safe in a way a defaulted
    #    encryption key is not; the worst case is every deployment sharing the
    #    same session length, which is a policy, not a secret.
    #
    # ⚠️ THE REAL CEILING IS THIS PLUS UP TO `access_token_ttl_minutes`, because
    #    a refused rotation stamps nothing and the access token already issued
    #    lives out its own TTL. Stated here and in the contract rather than
    #    claiming a hard 14 days.
    session_absolute_ttl_days: int = Field(default=14, validation_alias="SESSION_ABSOLUTE_TTL_DAYS")
    # How long after a rotation a replay of the old token is read as a two-tab
    # RACE rather than as theft — and then only while a live sibling of the same
    # family still exists (`app.rotate_refresh_token`). Seconds, deliberately
    # small: this is the width of a network round trip, not a grace period for
    # an attacker.
    refresh_race_grace_seconds: int = Field(
        default=10, validation_alias="REFRESH_RACE_GRACE_SECONDS"
    )
    # ⚠️ CLOCK SKEW ALLOWANCE, AND IT IS NOT DEFENSIVE PADDING — WITHOUT IT
    #    SESSION INVALIDATION SILENTLY DOES NOT WORK.
    #
    #    A token's `iat` is minted by PYTHON on the application host;
    #    `sessions_invalidated_at` is stamped by `clock_timestamp()` on the
    #    DATABASE host. Those are two machines. Measured against the live
    #    Supabase project while building this: a token created BEFORE a password
    #    change carried `iat = 20:03:43` while the stamp written afterwards read
    #    `20:03:41.88` — the database was 1.1s behind, so the token looked as
    #    though it had been issued after its own invalidation and survived.
    #
    #    A JWT `iat` is also an integer, so the token side is floored to whole
    #    seconds and there is no sub-second precision left to compare with.
    #
    #    The allowance widens the cutoff so realistic skew cannot defeat the
    #    check. It fails CLOSED: a token genuinely issued within this many
    #    seconds AFTER an invalidation is also refused. That costs one extra
    #    sign-in on a flow no human completes that fast (reset requires reading
    #    an email), and buys an invalidation that actually invalidates.
    session_invalidation_skew_seconds: int = Field(
        default=5, validation_alias="SESSION_INVALIDATION_SKEW_SECONDS"
    )

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

    # Email delivery (tdd.md §3.1, KAN-10b; provider resolved to SendGrid in
    # KAN-21).
    # "logging"  writes metadata to the logger (development/CI).
    # "sendgrid" sends via the SendGrid Web API -- the chosen provider.
    # "resend"   sends via the Resend API. Retained and still supported, but
    #            its unverified free tier delivers ONLY to the account owner's
    #            own address, so it could never reach a real parent. That is
    #            what forced the switch.
    # Both real providers need `uv sync --extra email`.
    #
    # ⚠️ THIS IS A `Literal`, NOT A `str`, AND WIDENING IT IS PART OF ADDING A
    #    PROVIDER. Finding A3: it used to be a bare `str`, and every consumer
    #    tests `== "logging"` or `== "resend"`, so `EMAIL_PROVIDER=Resend`
    #    matched NEITHER -- it fell through to the logging sender AND past the
    #    production guard below, which also tests `== "logging"`. A production
    #    deployment would have written every 2FA code and every password-reset
    #    link to stdout while reporting healthy.
    #
    #    The cost of the Literal is that a provider absent from it is refused at
    #    boot rather than ignored, which is the whole point -- but it means
    #    `email.py` growing a sender class is not sufficient on its own. Adding
    #    `SendGridEmailSender` without this line would have raised a validation
    #    error before the application could start.
    email_provider: Literal["logging", "resend", "sendgrid"] = Field(
        default="logging", validation_alias="EMAIL_PROVIDER"
    )
    resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")
    sendgrid_api_key: str = Field(default="", validation_alias="SENDGRID_API_KEY")
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
        # No `.lower()` and no `.strip()`: `_normalise_choice` has already done
        # both before validation, and anything that survived is one of exactly
        # three literals. Defensive re-normalisation here would hide a failure
        # that should have happened at boot.
        return self.environment == "production"

    @field_validator("environment", "email_provider", mode="before")
    @classmethod
    def _normalise_choice(cls, value: object) -> object:
        """
        Trim and lower-case BEFORE the Literal is checked.

        `APP_ENV=Production ` with a trailing space is a plausible thing to paste
        into a dashboard field, and it should start the application rather than
        refuse it. `APP_ENV=prod` is a different thing entirely -- an abbreviation
        that was never a valid value -- and that must still fail. Normalising
        forgives formatting; the Literal refuses guesses.
        """
        return value.strip().lower() if isinstance(value, str) else value

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
    def _absolute_session_ceiling_actually_binds(self) -> "Settings":
        """
        A ceiling shorter than one refresh token's life never fires.

        `app.rotate_refresh_token` refuses a rotation once the FAMILY is older
        than `session_absolute_ttl_days`. If that is 7 and `refresh_token_ttl_days`
        is also 7, the individual token expires first on every single chain and
        the family cap is unreachable — a setting that appears to bound sessions
        and does nothing. Caught here rather than discovered by nobody.
        """
        if self.session_absolute_ttl_days <= self.refresh_token_ttl_days:
            raise ValueError(
                f"SESSION_ABSOLUTE_TTL_DAYS ({self.session_absolute_ttl_days}) must exceed "
                f"JWT_REFRESH_TTL_DAYS ({self.refresh_token_ttl_days}); otherwise a single "
                "refresh token always expires before the family cap can ever apply, and the "
                "absolute session limit is inert."
            )
        return self

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
        # Every real provider needs a sender address; only `logging` does not.
        # One membership test rather than one `if` per provider, so adding a
        # fourth is an edit here and in the Literal above — not a third branch
        # somebody forgets to write.
        if self.email_provider in _PROVIDERS_NEEDING_SENDER and not self.email_from:
            raise ValueError(f"EMAIL_PROVIDER={self.email_provider} requires EMAIL_FROM to be set.")
        # Finding D11. `app_base_url` is what every verification and reset link
        # is built from. Left at its localhost default in production it mails
        # links nobody can open; set to `http://` it puts single-use credentials
        # — the reset token is one — into cleartext on the wire.
        if self.is_production and not self.app_base_url.startswith("https://"):
            raise ValueError(
                "APP_BASE_URL must be an https:// address in production (it is "
                f"currently {self.app_base_url!r}). Every verification and "
                "password-reset link is built from it, so a localhost value "
                "mails links nobody can open and an http:// value puts reset "
                "tokens in cleartext."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
