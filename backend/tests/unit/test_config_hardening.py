"""
Configuration that fails closed (findings A3, A4, D11).

THE SHAPE OF ALL THREE BUGS WAS THE SAME: a setting typed as a bare `str`, and
consumers that compared it for equality against one expected spelling. Anything
else did not raise — it simply matched no branch, and the code fell through to
whichever behaviour happened to be the default. Every one of those defaults was
the insecure one:

  * `APP_ENV=prod` read as development, so `/docs` was served, the logging email
    sender was permitted, and `secure` was dropped from the refresh cookie.
  * `EMAIL_PROVIDER=Resend` matched neither "resend" nor "logging", so it used
    the logging sender AND passed the production guard, which also tested
    `== "logging"`. Every 2FA code and reset link to stdout.
  * `APP_BASE_URL` left at its localhost default mails links nobody can open.

These construct `Settings()` through the real environment rather than by keyword,
because the environment is where the mistake is actually made — a value pasted
into a deployment dashboard.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestEnvironmentIsAClosedSet:
    def test_a_plausible_abbreviation_is_refused(self, monkeypatch):
        """
        `prod` is the single most likely way to get this wrong, and it used to be
        indistinguishable from `development` in its effects.
        """
        monkeypatch.setenv("APP_ENV", "prod")
        with pytest.raises(ValidationError):
            Settings()

    @pytest.mark.parametrize("raw", ["Production", " production ", "PRODUCTION"])
    def test_formatting_is_forgiven(self, monkeypatch, raw):
        """
        Case and stray whitespace are paste accidents, not different intentions.
        Refusing them would mean a deployment that cannot start for a reason
        nobody can see in a dashboard field.
        """
        monkeypatch.setenv("APP_ENV", raw)
        monkeypatch.setenv("EMAIL_PROVIDER", "resend")
        monkeypatch.setenv("EMAIL_FROM", "no-reply@example.com")
        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")

        assert Settings().is_production is True

    def test_the_default_is_development(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        assert Settings().is_production is False


class TestEmailProviderIsAClosedSet:
    def test_a_misspelling_is_refused(self, monkeypatch):
        monkeypatch.setenv("EMAIL_PROVIDER", "resendd")
        with pytest.raises(ValidationError):
            Settings()

    def test_capitalisation_is_forgiven(self, monkeypatch):
        monkeypatch.setenv("EMAIL_PROVIDER", "Resend")
        monkeypatch.setenv("EMAIL_FROM", "no-reply@example.com")

        # Normalised, so every `== "resend"` consumer matches. Before the
        # Literal this value silently selected the logging sender.
        assert Settings().email_provider == "resend"


class TestProductionRefusesAnUnusableBaseUrl:
    def _production_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("EMAIL_PROVIDER", "resend")
        monkeypatch.setenv("EMAIL_FROM", "no-reply@example.com")

    def test_the_localhost_default_is_refused(self, monkeypatch):
        self._production_env(monkeypatch)
        monkeypatch.setenv("APP_BASE_URL", "http://localhost:3000")

        with pytest.raises(ValidationError, match="APP_BASE_URL"):
            Settings()

    def test_plain_http_is_refused(self, monkeypatch):
        """A password-reset token is a single-use credential in the query
        string. Over http it is readable by anything on the path."""
        self._production_env(monkeypatch)
        monkeypatch.setenv("APP_BASE_URL", "http://app.example.com")

        with pytest.raises(ValidationError, match="APP_BASE_URL"):
            Settings()

    def test_https_is_accepted(self, monkeypatch):
        self._production_env(monkeypatch)
        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")

        assert Settings().app_base_url == "https://app.example.com"

    def test_development_still_allows_localhost(self, monkeypatch):
        """The rule is production-only; local development must stay trivial."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("APP_BASE_URL", "http://localhost:3000")

        assert Settings().app_base_url == "http://localhost:3000"


class TestTheProductionGuardIsNowReachable:
    def test_logging_sender_is_refused_in_production(self, monkeypatch):
        """
        This guard already existed. It was UNREACHABLE via a misspelling,
        because `EMAIL_PROVIDER=Logging` matched neither the guard's
        `== "logging"` nor the sender's, and the sender's fallback was the
        logging one — so the misspelling both bypassed the check and selected
        the thing the check exists to prevent.
        """
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("EMAIL_PROVIDER", "Logging")
        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")

        with pytest.raises(ValidationError, match="EMAIL_PROVIDER"):
            Settings()
