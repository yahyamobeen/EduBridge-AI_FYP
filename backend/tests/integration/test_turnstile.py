"""
Turnstile at the route level — the observable contract.

The autouse `never_call_turnstile` fixture makes every verification PASS; the
tests here deliberately re-patch the seam (`app.auth.service.verify_turnstile_token`) to a
rejecting stub. `app.auth.service`, because that is where the name the request
path calls lives.

These are the tests that pin the ORDERING rule at the contract level: a login
whose captcha is rejected must answer 400 CAPTCHA_FAILED even for an address
that does not exist — never 401 UNAUTHENTICATED — proving the captcha verdict
lands before the account machinery, not after it.
"""

import logging
from uuid import uuid4

from sqlalchemy import text

import app.auth.service as service_module

_TOKEN = "test-turnstile-token"  # noqa: S105 -- accepted by the autouse fixture


def _reject_captcha(monkeypatch):
    monkeypatch.setattr(service_module, "verify_turnstile_token", lambda _token: False)


def _register_body(email: str, **overrides) -> dict:
    body = {
        "email": email,
        "password": "password123",
        "full_name": "Captcha Tester",
        "role": "parent",
        "turnstile_token": _TOKEN,
    }
    body.update(overrides)
    return body


def test_register_with_rejected_captcha_is_400(monkeypatch, client, service_conn):
    _reject_captcha(monkeypatch)
    email = f"{uuid4().hex[:12]}@test.com"

    resp = client.post("/api/auth/register", json=_register_body(email))

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "CAPTCHA_FAILED"
    # NO account machinery ran: a rejected token must not spend a hash, and —
    # crucially — must not CREATE the account the form asked for.
    row = service_conn.execute(
        text("SELECT 1 FROM app_user WHERE email = :e"), {"e": email}
    ).first()
    assert row is None, "a captcha-rejected registration still created a user"


def test_login_with_rejected_captcha_is_400_not_401(monkeypatch, client):
    """
    The ordering contract at the HTTP level: an unknown email with a rejected
    token answers CAPTCHA_FAILED, NOT UNAUTHENTICATED. If login() ever verifies
    the password before the captcha, this test flips to 401.
    """
    _reject_captcha(monkeypatch)
    resp = client.post(
        "/api/auth/login",
        json={
            "email": f"{uuid4().hex[:12]}@nobody.com",
            "password": "whatever",  # noqa: S106 - the point is it must not run
            "turnstile_token": _TOKEN,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CAPTCHA_FAILED"


def test_missing_token_is_validation_error(client):
    email = f"{uuid4().hex[:12]}@test.com"
    body = _register_body(email)
    del body["turnstile_token"]

    resp = client.post("/api/auth/register", json=body)

    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert "turnstile_token" in err["details"]["fields"]


def test_empty_token_is_validation_error(client):
    email = f"{uuid4().hex[:12]}@test.com"

    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "pw", "turnstile_token": ""},  # noqa: S106
    )

    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert "turnstile_token" in err["details"]["fields"]


def test_captcha_success_still_authenticates(client):
    """The happy path is untouched: a verified token behaves exactly as before."""
    email = f"{uuid4().hex[:12]}@test.com"
    reg = client.post("/api/auth/register", json=_register_body(email))
    assert reg.status_code == 201, reg.text

    login_resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123", "turnstile_token": _TOKEN},
    )
    assert login_resp.status_code == 200, login_resp.text
    assert login_resp.json()["status"] == "email_verification_required"


def test_error_body_never_leaks_codes(monkeypatch, client, caplog):
    """
    Cloudflare's error-codes name internals; the client body must never carry
    them. The rejecting seam logs them (the real implementation does), and the
    response body stays generic: one CAPTCHA_FAILED and nothing else.
    """

    def _reject_logging_codes(_token: str) -> bool:
        import app.auth.turnstile as turnstile_module

        turnstile_module.logger.error("turnstile rejected token: %s", ["timeout-or-duplicate"])
        return False

    monkeypatch.setattr(service_module, "verify_turnstile_token", _reject_logging_codes)
    email = f"{uuid4().hex[:12]}@test.com"

    with caplog.at_level(logging.ERROR, logger="edubridge.turnstile"):
        resp = client.post("/api/auth/register", json=_register_body(email))

    assert resp.status_code == 400
    text = resp.text
    assert "error-codes" not in text
    assert "timeout-or-duplicate" not in text
    assert "CAPTCHA_FAILED" in text
    assert "timeout-or-duplicate" in caplog.text, "the code only reached the log"
