"""
Classroom Phase 4 — assignments, submissions and grades over HTTP.

`test_classroom_rls.py` proves the database refuses; this proves the routes
expose exactly the contract (tdd.md §3.6, prd.md CL-7): status is derived and
never stored, a draft stays private until it is turned in, a grade stays private
until it is returned, graded work is locked, and every refusal is a catalogued
code — a state carries `details.reason`, a bad field `details.fields`.

⚠️ `now()` IS FROZEN FOR THE WHOLE TEST (one transaction). Overdue work is
   therefore arranged directly in SQL — published two days ago, due yesterday —
   rather than by waiting; `turned_in_at` uses clock_timestamp(), so a turn-in
   after that deadline is genuinely late.
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
        {
            "id": user_id,
            "email": f"{role}-{user_id}@example.com",
            "role": role,
            "name": f"{role} {user_id.hex[:6]}",
        },
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


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


def _error(resp) -> dict:
    return resp.json()["error"]


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


def _join(client, db, space) -> str:
    student = _user(db, role="student")
    resp = client.post(
        "/api/spaces/join", json={"code": space["join_code"]}, headers=_auth(student)
    )
    assert resp.status_code == 200
    return student


@pytest.fixture
def student(client, db, space) -> str:
    return _join(client, db, space)


def _create(client, teacher, space, **body):
    return client.post(
        f"/api/spaces/{space['id']}/assignments",
        json={"title": "Lab 1", "points": 10, **body},
        headers=_auth(teacher),
    )


@pytest.fixture
def lab(client, teacher, space) -> dict:
    resp = _create(client, teacher, space, due_at=_iso(timedelta(days=7)))
    assert resp.status_code == 201
    return resp.json()


def _overdue(db, teacher, space) -> str:
    """Published two days ago, due yesterday — arranged in SQL because now() is frozen."""
    set_current_user_id(db, UUID(teacher))
    return str(
        db.execute(
            text(
                "INSERT INTO assignment "
                "(space_id, subject_id, author_id, title, points, publish_at, due_at) "
                "SELECT id, subject_id, :t, 'Overdue', 10, "
                "       now() - interval '2 days', now() - interval '1 day' "
                "  FROM classroom_space WHERE id = :s RETURNING id"
            ),
            {"t": teacher, "s": space["id"]},
        ).scalar_one()
    )


def _get(client, user, assignment_id):
    return client.get(f"/api/assignments/{assignment_id}", headers=_auth(user))


def _list(client, user, space):
    return client.get(f"/api/spaces/{space['id']}/assignments", headers=_auth(user))


def _submit(client, user, assignment_id, action, **body):
    base = f"/api/assignments/{assignment_id}/submission"
    if action == "save":
        return client.put(base, json=body, headers=_auth(user))
    return client.post(f"{base}/{action}", headers=_auth(user))


def _grade(client, teacher, assignment_id, student, **body):
    return client.put(
        f"/api/assignments/{assignment_id}/grades/{student}", json=body, headers=_auth(teacher)
    )


class TestCreateAndRead:
    def test_owner_creates_and_a_member_sees_their_own_view(self, client, teacher, space, student):
        created = _create(
            client, teacher, space, title="  Lab 1  ", instructions=" Measure g. ", points=20
        )
        assert created.status_code == 201
        body = created.json()
        assert (body["title"], body["instructions"], body["points"]) == ("Lab 1", "Measure g.", 20)
        assert body["my_submission"] is None  # owner view

        [owned] = _list(client, teacher, space).json()["items"]
        assert (owned["turned_in_count"], owned["my_status"]) == (0, None)
        [mine] = _list(client, student, space).json()["items"]
        assert (mine["my_status"], mine["turned_in_count"], mine["my_grade"]) == (
            "assigned",
            None,
            None,
        )
        assert _get(client, student, body["id"]).json()["my_submission"]["body"] == ""

    def test_a_scheduled_assignment_is_hidden_from_members(self, client, teacher, space, student):
        later = _create(client, teacher, space, publish_at=_iso(timedelta(hours=2))).json()
        assert later["scheduled"] is True
        assert _list(client, student, space).json()["items"] == []
        assert _get(client, student, later["id"]).status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            {"due_at": _iso(timedelta(hours=-1))},
            {"publish_at": _iso(timedelta(days=2)), "due_at": _iso(timedelta(days=1))},
        ],
        ids=["due in the past", "due before it is posted"],
    )
    def test_the_due_date_must_follow_posting(self, client, teacher, space, body):
        resp = _create(client, teacher, space, **body)
        assert resp.status_code == 400
        assert "due_at" in _error(resp)["details"]["fields"]

    def test_a_member_cannot_create(self, client, space, student):
        assert _create(client, student, space).status_code == 403

    def test_unknown_and_foreign_assignments_are_indistinguishable(self, client, db, lab):
        stranger = _user(db, role="teacher")
        foreign = _get(client, stranger, lab["id"])
        unknown = _get(client, stranger, uuid4())
        assert foreign.status_code == unknown.status_code == 403
        assert foreign.json() == unknown.json()


class TestStudentWork:
    def test_draft_turn_in_and_unsubmit(self, client, student, lab):
        link = "https://example.com/my-lab"
        saved = _submit(client, student, lab["id"], "save", body="My answer", link_url=link)
        assert saved.status_code == 200
        assert (saved.json()["status"], saved.json()["link_url"]) == ("assigned", link)

        turned = _submit(client, student, lab["id"], "turn-in")
        assert turned.json()["status"] == "turned_in"
        assert _submit(client, student, lab["id"], "turn-in").status_code == 200  # a repeat is fine

        edit = _submit(client, student, lab["id"], "save", body="changed")
        assert edit.status_code == 400
        assert _error(edit)["details"]["reason"] == "turned_in"

        back = _submit(client, student, lab["id"], "unsubmit")
        assert (back.status_code, back.json()["status"], back.json()["body"]) == (
            200,
            "assigned",
            "My answer",
        )

    def test_only_an_https_link_is_accepted(self, client, student, lab):
        resp = _submit(client, student, lab["id"], "save", link_url="javascript:alert(1)")
        assert resp.status_code == 400
        assert "link_url" in _error(resp)["details"]["fields"]

    def test_missing_and_late_are_derived(self, client, db, teacher, space, student):
        overdue = _overdue(db, teacher, space)
        assert _get(client, student, overdue).json()["my_status"] == "missing"
        turned = _submit(client, student, overdue, "turn-in")
        assert turned.json()["status"] == "turned_in_late"

    def test_a_teacher_cannot_submit(self, client, teacher, lab):
        assert _submit(client, teacher, lab["id"], "turn-in").status_code == 403


class TestGrading:
    def test_the_table_lists_every_member_and_keeps_drafts_private(
        self, client, db, teacher, space, lab
    ):
        drafting = _join(client, db, space)
        finished = _join(client, db, space)
        _submit(client, drafting, lab["id"], "save", body="half done")
        _submit(client, finished, lab["id"], "save", body="all done")
        _submit(client, finished, lab["id"], "turn-in")

        table = client.get(f"/api/assignments/{lab['id']}/submissions", headers=_auth(teacher))
        statuses = {r["student_id"]: r["status"] for r in table.json()["rows"]}
        assert statuses == {drafting: "assigned", finished: "turned_in"}

        def work(student):
            url = f"/api/assignments/{lab['id']}/submissions/{student}"
            return client.get(url, headers=_auth(teacher)).json()

        assert work(drafting)["body"] is None  # a draft is the student's own
        assert work(finished)["body"] == "all done"

    def test_a_grade_is_private_until_returned_and_locks_the_work(
        self, client, teacher, student, lab
    ):
        _submit(client, student, lab["id"], "turn-in")
        saved = _grade(client, teacher, lab["id"], student, grade=8.5, feedback="Show units.")
        assert saved.status_code == 200
        assert (saved.json()["grade"], saved.json()["graded"], saved.json()["status"]) == (
            8.5,
            True,
            "turned_in",
        )

        hidden = _get(client, student, lab["id"]).json()["my_submission"]
        assert (hidden["grade"], hidden["feedback"], hidden["status"]) == (None, None, "turned_in")
        locked = _submit(client, student, lab["id"], "unsubmit")
        assert (locked.status_code, _error(locked)["details"]["reason"]) == (400, "graded")

        returned = _grade(
            client,
            teacher,
            lab["id"],
            student,
            grade=8.5,
            feedback="Show units.",
            return_to_student=True,
        )
        assert returned.json()["status"] == "graded"
        mine = _get(client, student, lab["id"]).json()
        assert (mine["my_grade"], mine["my_submission"]["feedback"]) == (8.5, "Show units.")
        assert mine["my_status"] == "graded"

    def test_returning_a_grade_is_audited(self, client, db, service_conn, teacher, student, lab):
        _grade(client, teacher, lab["id"], student, grade=7, return_to_student=True)
        admin = service_conn.execute(
            text("SELECT id FROM app_user WHERE role = 'admin' AND status = 'active' LIMIT 1")
        ).scalar_one_or_none()
        if admin is None:
            pytest.skip("needs an owner-provisioned administrator to read audit_log")
        set_current_user_id(db, admin)
        target = f"assignment/{lab['id']}/student/{student}"
        rows = db.execute(
            text("SELECT actor_id FROM audit_log WHERE action = :a AND target = :t"),
            {"a": "classroom.grade_returned", "t": target},
        ).all()
        assert [str(r[0]) for r in rows] == [teacher]

    def test_a_grade_above_the_points_is_refused(self, client, teacher, student, lab):
        resp = _grade(client, teacher, lab["id"], student, grade=10.5)
        assert resp.status_code == 400
        assert "grade" in _error(resp)["details"]["fields"]

    def test_points_cannot_drop_below_a_grade(self, client, teacher, student, lab):
        _grade(client, teacher, lab["id"], student, grade=9)
        resp = client.patch(
            f"/api/assignments/{lab['id']}", json={"points": 5}, headers=_auth(teacher)
        )
        assert resp.status_code == 400
        assert "points" in _error(resp)["details"]["fields"]

    def test_only_active_members_can_be_graded(self, client, db, teacher, lab):
        outsider = _user(db, role="student")
        assert _grade(client, teacher, lab["id"], outsider, grade=5).status_code == 403


class TestEditAndDelete:
    def test_a_due_date_can_be_cleared_but_a_title_cannot(self, client, teacher, lab):
        url = f"/api/assignments/{lab['id']}"
        cleared = client.patch(url, json={"due_at": None}, headers=_auth(teacher))
        assert (cleared.status_code, cleared.json()["due_at"]) == (200, None)
        blank = client.patch(url, json={"title": None}, headers=_auth(teacher))
        assert blank.status_code == 400

    def test_only_a_scheduled_assignment_can_be_rescheduled(self, client, teacher, lab):
        resp = client.patch(
            f"/api/assignments/{lab['id']}",
            json={"publish_at": _iso(timedelta(days=1))},
            headers=_auth(teacher),
        )
        assert resp.status_code == 400
        assert "publish_at" in _error(resp)["details"]["fields"]

    def test_delete_removes_it(self, client, teacher, student, lab):
        url = f"/api/assignments/{lab['id']}"
        assert client.delete(url, headers=_auth(student)).status_code == 403
        assert client.delete(url, headers=_auth(teacher)).status_code == 204
        assert _get(client, teacher, lab["id"]).status_code == 403


class TestChapters:
    def test_only_teachers_use_the_chapter_picker(self, client, teacher, space, student):
        url = f"/api/reference/subjects/{space['subject']['id']}/chapters"
        assert client.get(url, headers=_auth(teacher)).status_code == 200
        assert client.get(url, headers=_auth(student)).status_code == 403

    def test_a_chapter_from_another_subject_is_refused(
        self, client, db, service_conn, teacher, space
    ):
        admin = service_conn.execute(
            text("SELECT id FROM app_user WHERE role = 'admin' AND status = 'active' LIMIT 1")
        ).scalar_one_or_none()
        if admin is None:
            pytest.skip("needs an owner-provisioned administrator to create chapters")
        set_current_user_id(db, admin)
        chapters = {}
        for name in ("Physics", "Chemistry"):
            chapters[name] = str(
                db.execute(
                    text(
                        "INSERT INTO chapter (subject_id, number, title) "
                        "SELECT s.id, 901, 'Test chapter' FROM subject s "
                        "  JOIN class_level cl ON cl.id = s.class_level_id "
                        "  JOIN board b ON b.id = cl.board_id "
                        " WHERE b.code = 'PCTB' AND cl.level = 11 AND s.name = :n "
                        "RETURNING id"
                    ),
                    {"n": name},
                ).scalar_one()
            )

        foreign = _create(client, teacher, space, chapter_id=chapters["Chemistry"])
        assert foreign.status_code == 400
        assert "chapter_id" in _error(foreign)["details"]["fields"]
        own = _create(client, teacher, space, chapter_id=chapters["Physics"])
        assert own.status_code == 201
        assert own.json()["chapter"]["number"] == 901
