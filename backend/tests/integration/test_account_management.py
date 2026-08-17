"""
FR-A8 — manage own account (prd.md:450, tdd.md §3.1). Phase 3.

Three endpoints that the contract specified and the code did not have:

    PATCH /api/auth/me                Update own profile and stored language
    POST  /api/auth/password/change   Requires the current password
    GET   /api/auth/2fa/status        Own second factor, never the secret

⚠️ EVERY REFUSAL HERE THAT MATTERS IS A DATABASE REFUSAL, not an application
   check. `MeUpdateRequest` has no `class_level` field AND `app_backend` holds
   no UPDATE privilege on that column (20260816160000, finding B4). The tests
   below assert the value did not move, which is true under both layers — the
   point of the second one is that it holds if the first grows a field.

Users are built directly on `db` and handed an access token from
`create_access_token`, the same shape `test_authz_matrix.py` uses. Going through
register -> verify -> enrol -> confirm for each case would test the login flow
four more times and this endpoint once.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.auth.security import create_access_token, verify_password
from app.core.db import set_current_user_id

PASSWORD = "password123"  # noqa: S105 -- a fixture value, not a credential
NEW_PASSWORD = "new-password-456"  # noqa: S105

GROUP_BY_CLASS = {9: "science", 10: "computer", 11: "pre_medical", 12: "pre_medical"}


def _create_user(db, email: str, *, role: str = "student", class_level: int = 9) -> str:
    """A live account with a real argon2 hash, bound as itself."""
    from app.auth.security import hash_password

    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user "
            "(id, email, password_hash, role, status, full_name, email_verified_at) "
            "VALUES (:id, :e, :pw, :role, 'active', 'Test User', now())"
        ),
        {"id": user_id, "e": email, "pw": hash_password(PASSWORD), "role": role},
    )
    if role == "student":
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, 'PCTB', :lvl, :grp, 'en', 'en')"
            ),
            {"id": user_id, "lvl": class_level, "grp": GROUP_BY_CLASS[class_level]},
        )
    elif role == "teacher":
        db.execute(text("INSERT INTO teacher_profile (user_id) VALUES (:id)"), {"id": user_id})
    elif role == "parent":
        db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _auth(user_id: str) -> dict[str, str]:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


def _add_refresh_tokens(db, user_id: str, count: int) -> None:
    """
    ⚠️ THROUGH `app.insert_auth_token`, NOT A PLAIN INSERT.

    A direct `INSERT INTO auth_token` is `permission denied for table
    auth_token`, and that is `20260816170000` (finding B6) working exactly as
    designed: the table's INSERT and DELETE grants were revoked when its
    `FOR ALL` policy was split, so a refresh token can only be minted through
    the SECURITY DEFINER function. Writing the fixture the other way would have
    meant a test setting up state by a route production cannot use.

    Same call `tokens.py:_insert_token` makes.
    """
    for i in range(count):
        db.execute(
            text(
                "SELECT app.insert_auth_token("
                "  :u, CAST('refresh' AS token_kind), :h, now() + interval '7 days')"
            ),
            {"u": user_id, "h": f"live-{i}-{user_id}"},
        )
    db.flush()


def _live_refresh_count(db, user_id: str) -> int:
    return db.execute(
        text(
            "SELECT count(*) FROM auth_token "
            " WHERE user_id = :u AND kind = 'refresh' AND revoked = false"
        ),
        {"u": user_id},
    ).scalar()


# ============================================================================
# POST /api/auth/password/change
# ============================================================================


class TestPasswordChange:
    def test_a_wrong_current_password_is_401_unauthenticated(self, client, db, unique_email):
        """
        ⚠️ UNAUTHENTICATED, NOT A NEW CODE. `tdd.md:1053` makes it "also the only
        response meaning 'wrong password'" and `tdd.md:1074` says "No endpoint
        invents a code." A WRONG_PASSWORD code would reach the client as an
        unrecognised string and render as "something went wrong".

        This is also why the client wrapper passes `noRetry: true`: it makes
        this the ONE route where both meanings of 401 are live at once.
        """
        user_id = _create_user(db, unique_email("pwchange"))

        resp = client.post(
            "/api/auth/password/change",
            json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
            headers=_auth(user_id),
        )

        assert resp.status_code == 401, resp.text
        assert resp.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_a_wrong_current_password_does_not_change_anything(self, client, db, unique_email):
        """The refusal must be inert — no hash written, no session ended."""
        user_id = _create_user(db, unique_email("pwchange"))
        _add_refresh_tokens(db, user_id, 2)

        client.post(
            "/api/auth/password/change",
            json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
            headers=_auth(user_id),
        )

        stored = db.execute(
            text("SELECT password_hash FROM app_user WHERE id = :u"), {"u": user_id}
        ).scalar()
        assert verify_password(PASSWORD, stored), "the old password stopped working on a REFUSAL"
        assert _live_refresh_count(db, user_id) == 2, "a refusal logged the user out"

    def test_the_correct_password_changes_it_and_ends_every_session(self, client, db, unique_email):
        user_id = _create_user(db, unique_email("pwchange"))
        _add_refresh_tokens(db, user_id, 3)

        resp = client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=_auth(user_id),
        )

        assert resp.status_code == 204, resp.text
        assert resp.content == b""

        stored = db.execute(
            text("SELECT password_hash FROM app_user WHERE id = :u"), {"u": user_id}
        ).scalar()
        assert verify_password(NEW_PASSWORD, stored)
        assert not verify_password(PASSWORD, stored)
        # ⚠️ INCLUDING THE CALLER'S OWN. A password change that left the current
        #    session alive would not be a response to a compromise.
        assert _live_refresh_count(db, user_id) == 0

    def test_it_writes_an_audit_row(self, client, db, service_conn, unique_email):
        """
        ⚠️ READ AS AN ADMINISTRATOR, AND THAT IS NOT A CONVENIENCE.

        `audit_admin_read` is `FOR SELECT ... USING (app.is_admin())` — the
        trail is append-only from the application and readable by nobody else,
        so the user who just changed their password CANNOT see their own audit
        row. Reading it as them returns zero rows and this test would fail while
        the row sat there, which is the RLS blindness that already cost this
        project two false negatives.

        `service_conn` discovers a committed administrator; the id is then bound
        on `db`, the real path, so `app.is_admin()` is satisfied inside the same
        transaction that holds the uncommitted audit row. Reading through
        `service_conn` itself would see nothing — separate transaction.
        """
        user_id = _create_user(db, unique_email("pwchange"))

        client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=_auth(user_id),
        )

        admin_id = service_conn.execute(
            text("SELECT id FROM app_user WHERE role = 'admin' AND status = 'active' LIMIT 1")
        ).scalar_one_or_none()
        if admin_id is None:
            pytest.skip("needs an owner-provisioned administrator; see the phase 1b handoff, 1.6.6")
        set_current_user_id(db, admin_id)

        rows = db.execute(
            text("SELECT action, target FROM audit_log WHERE actor_id = :u"), {"u": user_id}
        ).all()
        assert [(r[0], r[1]) for r in rows] == [("password_changed", "app_user")]

    def test_only_the_caller_is_affected(self, client, db, unique_email):
        """
        The assertion `app.change_password` exists to make cheap. It takes no
        user identifier at all — the subject is `app.current_user_id()` — so
        there is no argument a bug could aim at somebody else.
        """
        caller = _create_user(db, unique_email("pwchange"))
        bystander = _create_user(db, unique_email("pwchange"))
        _add_refresh_tokens(db, bystander, 2)

        client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=_auth(caller),
        )

        # ⚠️ RE-BIND BEFORE READING. The request just ran `authenticated`, which
        #    bound `caller` on this same connection (conftest patches
        #    SessionLocal onto the test transaction). Without this the read
        #    returns zero rows under `app_user_self_read` and `password_hash`
        #    comes back None — a failure that looks like the endpoint wiping a
        #    bystander's password rather than like the test asking as the wrong
        #    person.
        set_current_user_id(db, bystander)

        other = db.execute(
            text("SELECT password_hash FROM app_user WHERE id = :u"), {"u": bystander}
        ).scalar()
        assert verify_password(PASSWORD, other)
        assert _live_refresh_count(db, bystander) == 2

    def test_it_requires_authentication(self, client):
        resp = client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHENTICATED"

    @pytest.mark.parametrize("new_password", ["short", "x" * 129])
    def test_the_new_password_bounds_match_registration(
        self, client, db, unique_email, new_password
    ):
        """
        8..128, copied from `RegisterRequest.password` rather than chosen again.
        A stricter rule here would reject passwords this same system issued.
        """
        user_id = _create_user(db, unique_email("pwchange"))
        resp = client.post(
            "/api/auth/password/change",
            json={"current_password": PASSWORD, "new_password": new_password},
            headers=_auth(user_id),
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_the_current_password_is_bounded_too(self, client, db, unique_email):
        """
        Finding D12's shape. `current_password` reaches argon2, so an unbounded
        string is an unbounded amount of hashing on an authenticated route.
        """
        user_id = _create_user(db, unique_email("pwchange"))
        resp = client.post(
            "/api/auth/password/change",
            json={"current_password": "x" * 5000, "new_password": NEW_PASSWORD},
            headers=_auth(user_id),
        )
        assert resp.status_code == 400, resp.text


# ============================================================================
# PATCH /api/auth/me
# ============================================================================


class TestUpdateMe:
    def test_it_updates_the_full_name_and_returns_a_whole_me_response(
        self, client, db, unique_email
    ):
        """
        The response is `MeResponse`, produced by delegating to `me()`, so PATCH
        and GET cannot drift into reporting different shapes for one account.
        """
        user_id = _create_user(db, unique_email("patchme"))

        resp = client.patch(
            "/api/auth/me", json={"full_name": "Renamed Person"}, headers=_auth(user_id)
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["full_name"] == "Renamed Person"
        # Every MeResponse field, not just the one that changed.
        #
        # ⚠️ `language_pref` JOINED THE TOP LEVEL AFTER THIS TEST CAUGHT ITS
        #    ABSENCE. `20260816200000` moved the column to `app_user` so all four
        #    roles could have a stored language, and `PATCH /auth/me` accepted it
        #    from all four — but this response carried it only inside `profile`,
        #    which is `null` for teachers, parents and administrators. Writable
        #    by every role, readable by one: a teacher who chose Urdu opened the
        #    settings screen and saw English.
        assert set(body) == {
            "user_id",
            "email",
            "full_name",
            "language_pref",
            "role",
            "onboarding_state",
            "email_verified",
            "two_factor",
            "profile",
            "guardian",
        }
        assert client.get("/api/auth/me", headers=_auth(user_id)).json() == body

    @pytest.mark.parametrize("role", ["teacher", "parent"])
    def test_a_non_student_may_set_their_stored_language(self, client, db, unique_email, role):
        """
        ⚠️ THE WHOLE REASON 20260816200000 EXISTS. FR-A8 is "Role: all", and
        before that migration `language_pref` lived on `student_profile` — a
        table this user has no row in. The endpoint had nowhere to write the
        answer, so three roles out of four could never satisfy the acceptance
        criterion about outgoing email.
        """
        user_id = _create_user(db, unique_email("patchme"), role=role)

        resp = client.patch("/api/auth/me", json={"language_pref": "ur"}, headers=_auth(user_id))

        assert resp.status_code == 200, resp.text
        stored = db.execute(
            text("SELECT language_pref FROM app_user WHERE id = :u"), {"u": user_id}
        ).scalar()
        assert str(stored) == "ur"

    def test_a_teachers_choice_reaches_the_email_lookup(self, client, db, unique_email):
        """
        ⚠️ ASSERTED THROUGH `app.lookup_user_for_email_flow`, NOT THE ORM.

        That function is what `password/forgot` and `email/resend` actually call
        to pick a locale (`service.py:_locale_of`), it is SECURITY DEFINER, and
        it used to LEFT JOIN `student_profile` — so it returned NULL here and
        the caller fell back to English, silently and for ever. A test that read
        the column directly would pass while the emails stayed English.
        """
        email = unique_email("patchme")
        user_id = _create_user(db, email, role="teacher")

        client.patch("/api/auth/me", json={"language_pref": "ur"}, headers=_auth(user_id))

        pref = db.execute(
            text("SELECT language_pref FROM app.lookup_user_for_email_flow(:e)"), {"e": email}
        ).scalar()
        assert pref is not None, "a non-student's language is NULL again -- the LEFT JOIN is back"
        assert str(pref) == "ur"

    def test_a_students_language_shows_up_in_their_profile_block(self, client, db, unique_email):
        """
        `MeResponse.profile.language_pref` now reads `app_user`, so the settings
        screen cannot display one language while mail is sent in another.
        """
        user_id = _create_user(db, unique_email("patchme"))

        body = client.patch(
            "/api/auth/me", json={"language_pref": "roman_ur"}, headers=_auth(user_id)
        ).json()

        assert body["profile"]["language_pref"] == "roman_ur"

    def test_updating_one_field_leaves_the_other_alone(self, client, db, unique_email):
        """A PATCH is not a PUT; an absent field is absent, not null."""
        user_id = _create_user(db, unique_email("patchme"))
        client.patch("/api/auth/me", json={"language_pref": "ur"}, headers=_auth(user_id))

        body = client.patch(
            "/api/auth/me", json={"full_name": "Only The Name"}, headers=_auth(user_id)
        ).json()

        assert body["full_name"] == "Only The Name"
        assert body["profile"]["language_pref"] == "ur"

    def test_an_empty_body_is_rejected(self, client, db, unique_email):
        """
        Otherwise a client posting the wrong shape gets 200 and the current row,
        which is indistinguishable from "your change was saved".
        """
        user_id = _create_user(db, unique_email("patchme"))
        resp = client.patch("/api/auth/me", json={}, headers=_auth(user_id))
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        ("field", "value"),
        [("class_level", 11), ("board", "STBB"), ("student_group", "pre_medical")],
    )
    def test_the_curriculum_context_cannot_be_changed_through_this_endpoint(
        self, client, db, unique_email, field, value
    ):
        """
        ⚠️ `class_level` IS THE PARENTAL-CONSENT GATE INPUT. A Class 9 student
        who could set 11 would leave the gate permanently — that is finding B4,
        and `20260816160000:86-94` records why `board` and `student_group` are
        equally closed: they scope every progress record ever written, so
        changing one silently reinterprets the student's whole history.

        The assertion is that the VALUE DID NOT MOVE, which holds under both
        layers: the field is absent from `MeUpdateRequest`, and `app_backend`
        holds no UPDATE privilege on the column either way.
        """
        user_id = _create_user(db, unique_email("patchme"), class_level=9)

        resp = client.patch(
            "/api/auth/me",
            json={"full_name": "Legitimate Change", field: value},
            headers=_auth(user_id),
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["profile"]["class_level"] == 9
        assert resp.json()["profile"]["board"] == "PCTB"
        assert resp.json()["profile"]["student_group"] == "science"

    def test_it_requires_authentication(self, client):
        resp = client.patch("/api/auth/me", json={"full_name": "Nobody"})
        assert resp.status_code == 401


# ============================================================================
# GET /api/auth/2fa/status
# ============================================================================


def _enrol(db, user_id: str, *, method: str = "totp", codes: int = 0, active: bool = True) -> None:
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO two_factor_enrollment "
            "(user_id, method, status, totp_secret_encrypted, confirmed_at) "
            "VALUES (:u, :m, :s, :secret, :confirmed)"
        ),
        {
            "u": user_id,
            "m": method,
            "s": "active" if active else "pending",
            # ck_totp_requires_secret / ck_email_otp_has_no_secret.
            "secret": b"\x00" * 32 if method == "totp" else None,
            # ck_active_is_confirmed.
            "confirmed": "now()" if active else None,
        },
    )
    for i in range(codes):
        db.execute(
            text("INSERT INTO two_factor_backup_code (user_id, code_hash) VALUES (:u, :h)"),
            {"u": user_id, "h": f"hash-{i}-{user_id}"},
        )
    db.flush()


class TestTwoFactorStatus:
    def test_an_account_that_never_enrolled_reports_disabled(self, client, db, unique_email):
        """No row is not an error — it is the answer."""
        user_id = _create_user(db, unique_email("2fastatus"))

        body = client.get("/api/auth/2fa/status", headers=_auth(user_id)).json()

        assert body == {
            "enabled": False,
            "method": None,
            "locked_until": None,
            "backup_codes_remaining": 0,
        }

    def test_an_active_enrolment_reports_its_method_and_remaining_codes(
        self, client, db, unique_email
    ):
        """
        Closes card 1.3's success criterion (`user-stories.md:93`): the remaining
        count is visible WITHOUT regenerating, which previously required calling
        the endpoint that replaces every code.
        """
        user_id = _create_user(db, unique_email("2fastatus"))
        _enrol(db, user_id, method="totp", codes=8)

        body = client.get("/api/auth/2fa/status", headers=_auth(user_id)).json()

        assert body["enabled"] is True
        assert body["method"] == "totp"
        assert body["backup_codes_remaining"] == 8

    def test_a_used_code_stops_counting(self, client, db, unique_email):
        user_id = _create_user(db, unique_email("2fastatus"))
        _enrol(db, user_id, codes=3)
        db.execute(
            text(
                "UPDATE two_factor_backup_code SET used_at = now() "
                " WHERE user_id = :u AND code_hash = :h"
            ),
            {"u": user_id, "h": f"hash-0-{user_id}"},
        )
        db.flush()

        body = client.get("/api/auth/2fa/status", headers=_auth(user_id)).json()

        assert body["backup_codes_remaining"] == 2

    def test_a_pending_enrolment_is_not_a_second_factor(self, client, db, unique_email):
        """
        Mirrors `MeResponse.two_factor`, which reports the method only while the
        enrolment is active. Reporting `enabled: true` for a pending row would
        tell a settings screen the account is protected when it is not.
        """
        user_id = _create_user(db, unique_email("2fastatus"))
        _enrol(db, user_id, active=False)

        body = client.get("/api/auth/2fa/status", headers=_auth(user_id)).json()

        assert body["enabled"] is False
        assert body["method"] is None

    def test_one_account_cannot_see_anothers(self, client, db, unique_email):
        """
        ⚠️ WHAT `security_invoker` BOUGHT, pinned as a test.

        `two_factor_status_v` ran as its OWNER until `20260816150000`, which
        skipped the owner-scoped policies on both underlying tables entirely.
        Measured then from the application connection: a caller owning nothing
        read 7 of 7 accounts through the view while the tables returned 0.
        Reverting that one `ALTER VIEW` must fail here.
        """
        first = _create_user(db, unique_email("2fastatus"))
        _enrol(db, first, method="totp", codes=10)
        second = _create_user(db, unique_email("2fastatus"))

        body = client.get("/api/auth/2fa/status", headers=_auth(second)).json()

        assert body["enabled"] is False, "the second account is reading the first one's enrolment"
        assert body["backup_codes_remaining"] == 0

    def test_it_never_returns_the_secret(self, client, db, unique_email):
        """
        `tdd.md:195` — "Never returns the secret". `user-stories.md:97` makes
        retrieving it a failure criterion.

        The real guarantee is structural: `two_factor_status_v` was built
        without `totp_secret_encrypted` or `last_used_counter`
        (20260801120000:236-242), so there is nothing to leak even by accident.
        This asserts the response shape as the outward half of that.
        """
        user_id = _create_user(db, unique_email("2fastatus"))
        _enrol(db, user_id, method="totp", codes=2)

        resp = client.get("/api/auth/2fa/status", headers=_auth(user_id))

        assert set(resp.json()) == {
            "enabled",
            "method",
            "locked_until",
            "backup_codes_remaining",
        }
        for forbidden in ("secret", "totp_secret", "code_hash", "last_used_counter"):
            assert forbidden not in resp.text

    def test_it_requires_authentication(self, client):
        resp = client.get("/api/auth/2fa/status")
        assert resp.status_code == 401
