from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"{uuid4().hex[:12]}@test.com"


def test_register_student():
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Ayesha Khan",
            "role": "student",
            "board": "PCTB",
            "class_level": 9,
            "student_group": "science",
            "medium": "en",
            "language_pref": "en",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["role"] == "student"
    assert body["onboarding_state"] == "email_verification_pending"
    assert body["user_id"]


def test_register_teacher():
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Sir Imran",
            "role": "teacher",
            "institution": "Govt High School",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "teacher"


def test_register_parent():
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Mrs. Fatima",
            "role": "parent",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "parent"


def test_register_duplicate_email_conflict():
    email = _unique_email()
    payload = {
        "email": email,
        "password": "password123",
        "full_name": "Dup User",
        "role": "parent",
    }
    first = client.post("/api/auth/register", json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/auth/register", json=payload)
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_register_bad_group_for_class():
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Bad Group",
            "role": "student",
            "board": "PCTB",
            "class_level": 9,
            "student_group": "ics",
            "medium": "en",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CLASS_GROUP"


def test_register_student_missing_fields_validation():
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "No Fields",
            "role": "student",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CLASS_GROUP"


def test_enums_shape():
    resp = client.get("/api/reference/enums")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "PCTB" in {b["code"] for b in body["boards"]}
    assert 9 in body["class_levels"]
    groups_9 = {g["code"] for g in body["groups_by_class"]["9"]}
    assert groups_9 == {"science", "computer"}
    groups_12 = {g["code"] for g in body["groups_by_class"]["12"]}
    assert groups_12 == {"pre_medical", "pre_engineering", "ics"}
    assert body["mediums"] == ["en", "ur"]
    assert body["languages"] == ["en", "ur", "roman_ur"]


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
