"""
Classroom Phase 8 — the parent's read-only overview, over HTTP (tdd.md §3.6,
prd.md CL-10).

`test_classroom_rls.py` (`TestParentOverview`) proves the database returns only
what CL-10 allows; this proves the route exposes the contract: each verified
child, their classrooms and teachers, each assignment's deadline and DERIVED
status, and a grade once it is returned — and that nothing private travels,
however much private material exists (the student's answer, their link, the
teacher's feedback, the class chat).
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.auth.security import create_access_token
from app.core.db import set_current_user_id


def _user(db, *, role: str, name: str | None = None) -> str:
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
            "name": name or role,
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
    elif role == "parent":
        db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def teacher(db) -> str:
    return _user(db, role="teacher", name="Sir Ahmed")


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
    s = _user(db, role="student", name="Ayesha Khan")
    resp = client.post("/api/spaces/join", json={"code": space["join_code"]}, headers=_auth(s))
    assert resp.status_code == 200
    return s


@pytest.fixture
def parent(db, make_link, student) -> str:
    p = _user(db, role="parent")
    make_link(parent_id=p, student_id=student, status="verified")
    return p


@pytest.fixture
def lab(client, teacher, space) -> str:
    resp = client.post(
        f"/api/spaces/{space['id']}/assignments",
        json={"title": "Lab 1", "points": 10},
        headers=_auth(teacher),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _overview(client, user) -> dict:
    resp = client.get("/api/parent/classrooms", headers=_auth(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestParentOverview:
    def test_a_parent_sees_each_child_their_classroom_and_its_deadlines(
        self, client, parent, student, space, lab
    ):
        [child] = _overview(client, parent)["children"]
        assert (child["student_id"], child["full_name"]) == (student, "Ayesha Khan")
        [room] = child["classrooms"]
        assert (room["space_id"], room["title"], room["status"]) == (
            space["id"],
            "Physics 11-A",
            "active",
        )
        assert (room["subject_name"], room["teacher_name"]) == ("Physics", "Sir Ahmed")
        [work] = room["assignments"]
        assert (work["id"], work["title"], work["points"]) == (lab, "Lab 1", 10)
        assert (work["status"], work["grade"], work["due_at"]) == ("assigned", None, None)

    def test_a_returned_grade_shows_and_nothing_private_travels(
        self, client, teacher, parent, student, space, lab
    ):
        def put(path, body):
            return client.put(path, json=body, headers=_auth(student))

        assert (
            put(f"/api/assignments/{lab}/submission", {"body": "MY OWN ANSWER"}).status_code == 200
        )
        client.post(
            f"/api/assignments/{lab}/submission/links",
            json={"url": "https://docs.example.com/my-work"},
            headers=_auth(student),
        )
        client.post(f"/api/assignments/{lab}/submission/turn-in", headers=_auth(student))
        client.post(
            f"/api/spaces/{space['id']}/messages",
            json={"body": "A LINE IN THE CHAT"},
            headers=_auth(student),
        )
        graded = client.put(
            f"/api/assignments/{lab}/grades/{student}",
            json={"grade": 8.5, "feedback": "A PRIVATE NOTE", "return_to_student": True},
            headers=_auth(teacher),
        )
        assert graded.status_code == 200

        resp = client.get("/api/parent/classrooms", headers=_auth(parent))
        work = resp.json()["children"][0]["classrooms"][0]["assignments"][0]
        assert (work["status"], work["grade"]) == ("graded", 8.5)
        for private in (
            "MY OWN ANSWER",
            "docs.example.com",
            "A PRIVATE NOTE",
            "A LINE IN THE CHAT",
            "feedback",
            "turned_in_at",
        ):
            assert private not in resp.text, private

    def test_a_grade_not_yet_returned_stays_hidden(self, client, teacher, parent, student, lab):
        client.post(f"/api/assignments/{lab}/submission/turn-in", headers=_auth(student))
        client.put(
            f"/api/assignments/{lab}/grades/{student}",
            json={"grade": 4, "return_to_student": False},
            headers=_auth(teacher),
        )
        work = _overview(client, parent)["children"][0]["classrooms"][0]["assignments"][0]
        assert (work["status"], work["grade"]) == ("turned_in", None)

    def test_an_overdue_assignment_is_missing(self, client, db, teacher, parent, space):
        # Arranged in SQL: the API refuses a due date before publishing, and now() is frozen.
        set_current_user_id(db, UUID(teacher))
        db.execute(
            text(
                "INSERT INTO assignment "
                "  (space_id, subject_id, author_id, title, publish_at, due_at) "
                "SELECT s.id, s.subject_id, :a, 'Overdue', now() - interval '2 days', "
                "       now() - interval '1 day' FROM classroom_space s WHERE s.id = :s"
            ),
            {"s": space["id"], "a": teacher},
        )
        [work] = _overview(client, parent)["children"][0]["classrooms"][0]["assignments"]
        assert (work["title"], work["status"]) == ("Overdue", "missing")

    def test_a_child_in_no_classroom_is_still_listed(self, client, db, make_link):
        child = _user(db, role="student", name="Bilal")
        p = _user(db, role="parent")
        make_link(parent_id=p, student_id=child, status="verified")
        assert _overview(client, p) == {
            "children": [{"student_id": child, "full_name": "Bilal", "classrooms": []}]
        }

    def test_a_parent_with_no_verified_child_gets_an_empty_list(
        self, client, db, make_link, student
    ):
        pending = _user(db, role="parent")
        make_link(parent_id=pending, student_id=student, status="pending")
        assert _overview(client, pending) == {"children": []}

    def test_only_a_parent_may_ask(self, client, teacher, student):
        for user in (teacher, student):
            resp = client.get("/api/parent/classrooms", headers=_auth(user))
            assert resp.status_code == 403
            assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"
