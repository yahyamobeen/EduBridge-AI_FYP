from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register_student() -> tuple[str, str]:
    email = f"{uuid4().hex[:12]}@test.com"
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Test Student",
            "role": "student",
            "board": "PCTB",
            "class_level": 9,
            "student_group": "science",
            "medium": "en",
        },
    )
    assert resp.status_code == 201, resp.text
    return email, resp.json()["user_id"]


def test_login_wrong_password_401():
    email, _ = _register_student()
    resp = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_unknown_email_same_401_wording():
    resp = client.post(
        "/api/auth/login",
        json={"email": f"{uuid4().hex[:12]}@nobody.com", "password": "whatever"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Incorrect email or password."


def test_login_email_verification_required_no_session():
    email, _ = _register_student()
    resp = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "email_verification_required"
    assert "***" in body["email"]
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "set-cookie" not in resp.headers


def test_login_never_sets_session_cookie():
    email, _ = _register_student()
    resp = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    assert not any(h.lower() == "set-cookie" for h in resp.headers)


def test_refresh_without_cookie_401():
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_requires_token():
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_with_invalid_token_401():
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_logout_without_token_401():
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 401
