"""
Classroom Phase 5 — the calendar over HTTP (tdd.md §3.6, prd.md CL-9).

The calendar has no policy of its own; it reads the Phase 3 and 4 tables. So
these tests are about the promise in CL-9 — "it shows only what the viewer may
already see": a student gets deadlines with their own status and never a
scheduled post; a teacher gets deadlines plus their own scheduled posts and
nobody else's; leaving a class or archiving it takes its entries away; and the
range is bounded.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.auth.security import create_access_token
from app.core.db import set_current_user_id


def _user(db, *, role: str) -> str:
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
                "VALUES (:id, 'PCTB', 11, 'pre_medical', 'en', 'en')"
            ),
            {"id": user_id},
        )
    elif role == "teacher":
        db.execute(text("INSERT INTO teacher_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


NOW = datetime.now(UTC)


def _iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


def _space(client, db, teacher) -> dict:
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


def _calendar(client, user, start=timedelta(days=-1), end=timedelta(days=30)):
    return client.get(
        "/api/calendar",
        params={"from": _iso(start), "to": _iso(end)},
        headers=_auth(user),
    )


def _kinds(resp) -> list[tuple[str, str]]:
    assert resp.status_code == 200, resp.text
    return sorted((i["kind"], i["title"]) for i in resp.json()["items"])


@pytest.fixture
def teacher(db) -> str:
    return _user(db, role="teacher")


@pytest.fixture
def space(client, db, teacher) -> dict:
    return _space(client, db, teacher)


@pytest.fixture
def student(client, db, space) -> str:
    s = _user(db, role="student")
    resp = client.post("/api/spaces/join", json={"code": space["join_code"]}, headers=_auth(s))
    assert resp.status_code == 200
    return s


@pytest.fixture
def posted(client, teacher, space) -> None:
    """One live assignment due in 3 days, one scheduled assignment, one scheduled announcement."""
    base = f"/api/spaces/{space['id']}"
    for body in (
        {"title": "Lab 1", "due_at": _iso(timedelta(days=3))},
        {
            "title": "Lab 2",
            "publish_at": _iso(timedelta(days=2)),
            "due_at": _iso(timedelta(days=5)),
        },
    ):
        assert (
            client.post(f"{base}/assignments", json=body, headers=_auth(teacher)).status_code == 201
        )
    announcement = {"body": "Test on\n  Monday", "publish_at": _iso(timedelta(days=1))}
    assert (
        client.post(f"{base}/announcements", json=announcement, headers=_auth(teacher)).status_code
        == 201
    )


class TestWhatEachViewerSees:
    def test_a_student_sees_deadlines_with_their_status_and_no_scheduled_post(
        self, client, student, posted
    ):
        resp = _calendar(client, student)
        assert _kinds(resp) == [("due", "Lab 1")]
        [item] = resp.json()["items"]
        assert (item["my_status"], item["space_title"]) == ("assigned", "Physics 11-A")

    def test_the_teacher_sees_deadlines_and_their_own_scheduled_posts(
        self, client, teacher, student, posted
    ):
        resp = _calendar(client, teacher)
        assert _kinds(resp) == [
            ("due", "Lab 1"),
            ("due", "Lab 2"),
            ("scheduled_announcement", "Test on Monday"),  # whitespace collapsed
            ("scheduled_assignment", "Lab 2"),
        ]
        assert all(i["my_status"] is None for i in resp.json()["items"])

    def test_another_teacher_sees_nothing_of_it(self, client, db, posted):
        stranger = _user(db, role="teacher")
        assert _kinds(_calendar(client, stranger)) == []

    def test_entries_are_in_time_order(self, client, teacher, posted):
        times = [i["at"] for i in _calendar(client, teacher).json()["items"]]
        assert times == sorted(times)

    def test_a_turned_in_assignment_shows_as_turned_in(self, client, student, space, posted):
        [item] = _calendar(client, student).json()["items"]
        url = f"/api/assignments/{item['ref_id']}/submission/turn-in"
        assert client.post(url, headers=_auth(student)).status_code == 200
        [after] = _calendar(client, student).json()["items"]
        assert after["my_status"] == "turned_in"


class TestEntriesGoAway:
    def test_leaving_a_class_removes_its_deadlines(self, client, student, space, posted):
        url = f"/api/spaces/{space['id']}/membership"
        assert client.delete(url, headers=_auth(student)).status_code == 204
        assert _kinds(_calendar(client, student)) == []

    def test_an_archived_classroom_is_left_out(self, client, teacher, student, space, posted):
        resp = client.patch(
            f"/api/spaces/{space['id']}", json={"status": "archived"}, headers=_auth(teacher)
        )
        assert resp.status_code == 200
        assert _kinds(_calendar(client, teacher)) == []
        assert _kinds(_calendar(client, student)) == []

    def test_the_range_is_half_open(self, client, teacher, student, posted):
        # Lab 1 is due 3 days out: a window ending before it misses it.
        assert _kinds(_calendar(client, student, end=timedelta(days=2))) == []


class TestTheRangeIsBounded:
    @pytest.mark.parametrize(
        ("start", "end"),
        [(timedelta(0), timedelta(days=63)), (timedelta(days=2), timedelta(days=1))],
        ids=["63 days", "to before from"],
    )
    def test_an_unusable_range_is_a_400(self, client, teacher, start, end):
        resp = _calendar(client, teacher, start, end)
        assert resp.status_code == 400
        assert "to" in resp.json()["error"]["details"]["fields"]

    def test_a_range_without_a_time_zone_is_a_400(self, client, teacher):
        resp = client.get(
            "/api/calendar",
            params={"from": "2026-10-01T00:00:00", "to": "2026-10-31T00:00:00"},
            headers=_auth(teacher),
        )
        assert resp.status_code == 400

    def test_exactly_62_days_is_allowed(self, client, teacher):
        assert _calendar(client, teacher, timedelta(0), timedelta(days=62)).status_code == 200
