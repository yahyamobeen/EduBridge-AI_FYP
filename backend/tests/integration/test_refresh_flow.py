from uuid import uuid4

from sqlalchemy import text

from app.auth.tokens import issue_refresh_token
from app.core.db import set_current_user_id


def _user_with_refresh_token(client, db) -> tuple[str, str]:
    """
    Register through the API, then mint a refresh token directly.

    Registration deliberately issues no session — the account starts at
    `email_verification_pending` — so there is no legitimate route to a refresh
    token yet. 2FA verification is what normally produces one, and that is
    Muneeb's card.
    """
    email = f"{uuid4().hex[:12]}@test.com"
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Refresh User",
            "turnstile_token": "test-turnstile-token",
            "role": "parent",
        },
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["user_id"]

    set_current_user_id(db, user_id)
    plain, _ = issue_refresh_token(db, user_id)
    db.flush()
    return user_id, plain


def test_refresh_rotates_and_replay_fails(client, db):
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    first = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"  # noqa: S105 -- a scheme name
    assert body["expires_in"] > 0

    new_cookie = first.cookies.get("refresh_token")
    assert new_cookie and new_cookie != plain

    # The rotated token must never appear in the body — only in the httpOnly
    # cookie, so it cannot reach a log or a client store.
    assert "refresh_token" not in body

    replay = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "UNAUTHENTICATED"


def test_replay_revokes_the_whole_family(client, db):
    """
    Reuse means two parties hold the token. Answering 401 and stopping there
    would leave a thief who redeemed first with a working rotating chain, so the
    token issued a moment ago has to die as well.
    """
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    first = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert first.status_code == 200
    rotated = first.cookies.get("refresh_token")

    # Replay the spent one: detected as reuse.
    assert client.post("/api/auth/refresh", cookies={"refresh_token": plain}).status_code == 401

    after = client.post("/api/auth/refresh", cookies={"refresh_token": rotated})
    assert after.status_code == 401, "the rotated token survived a detected reuse"


def test_refresh_then_me(client, db):
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    resp = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert resp.status_code == 200
    access = resp.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    assert me.json()["onboarding_state"] == "email_verification_pending"


def test_logout_then_refresh_401(client, db):
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    resp = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert resp.status_code == 200
    access = resp.json()["access_token"]
    rotated = resp.cookies.get("refresh_token")

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert logout.status_code == 204

    stale = client.post("/api/auth/refresh", cookies={"refresh_token": rotated})
    assert stale.status_code == 401


def test_registered_student_has_a_trial_row(client, db):
    """
    Rule 4 of the derivation fails closed, so a missing subscription row would
    put every student into plan selection the moment they clear the guardian
    gate, having never had the 14-day trial the product promises.
    """
    email = f"{uuid4().hex[:12]}@test.com"
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Trial Check",
            "turnstile_token": "test-turnstile-token",
            "role": "student",
            "board": "PCTB",
            "class_level": 11,
            "student_group": "ics",
            "medium": "en",
        },
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["user_id"]

    set_current_user_id(db, user_id)
    row = (
        db.execute(
            text("SELECT status, trial_ends_at FROM subscription WHERE user_id = :uid"),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    assert row is not None, "registration did not start a trial"
    assert str(row["status"]) == "trialing"
    # The 14 days come from the schema default, never from Python.
    assert row["trial_ends_at"] is not None
