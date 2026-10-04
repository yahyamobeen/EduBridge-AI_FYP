"""
Classroom Phase 3 — the stream (announcements) over HTTP.

`test_classroom_rls.py` proves the database refuses; this proves the routes
expose exactly the contract (tdd.md §3.6): scheduling is invisible to members,
only a scheduled post can be rescheduled, times are checked against the
database clock, pages are complete and never repeat, and every refusal is a
catalogued code.

⚠️ `now()` IS FROZEN FOR THE WHOLE TEST: each test runs in one transaction, so
   every "post now" shares the same `publish_at`. Ordering ties fall to the id,
   and these tests assert completeness and no-repeats rather than wall-clock
   order — the keyset is (publish_at, id) precisely so ties are still ordered.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.auth.security import create_access_token
from app.core.db import set_current_user_id


def _user(db, *, role: str, class_level: int = 11) -> str:
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
            "VALUES (:id, :email, 'x', :role, 'active', :name)"
        ),
        {"id": user_id, "email": f"{role}-{user_id}@example.com", "role": role, "name": role},
    )
    if role == "student":
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, 'PCTB', :lvl, 'pre_medical', 'en', 'en')"
            ),
            {"id": user_id, "lvl": class_level},
        )
    elif role == "teacher":
        db.execute(text("INSERT INTO teacher_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


@pytest.fixture
def teacher(db) -> str:
    return _user(db, role="teacher")


@pytest.fixture
def space(client, db, teacher) -> dict:
    subject = db.execute(
        text(
            "SELECT s.id FROM subject s JOIN class_level cl ON cl.id = s.class_level_id "
            "JOIN board b ON b.id = cl.board_id "
            "WHERE b.code = 'PCTB' AND cl.level = 11 AND s.name = 'Physics'"
        )
    ).scalar_one()
    resp = client.post(
        "/api/spaces",
        json={"title": "Physics 11-A", "subject_id": str(subject)},
        headers=_auth(teacher),
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
def student(client, db, space) -> str:
    s = _user(db, role="student")
    assert (
        client.post(
            "/api/spaces/join", json={"code": space["join_code"]}, headers=_auth(s)
        ).status_code
        == 200
    )
    return s


def _post(client, teacher, space, **body):
    return client.post(
        f"/api/spaces/{space['id']}/announcements",
        json={"body": "Notice", **body},
        headers=_auth(teacher),
    )


def _stream(client, user, space, cursor=None):
    url = f"/api/spaces/{space['id']}/announcements"
    return client.get(url, params={"cursor": cursor} if cursor else None, headers=_auth(user))


class TestPostAndRead:
    def test_a_post_reaches_members(self, client, teacher, space, student):
        created = _post(client, teacher, space, body="  Test on Monday  ")
        assert created.status_code == 201
        assert created.json()["body"] == "Test on Monday"
        assert created.json()["scheduled"] is False
        items = _stream(client, student, space).json()["items"]
        assert [i["body"] for i in items] == ["Test on Monday"]

    def test_a_scheduled_post_is_hidden_from_members_until_its_time(
        self, client, teacher, space, student
    ):
        later = _post(client, teacher, space, body="later", publish_at=_iso(timedelta(hours=2)))
        assert later.status_code == 201
        assert later.json()["scheduled"] is True
        assert _stream(client, student, space).json()["items"] == []
        owner_view = _stream(client, teacher, space).json()["items"]
        assert [(i["body"], i["scheduled"]) for i in owner_view] == [("later", True)]

    @pytest.mark.parametrize(
        "publish_at",
        [_iso(timedelta(hours=-1)), _iso(timedelta(days=400))],
        ids=["in the past", "more than a year ahead"],
    )
    def test_a_schedule_must_be_in_the_next_year(self, client, teacher, space, publish_at):
        resp = _post(client, teacher, space, publish_at=publish_at)
        assert resp.status_code == 400
        assert "publish_at" in resp.json()["error"]["details"]["fields"]

    def test_a_schedule_without_a_time_zone_is_refused(self, client, teacher, space):
        resp = _post(client, teacher, space, publish_at="2030-01-01T10:00:00")
        assert resp.status_code == 400

    def test_a_member_cannot_post(self, client, space, student):
        assert _post(client, student, space).status_code == 403

    def test_an_outsider_cannot_read(self, client, db, space):
        resp = _stream(client, _user(db, role="student"), space)
        assert resp.status_code == 403

    def test_an_archived_classroom_is_read_only(self, client, teacher, space, student):
        assert _post(client, teacher, space, body="before").status_code == 201
        client.patch(
            f"/api/spaces/{space['id']}", json={"status": "archived"}, headers=_auth(teacher)
        )
        assert _post(client, teacher, space, body="after").status_code == 403
        assert [i["body"] for i in _stream(client, student, space).json()["items"]] == ["before"]


class TestPagination:
    def test_pages_are_complete_and_never_repeat(self, client, teacher, space, student):
        for i in range(25):
            assert _post(client, teacher, space, body=f"post {i}").status_code == 201
        first = _stream(client, student, space).json()
        assert len(first["items"]) == 20
        assert first["next_cursor"]
        second = _stream(client, student, space, first["next_cursor"]).json()
        assert len(second["items"]) == 5
        assert second["next_cursor"] is None
        ids = [i["id"] for i in first["items"] + second["items"]]
        assert len(set(ids)) == 25

    def test_a_malformed_cursor_is_a_400(self, client, space, student):
        resp = _stream(client, student, space, "%%%not-a-cursor")
        assert resp.status_code == 400
        assert "cursor" in resp.json()["error"]["details"]["fields"]


class TestEditAndDelete:
    def test_the_author_edits_the_text(self, client, teacher, space):
        post = _post(client, teacher, space).json()
        resp = client.patch(
            f"/api/announcements/{post['id']}", json={"body": "Corrected"}, headers=_auth(teacher)
        )
        assert resp.status_code == 200
        assert resp.json()["body"] == "Corrected"

    def test_a_published_post_cannot_be_moved_back_into_the_future(self, client, teacher, space):
        post = _post(client, teacher, space).json()
        resp = client.patch(
            f"/api/announcements/{post['id']}",
            json={"publish_at": _iso(timedelta(hours=3))},
            headers=_auth(teacher),
        )
        assert resp.status_code == 400
        assert "publish_at" in resp.json()["error"]["details"]["fields"]

    def test_a_scheduled_post_can_be_rescheduled(self, client, teacher, space):
        post = _post(client, teacher, space, publish_at=_iso(timedelta(hours=2))).json()
        resp = client.patch(
            f"/api/announcements/{post['id']}",
            json={"publish_at": _iso(timedelta(days=2))},
            headers=_auth(teacher),
        )
        assert resp.status_code == 200
        assert resp.json()["scheduled"] is True

    def test_delete_removes_it_from_the_stream(self, client, teacher, space, student):
        post = _post(client, teacher, space).json()
        assert (
            client.delete(f"/api/announcements/{post['id']}", headers=_auth(teacher)).status_code
            == 204
        )
        assert _stream(client, student, space).json()["items"] == []

    def test_members_and_other_teachers_get_the_same_refusal_as_a_missing_post(
        self, client, db, teacher, space, student
    ):
        post = _post(client, teacher, space).json()
        url = f"/api/announcements/{post['id']}"
        intruder = _user(db, role="teacher")
        as_member = client.delete(url, headers=_auth(student))
        as_intruder = client.patch(url, json={"body": "x"}, headers=_auth(intruder))
        missing = client.delete(f"/api/announcements/{uuid4()}", headers=_auth(intruder))
        assert as_member.status_code == 403  # a student cannot reach a Teacher route at all
        assert as_intruder.status_code == missing.status_code == 403
        assert as_intruder.json() == missing.json()
