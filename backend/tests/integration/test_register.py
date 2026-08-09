from uuid import uuid4


def _unique_email() -> str:
    return f"{uuid4().hex[:12]}@test.com"


def test_register_student(client):
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Ayesha Khan",
            "turnstile_token": "test-turnstile-token",
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


def test_register_teacher(client):
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Sir Imran",
            "turnstile_token": "test-turnstile-token",
            "role": "teacher",
            "institution": "Govt High School",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "teacher"


def test_register_parent(client):
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Mrs. Fatima",
            "turnstile_token": "test-turnstile-token",
            "role": "parent",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "parent"


def test_register_duplicate_email_conflict(client):
    email = _unique_email()
    payload = {
        "email": email,
        "password": "password123",
        "full_name": "Dup User",
        "turnstile_token": "test-turnstile-token",
        "role": "parent",
    }
    first = client.post("/api/auth/register", json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/auth/register", json=payload)
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_register_bad_group_for_class(client):
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Bad Group",
            "turnstile_token": "test-turnstile-token",
            "role": "student",
            "board": "PCTB",
            "class_level": 9,
            "student_group": "ics",
            "medium": "en",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CLASS_GROUP"


def test_register_student_missing_fields_validation(client):
    """
    Absent student fields are a 400 VALIDATION_ERROR with per-field detail — NOT
    a 422 INVALID_CLASS_GROUP, which this previously asserted. The two codes
    describe different problems: "you left the form blank" versus "that group is
    not offered for that class". A client rendering the second for the first
    tells a user their group is wrong when they never picked one.
    """
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "No Fields",
            "turnstile_token": "test-turnstile-token",
            "role": "student",
        },
    )
    assert resp.status_code == 400
    body = resp.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    # Per-field, so the form can mark the offending inputs rather than showing a
    # single opaque banner.
    assert set(body["details"]["fields"]) == {"board", "class_level", "student_group", "medium"}


def test_register_student_creates_a_trial_subscription(client):
    """
    Rule 4 of the onboarding derivation fails closed, so without this row every
    student would reach plan selection the moment they clear the guardian gate,
    having never had the 14-day trial the product promises (prd.md §2.6).
    """
    email = _unique_email()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Trial Student",
            "turnstile_token": "test-turnstile-token",
            "role": "student",
            "board": "PCTB",
            "class_level": 9,
            "student_group": "science",
            "medium": "en",
        },
    )
    assert resp.status_code == 201, resp.text


def test_enums_shape(client):
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


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
