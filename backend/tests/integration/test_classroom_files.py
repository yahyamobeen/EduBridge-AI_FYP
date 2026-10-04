"""
Classroom Phase 6 — files over HTTP (tdd.md §3.6, prd.md CL-8).

`test_classroom_rls.py` proves the database refuses; this proves the routes
and the bucket stay in step with it. The `object_store` fixture
(tests/integration/conftest.py) is a fresh in-memory store per test, so every
test can assert not only the response but what is — and is no longer — stored:

  * a refused upload leaves no object behind;
  * a removed file's object goes once the removal commits, and not before;
  * a rolled-back upload leaves no object behind;
  * a draft's files stay the student's until the work is turned in;
  * a download is always an attachment, in a sandbox.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.auth.security import create_access_token
from app.classroom import file_service, storage
from app.core.config import get_settings
from app.core.db import set_current_user_id

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


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


def _upload(client, user, url, data=PDF, name="Lab report.PDF"):
    headers = {**_auth(user), "Content-Type": "application/pdf"}
    if name is not None:
        headers["X-Upload-Filename"] = name
    return client.post(url, content=data, headers=headers)


def _reason(resp) -> str:
    return resp.json()["error"]["details"]["reason"]


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


def _files_url(lab: str) -> str:
    return f"/api/assignments/{lab}/submission/files"


def _turn_in(client, student, lab) -> None:
    url = f"/api/assignments/{lab}/submission/turn-in"
    assert client.post(url, headers=_auth(student)).status_code == 200


def _drain() -> None:
    storage.drain_storage_cleanup()


class TestSubmissionFiles:
    def test_upload_then_download_your_own(self, client, student, lab, object_store):
        resp = _upload(client, student, _files_url(lab))
        assert resp.status_code == 201, resp.text
        meta = resp.json()
        assert (meta["filename"], meta["content_type"], meta["size_bytes"]) == (
            "Lab report.pdf",
            "application/pdf",
            len(PDF),
        )
        [key] = object_store.objects
        assert key.startswith("u/")

        mine = client.get(f"/api/assignments/{lab}", headers=_auth(student)).json()
        assert [f["id"] for f in mine["my_submission"]["files"]] == [meta["id"]]

        got = client.get(f"/api/submission-files/{meta['id']}/content", headers=_auth(student))
        assert got.status_code == 200
        assert got.content == PDF
        assert got.headers["content-disposition"].startswith("attachment; ")
        assert "sandbox" in got.headers["content-security-policy"]
        assert got.headers["x-content-type-options"] == "nosniff"

    def test_the_teacher_sees_it_only_once_turned_in(self, client, teacher, student, lab):
        file_id = _upload(client, student, _files_url(lab)).json()["id"]
        work_url = f"/api/assignments/{lab}/submissions/{student}"
        content_url = f"/api/submission-files/{file_id}/content"

        assert client.get(work_url, headers=_auth(teacher)).json()["files"] == []
        assert client.get(content_url, headers=_auth(teacher)).status_code == 403

        _turn_in(client, student, lab)
        assert len(client.get(work_url, headers=_auth(teacher)).json()["files"]) == 1
        assert client.get(content_url, headers=_auth(teacher)).content == PDF

    def test_a_classmate_gets_the_same_refusal_as_a_missing_file(
        self, client, db, space, student, lab
    ):
        file_id = _upload(client, student, _files_url(lab)).json()["id"]
        _turn_in(client, student, lab)
        classmate = _join(client, db, space)
        theirs = client.get(f"/api/submission-files/{file_id}/content", headers=_auth(classmate))
        missing = client.get(f"/api/submission-files/{uuid4()}/content", headers=_auth(classmate))
        assert theirs.status_code == missing.status_code == 403
        assert theirs.json() == missing.json()

    def test_a_file_of_the_wrong_kind_is_refused_and_nothing_is_stored(
        self, client, student, lab, object_store
    ):
        resp = _upload(client, student, _files_url(lab), data=b"MZ\x90\x00 an executable")
        assert (resp.status_code, _reason(resp)) == (400, "unsupported_type")
        assert object_store.objects == {}

    def test_an_upload_without_a_name_is_a_400(self, client, student, lab, object_store):
        assert _upload(client, student, _files_url(lab), name=None).status_code == 400
        assert object_store.objects == {}

    def test_a_file_over_the_limit_is_refused_before_storing(
        self, client, monkeypatch, student, lab, object_store
    ):
        monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
        resp = _upload(client, student, _files_url(lab))
        assert (resp.status_code, _reason(resp)) == (400, "too_large")
        assert object_store.objects == {}

    def test_turned_in_work_takes_no_new_file_and_keeps_no_object(
        self, client, student, lab, object_store
    ):
        _turn_in(client, student, lab)
        resp = _upload(client, student, _files_url(lab))
        assert (resp.status_code, _reason(resp)) == (400, "turned_in")
        assert object_store.objects == {}  # stored, refused, deleted at once

    def test_an_outsider_cannot_upload(self, client, db, lab, object_store):
        outsider = _user(db, role="student")
        assert _upload(client, outsider, _files_url(lab)).status_code == 403
        assert object_store.objects == {}

    def test_removing_a_file_removes_its_object_once_committed(
        self, client, student, lab, object_store
    ):
        file_id = _upload(client, student, _files_url(lab)).json()["id"]
        resp = client.delete(f"/api/submission-files/{file_id}", headers=_auth(student))
        assert resp.status_code == 204
        _drain()
        assert object_store.objects == {}

    def test_turned_in_files_cannot_be_removed(self, client, student, lab, object_store):
        file_id = _upload(client, student, _files_url(lab)).json()["id"]
        _turn_in(client, student, lab)
        resp = client.delete(f"/api/submission-files/{file_id}", headers=_auth(student))
        assert (resp.status_code, _reason(resp)) == (400, "turned_in")
        _drain()
        assert len(object_store.objects) == 1


class TestTeacherAttachments:
    def test_an_assignment_attachment_reaches_members(self, client, teacher, student, lab):
        resp = _upload(client, teacher, f"/api/assignments/{lab}/attachments", name="Sheet.pdf")
        assert resp.status_code == 201
        file_id = resp.json()["id"]
        seen = client.get(f"/api/assignments/{lab}", headers=_auth(student)).json()
        assert [a["filename"] for a in seen["attachments"]] == ["Sheet.pdf"]
        got = client.get(f"/api/attachments/{file_id}/content", headers=_auth(student))
        assert got.content == PDF

    def test_a_scheduled_assignments_attachment_stays_hidden(self, client, teacher, space, student):
        later = client.post(
            f"/api/spaces/{space['id']}/assignments",
            json={
                "title": "Later",
                "publish_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            },
            headers=_auth(teacher),
        ).json()["id"]
        file_id = _upload(client, teacher, f"/api/assignments/{later}/attachments").json()["id"]
        resp = client.get(f"/api/attachments/{file_id}/content", headers=_auth(student))
        assert resp.status_code == 403

    def test_an_announcement_attachment_rides_with_its_post_and_goes_with_it(
        self, client, teacher, space, student, object_store
    ):
        post = client.post(
            f"/api/spaces/{space['id']}/announcements",
            json={"body": "Worksheet attached"},
            headers=_auth(teacher),
        ).json()
        assert (
            _upload(client, teacher, f"/api/announcements/{post['id']}/attachments").status_code
            == 201
        )
        stream = client.get(
            f"/api/spaces/{space['id']}/announcements", headers=_auth(student)
        ).json()
        assert len(stream["items"][0]["attachments"]) == 1

        url = f"/api/announcements/{post['id']}"
        assert client.delete(url, headers=_auth(teacher)).status_code == 204
        _drain()
        assert object_store.objects == {}

    def test_another_teacher_cannot_attach(self, client, db, lab, object_store):
        stranger = _user(db, role="teacher")
        resp = _upload(client, stranger, f"/api/assignments/{lab}/attachments")
        assert resp.status_code == 403
        assert object_store.objects == {}

    def test_a_member_cannot_remove_an_attachment(self, client, teacher, student, lab):
        file_id = _upload(client, teacher, f"/api/assignments/{lab}/attachments").json()["id"]
        assert (
            client.delete(f"/api/attachments/{file_id}", headers=_auth(student)).status_code == 403
        )
        assert (
            client.delete(f"/api/attachments/{file_id}", headers=_auth(teacher)).status_code == 204
        )

    def test_deleting_an_assignment_removes_every_object(
        self, client, teacher, student, lab, object_store
    ):
        _upload(client, teacher, f"/api/assignments/{lab}/attachments")
        _upload(client, student, _files_url(lab))  # a draft the teacher cannot see
        assert len(object_store.objects) == 2
        assert client.delete(f"/api/assignments/{lab}", headers=_auth(teacher)).status_code == 204
        _drain()
        assert object_store.objects == {}


class TestRollback:
    def test_a_rolled_back_upload_leaves_no_object(
        self, db, client, space, student, lab, object_store
    ):
        set_current_user_id(db, UUID(student))
        file_service.store_submission_file(
            db, UUID(student), UUID(lab), UUID(space["id"]), PDF, "lab.pdf"
        )
        assert len(object_store.objects) == 1
        db.rollback()
        _drain()
        assert object_store.objects == {}
