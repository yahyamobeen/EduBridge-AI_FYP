from uuid import uuid4

from sqlalchemy import text

from app.auth.tokens import issue_refresh_token
from app.core.config import get_settings
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


def test_replay_revokes_the_whole_family(client, db, monkeypatch):
    """
    Reuse means two parties hold the token. Answering 401 and stopping there
    would leave a thief who redeemed first with a working rotating chain, so the
    token issued a moment ago has to die as well.

    ⚠️ THE REPLAY IS AGED PAST THE GRACE WINDOW IN PHASE 4, AND WITHOUT THAT LINE
       THIS TEST NOW ASSERTS THE WRONG THING.

    An IMMEDIATE replay is no longer read as theft: two browser tabs refreshing
    together present the same token twice, because the client's single-flight
    guard is per tab, and revoking the family there signed honest users out of
    every device. `app.rotate_refresh_token` forgives a replay only while the
    revocation is fresh AND a live sibling of the same family exists.

    A stolen token replayed LATER is exactly what reuse detection is for, and
    that is what this test must exercise. Closing the window to zero reaches it
    without sleeping ten real seconds. The test below covers the race side.
    """
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    first = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert first.status_code == 200
    rotated = first.cookies.get("refresh_token")

    monkeypatch.setattr(get_settings(), "refresh_race_grace_seconds", 0)

    # Replay the spent one: detected as reuse.
    assert client.post("/api/auth/refresh", cookies={"refresh_token": plain}).status_code == 401

    after = client.post("/api/auth/refresh", cookies={"refresh_token": rotated})
    assert after.status_code == 401, "the rotated token survived a detected reuse"


def test_two_tabs_racing_does_not_sign_the_user_out_of_everything(client, db):
    """
    ⚠️ THE BEHAVIOUR THE TEST ABOVE USED TO PREVENT, now asserted directly.

    Two tabs refresh with the same token. One wins. The loser must get a plain
    401 and the winner's session must survive — before Phase 4 the loser tripped
    reuse detection and killed both.
    """
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    winner = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert winner.status_code == 200
    rotated = winner.cookies.get("refresh_token")

    loser = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert loser.status_code == 401

    still_alive = client.post("/api/auth/refresh", cookies={"refresh_token": rotated})
    assert still_alive.status_code == 200, "a two-tab race revoked the winner's session"


def test_refresh_then_me(client, db):
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    resp = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert resp.status_code == 200
    access = resp.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    assert me.json()["onboarding_state"] == "email_verification_pending"


def test_logout_clears_the_cookie_so_the_next_refresh_is_not_read_as_theft(client, db):
    """
    Finding A2.

    THE PREVIOUS VERSION OF THIS TEST ASSERTED THE BUG AS CORRECT. It logged
    out, then hand-fed the revoked token back to `/auth/refresh` and asserted
    401 — which passes whether or not the cookie is cleared, because supplying
    the cookie manually bypasses the very thing that was broken. Worse, the 401
    it asserted came from the REUSE-DETECTION path, so the test's happy ending
    was a `refresh_token_reuse_detected` audit row and an account-wide family
    revocation on an ordinary sign-out.

    What matters is the message, not the status. Both paths answer 401:
      * "Missing refresh token."            -> no cookie was presented. Correct.
      * "Invalid or expired refresh token." -> reuse detection. Revokes the
                                               family and writes a breach row.
    """
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    resp = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert resp.status_code == 200
    access = resp.json()["access_token"]

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert logout.status_code == 204

    # The response must ACTIVELY clear it, on the same path it was set on — a
    # browser only overwrites a cookie when name and path match.
    set_cookie = logout.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie, "logout sent no Set-Cookie at all"
    assert "Path=/api/auth/refresh" in set_cookie, set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower(), set_cookie

    # And the client honoured it, so there is nothing left to present.
    assert not client.cookies.get("refresh_token")

    stale = client.post("/api/auth/refresh")
    assert stale.status_code == 401
    assert stale.json()["error"]["message"] == "Missing refresh token.", (
        "sign-out left a usable cookie, so refresh took the reuse-detection path "
        "and recorded a breach that never happened"
    )


def test_a_revoked_token_deliberately_re_presented_is_still_refused(client, db):
    """
    The property the old test was reaching for, kept and correctly labelled.

    A revoked token must never work again, however it arrives — this is the
    theft case, and here the reuse path firing is exactly right. Separated from
    the test above so that one can assert the sign-out path is NOT this one.
    """
    _, plain = _user_with_refresh_token(client, db)
    client.cookies.clear()

    resp = client.post("/api/auth/refresh", cookies={"refresh_token": plain})
    assert resp.status_code == 200
    access = resp.json()["access_token"]
    rotated = resp.cookies.get("refresh_token")

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert logout.status_code == 204

    client.cookies.clear()
    replayed = client.post("/api/auth/refresh", cookies={"refresh_token": rotated})
    assert replayed.status_code == 401


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
