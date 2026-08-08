"""
Turnstile unit tests — no network, no database.

`verify_turnstile_token` branches are exercised with a fake httpx.Client; the
ORDERING property of `login()` is pinned with spies on the names the service
actually calls (`app.auth.service.verify_turnstile_token`), because `login()`
imports the function by name — patching `app.auth.turnstile` alone changes
nothing the request path uses.

The unit conftest puts a fake TURNSTILE_SECRET_KEY into the environment, so
`Settings()` validates here without any `.env`.
"""

import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.auth.schemas import LoginRequest
from app.auth.service import login
from app.auth.turnstile import verify_turnstile_token
from app.core.errors import AppError

WRONG_PASSWORD = "wrong-password"  # noqa: S105 -- a fixture credential
CORRECT_PASSWORD = "correct-horse-battery"  # noqa: S105 -- a fixture credential
TOKEN = "a-shared-test-token"  # noqa: S105 -- accepted by every spy in this file


class _FakeResponse:
    def __init__(self, *, payload, status_ok: bool = True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "https://challenges.cloudflare.com"),
                response=httpx.Response(500),
            )

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.posted: dict | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def post(self, url: str, *, data: dict):
        self.posted = {"url": url, "data": data}
        return self._response


@pytest.fixture
def fake_client(monkeypatch):
    def _install(response: _FakeResponse) -> _FakeClient:
        import app.auth.turnstile as turnstile_module

        client = _FakeClient(response)
        monkeypatch.setattr(turnstile_module.httpx, "Client", lambda *_a, **_k: client)
        return client

    return _install


class TestVerifyTurnstileToken:
    def test_success_true(self, fake_client):
        """Cloudflare's `success: true` is the only pass."""
        client = fake_client(_FakeResponse(payload={"success": True}))

        assert verify_turnstile_token("any-token") is True
        assert client.posted["url"].endswith("/turnstile/v0/siteverify")
        assert client.posted["data"]["response"] == "any-token"
        # The configured secret travels in the body, never in the URL.
        assert "secret" in client.posted["data"]

    def test_reject_logs_codes_and_returns_false(self, fake_client, caplog):
        rejected = _FakeResponse(
            payload={"success": False, "error-codes": ["timeout-or-duplicate"]}
        )
        fake_client(rejected)

        with caplog.at_level(logging.ERROR, logger="edubridge.turnstile"):
            assert verify_turnstile_token("t") is False

        assert "timeout-or-duplicate" in caplog.text

    def test_http_error_fails_closed(self, fake_client):
        fake_client(_FakeResponse(payload={"success": True}, status_ok=False))

        assert verify_turnstile_token("t") is False

    def test_non_json_body_fails_closed(self, fake_client):
        fake_client(_FakeResponse(payload=ValueError("not json")))

        assert verify_turnstile_token("t") is False

    def test_success_not_bool_fails_closed(self, fake_client):
        fake_client(_FakeResponse(payload={"success": "yes"}))

        assert verify_turnstile_token("t") is False


def _fake_login_db(user_row: dict | None):
    """A Session stand-in answering the two reads `login()` makes."""
    class _Mappings:
        def __init__(self, row):
            self._row = row

        def one_or_none(self):
            return self._row

    class _Result:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return _Mappings(self._row)

    class _Db:
        def __init__(self):
            self.executed = 0

        def execute(self, *a, **k):
            self.executed += 1
            if self.executed == 1:
                return _Result(user_row)
            # The 2FA read after a known user; `None` means no enrolment.
            return _Result(None)

    return _Db()


class TestLoginOrdersTheCaptchaFirst:
    def test_captcha_runs_before_any_database_work(self, monkeypatch):
        """Login must not touch the store before the captcha verdict."""
        import app.auth.service as service_module

        order: list[str] = []

        def _spy(token: str) -> bool:
            order.append("captcha")
            return True

        class _BlowsUp:
            def execute(self, *_a, **_k):
                order.append("db")
                raise AssertionError("login reached the database despite a captcha guard")

        monkeypatch.setattr(service_module, "verify_turnstile_token", _spy)
        with pytest.raises(AssertionError):
            login(
                _BlowsUp(),
                LoginRequest(
                    email="nobody@example.com",
                    password=WRONG_PASSWORD,
                    turnstile_token=TOKEN,
                ),
            )
        # The 'db' entry proves the store WOULD have been reached — but only
        # after the captcha verdict, which is the ordering this pins.
        assert order == ["captcha", "db"], f"database was reached out of order: {order}"

    def test_unknown_email_verifies_captcha_once_then_dummy_hash(self, monkeypatch):
        """
        The account-missing branch: captcha first, then exactly one argon2
        verify against the DUMMY hash — `verify_password` from app.auth.service.
        """
        import app.auth.service as service_module

        calls: list[str] = []  # names only: the ORDER is what is being asserted
        monkeypatch.setattr(
            service_module,
            "verify_turnstile_token",
            lambda _token: calls.append("captcha") or True,
        )
        real_verify = service_module.verify_password

        def _recording_verify(password, hash_):
            calls.append("password")
            return real_verify(password, hash_)

        monkeypatch.setattr(service_module, "verify_password", _recording_verify)

        db = _fake_login_db(user_row=None)
        with pytest.raises(AppError) as exc:
            login(
                db,
                LoginRequest(
                    email="nobody@example.com",
                    password=WRONG_PASSWORD,
                    turnstile_token=TOKEN,
                ),
            )
        assert exc.value.status_code == 401
        assert calls == ["captcha", "password"]

    def test_known_email_captcha_before_password_branch(self, monkeypatch):
        """
        A real account with the correct password. Siteverify is called FIRST and
        exactly once; the password verify runs on the real hash.
        """
        import app.auth.service as service_module
        from app.auth.security import hash_password

        calls: list[str] = []
        monkeypatch.setattr(
            service_module,
            "verify_turnstile_token",
            lambda _token: calls.append("captcha") or True,
        )
        real_verify = service_module.verify_password

        def _recording_verify(password, hash_):
            calls.append("password")
            return real_verify(password, hash_)

        monkeypatch.setattr(service_module, "verify_password", _recording_verify)
        # issue_challenge_token would write tokens through `db`; stub the name.
        monkeypatch.setattr(service_module, "issue_challenge_token", lambda *_a, **_k: "tok")

        user_row = {
            "id": uuid4(),
            "password_hash": hash_password(CORRECT_PASSWORD),
            "status": "active",
            "email_verified_at": datetime.now(UTC),
        }
        result = login(
            _fake_login_db(user_row=user_row),
            LoginRequest(
                email="known@example.com", password=CORRECT_PASSWORD, turnstile_token=TOKEN
            ),
        )
        assert result["status"] == "two_factor_enrollment_required"
        assert calls == ["captcha", "password"]


class TestConfigRefusesThePlaceholder:
    def test_changeme_secret_rejected(self, monkeypatch):

        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "CHANGE_ME_create_in_cloudflare_dashboard")
        with pytest.raises(ValidationError) as exc:
            from app.core.config import Settings

            Settings()
        assert "TURNSTILE_SECRET_KEY" in str(exc.value)
