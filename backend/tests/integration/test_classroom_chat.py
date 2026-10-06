"""
Classroom Phase 7 — the class chat, over HTTP (tdd.md §3.6, prd.md CL-5).

`test_classroom_rls.py` (`TestChatBoundary`) proves the database refuses; this
proves the routes expose the contract: a poll with a database-clock cursor, an
overlap window and tombstones; a post that is refused with a reason a member
can act on (`details.reason`); moderation by the classroom's teacher only; and
the same byte-identical 403 for an outsider as for a classroom that does not
exist.

⚠️ Each test runs in ONE transaction, so `now()` — the poll's `server_time` —
is frozen at its start and every message is "after" it. These tests assert
what a poll contains, never wall-clock order between polls.
"""

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
        group = "pre_medical" if class_level >= 11 else "science"
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, 'PCTB', :lvl, CAST(:grp AS student_group), 'en', 'en')"
            ),
            {"id": user_id, "lvl": class_level, "grp": group},
        )
    elif role == "teacher":
        db.execute(text("INSERT INTO teacher_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


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
    s = _user(db, role="student")
    resp = client.post("/api/spaces/join", json={"code": space["join_code"]}, headers=_auth(s))
    assert resp.status_code == 200
    return s


@pytest.fixture
def student(client, db, space) -> str:
    return _join(client, db, space)


def _post(client, user, space, body="Is the test on Monday?"):
    return client.post(
        f"/api/spaces/{space['id']}/messages", json={"body": body}, headers=_auth(user)
    )


def _poll(client, user, space, **query) -> dict:
    resp = client.get(f"/api/spaces/{space['id']}/messages", params=query, headers=_auth(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mute(client, teacher, space, student, muted=True):
    return client.put(
        f"/api/spaces/{space['id']}/members/{student}/mute",
        json={"muted": muted},
        headers=_auth(teacher),
    )


def _patch(client, teacher, space, **fields):
    return client.patch(f"/api/spaces/{space['id']}", json=fields, headers=_auth(teacher))


class TestPostingAndPolling:
    def test_a_member_posts_and_the_class_reads_it(self, client, db, teacher, space, student):
        posted = _post(client, student, space)
        assert posted.status_code == 201, posted.text
        message = posted.json()
        assert message["author_id"] == student
        assert (message["body"], message["deleted"]) == ("Is the test on Monday?", False)

        classmate = _join(client, db, space)
        for reader in (classmate, teacher):
            page = _poll(client, reader, space)
            assert [m["id"] for m in page["messages"]] == [message["id"]]
        page = _poll(client, classmate, space)
        assert (page["can_post"], page["chat_locked"], page["muted"]) == (True, False, False)
        assert page["server_time"] and page["deleted_ids"] == [] and page["reset"] is False

    def test_the_body_is_trimmed_and_bounded(self, client, student, space):
        assert _post(client, student, space, "  hello  ").json()["body"] == "hello"
        for bad in ("   ", "x" * 1001):
            resp = _post(client, student, space, bad)
            assert resp.status_code == 400
            assert "body" in _error(resp)["details"]["fields"]

    def test_a_catch_up_poll_brings_new_messages_and_tombstones(
        self, client, teacher, space, student
    ):
        first = _post(client, student, space, "first").json()
        cursor = _poll(client, student, space)["server_time"]
        second = _post(client, student, space, "second").json()
        assert client.delete(
            f"/api/messages/{first['id']}", headers=_auth(teacher)
        ).status_code == (204)

        page = _poll(client, student, space, after=cursor)
        ids = [m["id"] for m in page["messages"]]
        assert second["id"] in ids and first["id"] not in ids  # a member never reads it again
        assert first["id"] in page["deleted_ids"]

    def test_the_teacher_still_reads_a_deleted_message_flagged(
        self, client, teacher, space, student
    ):
        mid = _post(client, student, space, "spam").json()["id"]
        client.delete(f"/api/messages/{mid}", headers=_auth(teacher))
        [kept] = _poll(client, teacher, space)["messages"]
        assert (kept["id"], kept["body"], kept["deleted"]) == (mid, "spam", True)

    def test_older_messages_come_a_page_at_a_time_oldest_first(self, client, db, space, student):
        # Inserted as the student, under the same policy the route uses: 55
        # posts through the route would trip the chat_post limit.
        set_current_user_id(db, UUID(student))
        for n in range(55):
            db.execute(
                text("INSERT INTO space_message (space_id, author_id, body) VALUES (:s, :u, :b)"),
                {"s": space["id"], "u": student, "b": f"m{n:02}"},
            )
        newest = _poll(client, student, space)
        assert [m["body"] for m in newest["messages"]] == [f"m{n:02}" for n in range(5, 55)]
        assert newest["older_cursor"]
        older = _poll(client, student, space, before=newest["older_cursor"])
        assert [m["body"] for m in older["messages"]] == [f"m{n:02}" for n in range(5)]
        assert older["older_cursor"] is None

    def test_a_catch_up_too_far_behind_starts_again_from_the_newest(
        self, client, db, space, student
    ):
        cursor = _poll(client, student, space)["server_time"]
        set_current_user_id(db, UUID(student))
        for n in range(205):
            db.execute(
                text("INSERT INTO space_message (space_id, author_id, body) VALUES (:s, :u, :b)"),
                {"s": space["id"], "u": student, "b": f"m{n:03}"},
            )
        page = _poll(client, student, space, after=cursor)
        assert page["reset"] is True
        assert [m["body"] for m in page["messages"]] == [f"m{n:03}" for n in range(155, 205)]
        assert page["older_cursor"]

    def test_after_and_before_together_is_a_bad_request(self, client, student, space):
        page = _poll(client, student, space)
        resp = client.get(
            f"/api/spaces/{space['id']}/messages",
            params={"after": page["server_time"], "before": "x"},
            headers=_auth(student),
        )
        assert resp.status_code == 400
        assert _error(resp)["code"] == "VALIDATION_ERROR"

    def test_posting_is_rate_limited(self, client, student, space):
        for n in range(10):
            assert _post(client, student, space, f"m{n}").status_code == 201
        resp = _post(client, student, space, "one too many")
        assert resp.status_code == 429
        assert _error(resp)["details"]["retry_after"] >= 1


class TestWhoMayTakePart:
    def test_an_outsider_gets_the_same_answer_as_a_classroom_that_does_not_exist(
        self, client, db, space, student
    ):
        _post(client, student, space)
        outsider = _user(db, role="student")
        nowhere = {"id": str(uuid4())}
        for method in ("get", "post"):
            answers = []
            for target in (space, nowhere):
                url = f"/api/spaces/{target['id']}/messages"
                if method == "get":
                    resp = client.get(url, headers=_auth(outsider))
                else:
                    resp = client.post(url, json={"body": "hi"}, headers=_auth(outsider))
                assert resp.status_code == 403
                answers.append(resp.content)
            assert answers[0] == answers[1]

    def test_a_class_9_student_without_a_guardian_is_gated(self, client, db, space):
        gated = _user(db, role="student", class_level=9)
        resp = client.get(f"/api/spaces/{space['id']}/messages", headers=_auth(gated))
        assert (resp.status_code, _error(resp)["code"]) == (403, "GATE_PENDING")


class TestModeration:
    def test_a_muted_student_reads_and_is_told_why_they_cannot_post(
        self, client, teacher, space, student
    ):
        assert _mute(client, teacher, space, student).status_code == 204
        page = _poll(client, student, space)
        assert (page["can_post"], page["muted"]) == (False, True)
        resp = _post(client, student, space)
        assert (resp.status_code, _error(resp)["details"]["reason"]) == (400, "muted")
        people = client.get(f"/api/spaces/{space['id']}/people", headers=_auth(teacher)).json()
        assert [m["muted"] for m in people["members"]] == [True]

        assert _mute(client, teacher, space, student, muted=False).status_code == 204
        assert _post(client, student, space).status_code == 201

    def test_a_locked_chat_takes_posts_from_its_teacher_only(self, client, teacher, space, student):
        locked = _patch(client, teacher, space, chat_locked=True)
        assert locked.status_code == 200 and locked.json()["chat_locked"] is True
        page = _poll(client, student, space)
        assert (page["can_post"], page["chat_locked"]) == (False, True)
        resp = _post(client, student, space)
        assert (resp.status_code, _error(resp)["details"]["reason"]) == (400, "chat_locked")
        assert _post(client, teacher, space, "Quiet please.").status_code == 201
        assert _poll(client, teacher, space)["can_post"] is True

        assert _patch(client, teacher, space, chat_locked=False).json()["chat_locked"] is False
        assert _post(client, student, space).status_code == 201

    def test_an_archived_classroom_is_read_only_but_still_moderated(
        self, client, teacher, space, student
    ):
        mid = _post(client, student, space).json()["id"]
        assert _patch(client, teacher, space, status="archived").status_code == 200
        resp = _post(client, student, space)
        assert (resp.status_code, _error(resp)["details"]["reason"]) == (400, "archived")
        assert _poll(client, student, space)["can_post"] is False
        assert client.delete(f"/api/messages/{mid}", headers=_auth(teacher)).status_code == 204

    def test_only_the_classroom_teacher_moderates(self, client, db, teacher, space, student):
        mid = _post(client, student, space).json()["id"]
        other_teacher = _user(db, role="teacher")
        for user in (student, other_teacher):
            assert client.delete(f"/api/messages/{mid}", headers=_auth(user)).status_code == 403
            assert _mute(client, user, space, student).status_code == 403
        unknown = client.delete(f"/api/messages/{uuid4()}", headers=_auth(teacher))
        assert unknown.status_code == 403
        assert _poll(client, student, space)["messages"][0]["id"] == mid

    def test_deleting_twice_is_not_an_error(self, client, teacher, space, student):
        mid = _post(client, student, space).json()["id"]
        for _ in range(2):
            assert client.delete(f"/api/messages/{mid}", headers=_auth(teacher)).status_code == 204

    def test_only_a_current_member_can_be_muted(self, client, db, teacher, space):
        stranger = _user(db, role="student")
        assert _mute(client, teacher, space, stranger).status_code == 403

    def test_a_student_cannot_lock_the_chat(self, client, space, student):
        assert _patch(client, student, space, chat_locked=True).status_code == 403

    def test_moderation_is_audited(self, client, db, service_conn, teacher, space, student):
        mid = _post(client, student, space).json()["id"]
        client.delete(f"/api/messages/{mid}", headers=_auth(teacher))
        client.delete(f"/api/messages/{mid}", headers=_auth(teacher))  # not a second row
        _mute(client, teacher, space, student)
        _mute(client, teacher, space, student, muted=False)
        admin = service_conn.execute(
            text("SELECT id FROM app_user WHERE role = 'admin' AND status = 'active' LIMIT 1")
        ).scalar_one_or_none()
        if admin is None:
            pytest.skip("needs an owner-provisioned administrator to read audit_log")
        set_current_user_id(db, admin)
        # Sorted, not ordered by time: created_at is now(), frozen for the test.
        rows = db.execute(
            text(
                "SELECT action, target FROM audit_log WHERE actor_id = :t "
                "AND action LIKE 'classroom.%' AND action <> 'classroom.created' ORDER BY action"
            ),
            {"t": teacher},
        ).all()
        member = f"classroom_space/{space['id']}/student/{student}"
        assert [tuple(r) for r in rows] == [
            ("classroom.message_deleted", f"space_message/{mid}"),
            ("classroom.student_muted", member),
            ("classroom.student_unmuted", member),
        ]
