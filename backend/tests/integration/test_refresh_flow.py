from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.tokens import issue_refresh_token
from app.core.db import service_engine
from app.main import app

client = TestClient(app)


def _make_user_with_refresh_token() -> tuple[str, str]:
    email = f"{uuid4().hex[:12]}@test.com"
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Refresh User",
            "role": "parent",
        },
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["user_id"]
    with Session(bind=service_engine) as session:
        plain, _ = issue_refresh_token(session, user_id)
        session.commit()
    return user_id, plain


def test_refresh_rotates_and_replay_fails():
    _, plain = _make_user_with_refresh_token()
    client.cookies.clear()

    first = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    new_cookie = first.cookies.get("refresh_token")
    assert new_cookie and new_cookie != plain

    replay = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "UNAUTHENTICATED"


def test_refresh_with_valid_cookie_then_me():
    _, plain = _make_user_with_refresh_token()
    client.cookies.clear()

    resp = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert resp.status_code == 200
    access = resp.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    assert me.json()["onboarding_state"] == "email_verification_pending"


def test_logout_then_refresh_401():
    user_id, plain = _make_user_with_refresh_token()
    resp = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert resp.status_code == 200
    access = resp.json()["access_token"]

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert logout.status_code == 204

    stale = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert stale.status_code == 401
