"""
Classroom Phase 2 — the HTTP surface over the database boundary.

`test_classroom_rls.py` proves the DATABASE refuses; this file proves the
ROUTES expose exactly what the contract says (tdd.md §3.6) and translate every
database outcome into a catalogued response (tdd.md §7.3). The real app, the
real dependencies, the real functions — only the transaction is rolled back.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.auth.security import create_access_token
from app.core.db import set_current_user_id

GROUP_BY_CLASS = {9: "science", 10: "computer", 11: "pre_medical", 12: "pre_medical"}


def _user(db, *, role: str, class_level: int = 11, group: str | None = None, board="PCTB") -> str:
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
            "VALUES (:id, :email, 'x', :role, 'active', :name)"
        ),
        {
            "id": user_id,
            "email": f"{role}-{user_id}@example.com",
            "role": role,
            "name": f"{role.title()} {user_id.hex[:6]}",
        },
    )
    if role == "student":
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, CAST(:board AS board_code), :lvl, "
                "        CAST(:grp AS student_group), 'en', 'en')"
            ),
            {
                "id": user_id,
                "board": board,
                "lvl": class_level,
                "grp": group or GROUP_BY_CLASS[class_level],
            },
        )
    elif role == "teacher":
        db.execute(text("INSERT INTO teacher_profile (user_id) VALUES (:id)"), {"id": user_id})
    elif role == "parent":
        db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


def _subject(db, name: str = "Physics", *, level: int = 11) -> str:
    return str(
        db.execute(
            text(
                "SELECT s.id FROM subject s "
                "  JOIN class_level cl ON cl.id = s.class_level_id "
                "  JOIN board b ON b.id = cl.board_id "
                " WHERE b.code = 'PCTB' AND cl.level = :lvl AND s.name = :name"
            ),
            {"lvl": level, "name": name},
        ).scalar_one()
    )


def _create(client, teacher: str, subject_id: str, title: str = "Physics 11-A") -> dict:
    resp = client.post(
        "/api/spaces", json={"title": title, "subject_id": subject_id}, headers=_auth(teacher)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _join(client, student: str, code: str):
    return client.post("/api/spaces/join", json={"code": code}, headers=_auth(student))


@pytest.fixture
def teacher(db) -> str:
    return _user(db, role="teacher")


@pytest.fixture
def space(client, db, teacher) -> dict:
    return _create(client, teacher, _subject(db))


# ── create and read ─────────────────────────────────────────────────────────


class TestCreate:
    def test_teacher_creates_a_classroom_with_a_live_code(self, space):
        assert space["viewer_role"] == "owner"
        assert space["can_manage"] is True
        assert space["member_count"] == 0
        assert space["subject"]["name"] == "Physics"
        assert (space["subject"]["board"], space["subject"]["class_level"]) == ("PCTB", 11)
        assert len(space["join_code"]) == 8

    def test_blank_title_is_a_400_not_a_500(self, client, db, teacher):
        resp = client.post(
            "/api/spaces", json={"title": "   ", "subject_id": _subject(db)}, headers=_auth(teacher)
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_unknown_subject(self, client, teacher):
        resp = client.post(
            "/api/spaces", json={"title": "X", "subject_id": str(uuid4())}, headers=_auth(teacher)
        )
        assert resp.status_code == 400
        assert "subject_id" in resp.json()["error"]["details"]["fields"]

    @pytest.mark.parametrize("role", ["student", "parent"])
    def test_only_teachers_create(self, client, db, role):
        resp = client.post(
            "/api/spaces",
            json={"title": "Mine", "subject_id": _subject(db)},
            headers=_auth(_user(db, role=role)),
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    def test_a_parent_cannot_list_classrooms(self, client, db):
        resp = client.get("/api/spaces", headers=_auth(_user(db, role="parent")))
        assert resp.status_code == 403


class TestReadsNeverLeak:
    def test_unknown_and_foreign_classroom_are_indistinguishable(self, client, db, space):
        intruder = _user(db, role="teacher")
        foreign = client.get(f"/api/spaces/{space['id']}", headers=_auth(intruder))
        unknown = client.get(f"/api/spaces/{uuid4()}", headers=_auth(intruder))
        assert foreign.status_code == unknown.status_code == 403
        assert foreign.json() == unknown.json()

    def test_a_member_never_sees_the_code_or_the_head_count(self, client, db, space):
        student = _user(db, role="student")
        assert _join(client, student, space["join_code"]).status_code == 200
        detail = client.get(f"/api/spaces/{space['id']}", headers=_auth(student)).json()
        assert detail["viewer_role"] == "member"
        assert detail["join_code"] is None
        assert detail["member_count"] is None
        assert detail["can_manage"] is False

    def test_members_see_names_but_not_mute_flags(self, client, db, teacher, space):
        a, b = _user(db, role="student"), _user(db, role="student")
        for s in (a, b):
            assert _join(client, s, space["join_code"]).status_code == 200
        people = client.get(f"/api/spaces/{space['id']}/people", headers=_auth(a)).json()
        assert people["owner"]["user_id"] == teacher
        assert {m["user_id"] for m in people["members"]} == {a, b}
        assert all(m["muted"] is None for m in people["members"])
        owner_view = client.get(f"/api/spaces/{space['id']}/people", headers=_auth(teacher)).json()
        assert all(m["muted"] is False for m in owner_view["members"])

    def test_people_is_forbidden_to_outsiders(self, client, db, space):
        resp = client.get(
            f"/api/spaces/{space['id']}/people", headers=_auth(_user(db, role="student"))
        )
        assert resp.status_code == 403


# ── joining ─────────────────────────────────────────────────────────────────


class TestJoin:
    def test_join_then_list(self, client, db, space):
        student = _user(db, role="student")
        resp = _join(client, student, space["join_code"].lower())
        assert resp.status_code == 200
        assert resp.json() == {"space_id": space["id"], "already_member": False}
        listed = client.get("/api/spaces", headers=_auth(student)).json()["spaces"]
        assert [s["id"] for s in listed] == [space["id"]]

    def test_second_join_is_idempotent(self, client, db, space):
        student = _user(db, role="student")
        _join(client, student, space["join_code"])
        assert _join(client, student, space["join_code"]).json()["already_member"] is True

    def test_invalid_code(self, client, db, space):
        resp = _join(client, _user(db, role="student"), "ZZZZZZZZ")
        assert resp.status_code == 400
        assert resp.json()["error"]["details"]["reason"] == "invalid_code"

    def test_class_mismatch_names_the_class(self, client, db, space):
        resp = _join(client, _user(db, role="student", class_level=12), space["join_code"])
        assert resp.status_code == 400
        details = resp.json()["error"]["details"]
        assert details["reason"] == "class_mismatch"
        assert (details["space"]["board"], details["space"]["class_level"]) == ("PCTB", 11)

    def test_class_9_without_guardian_is_gated_at_the_route(self, client, db, teacher):
        nine = _create(client, teacher, _subject(db, level=9))
        resp = _join(client, _user(db, role="student", class_level=9), nine["join_code"])
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "GATE_PENDING"

    def test_a_teacher_cannot_join(self, client, db, space):
        assert _join(client, _user(db, role="teacher"), space["join_code"]).status_code == 403

    def test_join_is_rate_limited_per_account(self, client, db, space):
        student = _user(db, role="student")
        codes = [_join(client, student, "ZZZZZZZZ").status_code for _ in range(11)]
        assert codes[:10] == [400] * 10
        assert codes[10] == 429


# ── leaving and removal ─────────────────────────────────────────────────────


class TestLeaveAndRemove:
    def test_leave_is_a_silent_idempotent_204(self, client, db, space):
        student = _user(db, role="student")
        _join(client, student, space["join_code"])
        url = f"/api/spaces/{space['id']}/membership"
        assert client.delete(url, headers=_auth(student)).status_code == 204
        assert client.delete(url, headers=_auth(student)).status_code == 204
        assert (
            client.delete(f"/api/spaces/{uuid4()}/membership", headers=_auth(student)).status_code
            == 204
        )
        assert client.get("/api/spaces", headers=_auth(student)).json()["spaces"] == []

    def test_a_student_who_became_gated_can_still_leave(self, client, db, teacher, make_link):
        """Leaving is a consent right (prd.md §4.2): a revoked link must not trap a student."""
        nine = _create(client, teacher, _subject(db, level=9))
        student = _user(db, role="student", class_level=9)
        parent = _user(db, role="parent")
        make_link(parent_id=parent, student_id=student, status="verified")
        assert _join(client, student, nine["join_code"]).status_code == 200

        set_current_user_id(db, UUID(parent))  # the parent withdraws consent
        db.execute(
            text("UPDATE guardian_link SET status = 'revoked' WHERE student_id = :s"),
            {"s": student},
        )
        db.flush()

        assert client.get("/api/spaces", headers=_auth(student)).status_code == 403  # gated
        left = client.delete(f"/api/spaces/{nine['id']}/membership", headers=_auth(student))
        assert left.status_code == 204
        set_current_user_id(db, UUID(student))
        assert (
            db.execute(
                text("SELECT left_at IS NOT NULL FROM enrollment WHERE student_id = :s"),
                {"s": student},
            ).scalar_one()
            is True
        )

    def test_removed_student_cannot_rejoin(self, client, db, teacher, space):
        student = _user(db, role="student")
        _join(client, student, space["join_code"])
        resp = client.delete(f"/api/spaces/{space['id']}/members/{student}", headers=_auth(teacher))
        assert resp.status_code == 204
        rejoin = _join(client, student, space["join_code"])
        assert rejoin.status_code == 400
        assert rejoin.json()["error"]["details"]["reason"] == "invalid_code"

    def test_only_the_owner_removes(self, client, db, space):
        student = _user(db, role="student")
        _join(client, student, space["join_code"])
        resp = client.delete(
            f"/api/spaces/{space['id']}/members/{student}", headers=_auth(_user(db, role="teacher"))
        )
        assert resp.status_code == 403


# ── management ──────────────────────────────────────────────────────────────


class TestManage:
    def test_rename_and_archive(self, client, teacher, space):
        resp = client.patch(
            f"/api/spaces/{space['id']}",
            json={"title": "  Renamed  ", "status": "archived"},
            headers=_auth(teacher),
        )
        assert resp.status_code == 200
        assert (resp.json()["title"], resp.json()["status"]) == ("Renamed", "archived")

    def test_empty_patch_is_a_400(self, client, teacher, space):
        resp = client.patch(f"/api/spaces/{space['id']}", json={}, headers=_auth(teacher))
        assert resp.status_code == 400

    def test_a_member_cannot_manage(self, client, db, space):
        student = _user(db, role="student")
        _join(client, student, space["join_code"])
        headers = _auth(student)
        assert (
            client.patch(
                f"/api/spaces/{space['id']}", json={"title": "x"}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/spaces/{space['id']}/join-code", json={"action": "rotate"}, headers=headers
            ).status_code
            == 403
        )

    def test_rotate_replaces_and_disable_closes(self, client, db, teacher, space):
        url = f"/api/spaces/{space['id']}/join-code"
        rotated = client.post(url, json={"action": "rotate"}, headers=_auth(teacher)).json()
        assert rotated["join_code"] != space["join_code"]
        old = _join(client, _user(db, role="student"), space["join_code"])
        assert old.json()["error"]["details"]["reason"] == "invalid_code"

        disabled = client.post(url, json={"action": "disable"}, headers=_auth(teacher)).json()
        assert disabled == {"join_code": None}
        new = _join(client, _user(db, role="student"), rotated["join_code"])
        assert new.json()["error"]["details"]["reason"] == "invalid_code"

    def test_unarchiving_respects_the_active_classroom_cap(self, client, db, teacher):
        subject = _subject(db)
        archived = _create(client, teacher, subject, title="Old")
        client.patch(
            f"/api/spaces/{archived['id']}", json={"status": "archived"}, headers=_auth(teacher)
        )
        set_current_user_id(db, UUID(teacher))
        for i in range(50):
            db.execute(text("SELECT app.create_space(:t, :s)"), {"t": f"C{i}", "s": subject})
        db.flush()
        resp = client.patch(
            f"/api/spaces/{archived['id']}", json={"status": "active"}, headers=_auth(teacher)
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["details"]["reason"] == "classroom_limit"


# ── reference ───────────────────────────────────────────────────────────────


class TestSubjects:
    def test_requires_a_session(self, client):
        assert client.get("/api/reference/subjects?board=PCTB&class_level=9").status_code == 401

    def test_lists_subjects_with_their_groups(self, client, teacher):
        resp = client.get(
            "/api/reference/subjects?board=PCTB&class_level=9", headers=_auth(teacher)
        )
        assert resp.status_code == 200
        physics = next(s for s in resp.json()["subjects"] if s["name"] == "Physics")
        assert "science" in physics["groups"]

    def test_class_level_is_bounded(self, client, teacher):
        resp = client.get(
            "/api/reference/subjects?board=PCTB&class_level=13", headers=_auth(teacher)
        )
        assert resp.status_code == 400
