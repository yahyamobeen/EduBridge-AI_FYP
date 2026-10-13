"""
Classroom Phase 6b — links on a piece of work, over HTTP (tdd.md §3.6, prd.md
CL-7 as amended 2026-10-05).

`test_classroom_rls.py` (`TestLinkBoundary`) proves the database refuses; this
proves the routes expose the contract: a student adds up to five https links
one at a time, beside their files; they are theirs alone until the work is
turned in; and every refusal is a catalogued code — a state carries
`details.reason`, a bad link `details.fields.url`.
"""

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
    s = _user(db, role="student")
    resp = client.post("/api/spaces/join", json={"code": space["join_code"]}, headers=_auth(s))
    assert resp.status_code == 200
    return s


@pytest.fixture
def student(client, db, space) -> str:
    return _join(client, db, space)


@pytest.fixture
def lab(client, teacher, space) -> str:
    resp = client.post(
        f"/api/spaces/{space['id']}/assignments",
        json={"title": "Lab 1", "points": 10},
        headers=_auth(teacher),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _add(client, user, lab, url="https://docs.example.com/my-lab"):
    return client.post(
        f"/api/assignments/{lab}/submission/links", json={"url": url}, headers=_auth(user)
    )


def _mine(client, student, lab) -> dict:
    resp = client.get(f"/api/assignments/{lab}", headers=_auth(student))
    assert resp.status_code == 200
    return resp.json()["my_submission"]


def _turn_in(client, student, lab) -> None:
    url = f"/api/assignments/{lab}/submission/turn-in"
    assert client.post(url, headers=_auth(student)).status_code == 200


class TestLinks:
    def test_add_list_and_remove_your_own(self, client, student, lab):
        first = _add(client, student, lab)
        assert first.status_code == 201, first.text
        assert first.json()["url"] == "https://docs.example.com/my-lab"
        second = _add(client, student, lab, "https://slides.example.com/deck")
        assert second.status_code == 201
        assert [link["url"] for link in _mine(client, student, lab)["links"]] == [
            "https://docs.example.com/my-lab",
            "https://slides.example.com/deck",
        ]

        gone = client.delete(f"/api/submission-links/{first.json()['id']}", headers=_auth(student))
        assert gone.status_code == 204
        assert [link["url"] for link in _mine(client, student, lab)["links"]] == [
            "https://slides.example.com/deck"
        ]

    def test_the_same_link_twice_is_still_one_link(self, client, student, lab):
        a = _add(client, student, lab).json()
        b = _add(client, student, lab).json()
        assert a["id"] == b["id"]
        assert len(_mine(client, student, lab)["links"]) == 1

    @pytest.mark.parametrize(
        "bad", ["javascript:alert(1)", "http://example.com", "example.com", "https://"]
    )
    def test_only_an_https_link_is_accepted(self, client, student, lab, bad):
        resp = _add(client, student, lab, bad)
        assert resp.status_code == 400
        assert "url" in resp.json()["error"]["details"]["fields"]

    def test_the_sixth_link_is_refused(self, client, student, lab):
        for n in range(5):
            assert _add(client, student, lab, f"https://example.com/{n}").status_code == 201
        resp = _add(client, student, lab, "https://example.com/5")
        assert resp.status_code == 400
        assert resp.json()["error"]["details"]["reason"] == "too_many_links"

    def test_turned_in_work_takes_no_link_and_keeps_its_own(self, client, student, lab):
        link = _add(client, student, lab).json()
        _turn_in(client, student, lab)
        refused = _add(client, student, lab, "https://example.com/late")
        assert refused.json()["error"]["details"]["reason"] == "turned_in"
        kept = client.delete(f"/api/submission-links/{link['id']}", headers=_auth(student))
        assert kept.status_code == 400
        assert kept.json()["error"]["details"]["reason"] == "turned_in"

    def test_the_teacher_sees_the_links_only_once_turned_in(self, client, teacher, student, lab):
        _add(client, student, lab)
        url = f"/api/assignments/{lab}/submissions/{student}"
        assert client.get(url, headers=_auth(teacher)).json()["links"] == []
        _turn_in(client, student, lab)
        work = client.get(url, headers=_auth(teacher)).json()
        assert [link["url"] for link in work["links"]] == ["https://docs.example.com/my-lab"]

    def test_a_classmate_cannot_remove_it_and_learns_nothing(self, client, db, space, student, lab):
        link = _add(client, student, lab).json()
        classmate = _join(client, db, space)
        theirs = client.delete(f"/api/submission-links/{link['id']}", headers=_auth(classmate))
        unknown = client.delete(f"/api/submission-links/{uuid4()}", headers=_auth(classmate))
        assert theirs.status_code == unknown.status_code == 403
        assert theirs.json() == unknown.json()

    def test_a_teacher_and_an_outsider_cannot_add_one(self, client, db, teacher, lab):
        assert _add(client, teacher, lab).status_code == 403
        assert _add(client, _user(db, role="student"), lab).status_code == 403

    def test_a_draft_no_longer_carries_a_link(self, client, student, lab):
        resp = client.put(
            f"/api/assignments/{lab}/submission",
            json={"body": "My answer", "link_url": "https://example.com/ignored"},
            headers=_auth(student),
        )
        assert resp.status_code == 200
        assert (resp.json()["body"], resp.json()["links"]) == ("My answer", [])
        assert "link_url" not in resp.json()
