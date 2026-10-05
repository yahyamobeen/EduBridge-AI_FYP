"""
The classroom membership boundary — findings B9, B10 and B11.

Every test here talks to the DATABASE as `app_backend`, with no endpoint in
between. That is the point: `user-stories.md` card 1.5 promises that a missed
application check is caught again by the database, and the August 2026 review
found that promise did not hold for these tables (database.md §2.4). These tests
are what makes it hold — each one is an attack the application would never
make, refused by PostgreSQL itself.

⚠️ A REFUSAL IS ASSERTED BY ITS MESSAGE, NOT ONLY ITS TYPE. A unique violation or
   a bad enum value is also a ProgrammingError/DBAPIError, and would make a test
   pass for the wrong reason (the same rule as test_rls.py:343-346). Each refusal
   runs inside `db.begin_nested()`, so the aborted savepoint does not poison the
   assertions that follow it.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.classroom.codes import generate_join_code
from app.core.db import set_current_user_id

GROUP_BY_CLASS = {9: "science", 10: "computer", 11: "pre_medical", 12: "pre_medical"}


# ── arrangement helpers ─────────────────────────────────────────────────────


def _user(db, *, role: str, class_level: int = 11, group: str | None = None, board="PCTB") -> str:
    """A user with the profile row their role needs, created as themselves."""
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


def _subject(db, name: str = "Physics", *, level: int = 11, board: str = "PCTB") -> UUID:
    return db.execute(
        text(
            "SELECT s.id FROM subject s "
            "  JOIN class_level cl ON cl.id = s.class_level_id "
            "  JOIN board b ON b.id = cl.board_id "
            " WHERE b.code = CAST(:board AS board_code) AND cl.level = :lvl AND s.name = :name"
        ),
        {"board": board, "lvl": level, "name": name},
    ).scalar_one()


def _as(db, user_id: str) -> None:
    set_current_user_id(db, UUID(user_id))


def _create(db, teacher_id: str, subject_id: UUID, title: str = "Test class") -> UUID:
    _as(db, teacher_id)
    row = (
        db.execute(
            text("SELECT outcome, new_space_id FROM app.create_space(:t, :s)"),
            {"t": title, "s": subject_id},
        )
        .mappings()
        .one()
    )
    assert row["outcome"] == "created", row["outcome"]
    return row["new_space_id"]


def _rotate(db, teacher_id: str, space_id: UUID) -> str:
    _as(db, teacher_id)
    code = generate_join_code()
    outcome = db.execute(
        text("SELECT outcome FROM app.rotate_join_code(:s, :c)"), {"s": space_id, "c": code}
    ).scalar_one()
    assert outcome == "rotated", outcome
    return code


def _space(db, teacher_id: str, subject_id: UUID) -> tuple[UUID, str]:
    space_id = _create(db, teacher_id, subject_id)
    return space_id, _rotate(db, teacher_id, space_id)


def _join(db, student_id: str, code: str) -> str:
    _as(db, student_id)
    return db.execute(
        text("SELECT outcome FROM app.join_space_by_code(:c)"), {"c": code}
    ).scalar_one()


def _refused(db, statement: str, params: dict) -> str:
    """Run a statement that MUST be refused; return the lower-cased message."""
    with pytest.raises(DBAPIError) as caught, db.begin_nested():
        db.execute(text(statement), params)
        db.flush()
    return str(caught.value).lower()


def _count(db, statement: str, params: dict) -> int:
    return db.execute(text(statement), params).scalar_one()


@pytest.fixture
def teacher(db) -> str:
    return _user(db, role="teacher")


@pytest.fixture
def physics_11(db) -> UUID:
    return _subject(db, "Physics", level=11)


@pytest.fixture
def classroom(db, teacher, physics_11) -> tuple[UUID, str]:
    """A Class 11 PCTB Physics space with a live code. Class 11: no guardian gate."""
    return _space(db, teacher, physics_11)


# ── B9 / B10: the direct write paths are gone ───────────────────────────────


class TestDirectWritesAreRefused:
    def test_student_cannot_insert_an_enrollment(self, db, classroom):
        space_id, _ = classroom
        student = _user(db, role="student")
        message = _refused(
            db,
            "INSERT INTO enrollment (space_id, student_id) VALUES (:s, :u)",
            {"s": space_id, "u": student},
        )
        assert "permission denied" in message

    def test_removed_student_cannot_clear_their_own_removal(self, db, teacher, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, teacher)
        assert db.execute(
            text("SELECT app.remove_student(:s, :u)"), {"s": space_id, "u": student}
        ).scalar_one()
        _as(db, student)
        message = _refused(
            db,
            "UPDATE enrollment SET left_at = NULL, removed_at = NULL WHERE student_id = :u",
            {"u": student},
        )
        assert "permission denied" in message

    def test_nobody_inserts_a_classroom_directly(self, db, teacher, physics_11):
        _as(db, teacher)
        message = _refused(
            db,
            "INSERT INTO classroom_space (owner_id, owner_role, subject_id, title) "
            "VALUES (:u, 'teacher', :s, 'Direct')",
            {"u": teacher, "s": physics_11},
        )
        assert "permission denied" in message

    def test_a_student_cannot_create_a_classroom_through_the_function(self, db, physics_11):
        student = _user(db, role="student")
        _as(db, student)
        outcome = db.execute(
            text("SELECT outcome FROM app.create_space('Mine', :s)"), {"s": physics_11}
        ).scalar_one()
        assert outcome == "not_teacher"
        assert (
            _count(db, "SELECT count(*) FROM classroom_space WHERE owner_id = :u", {"u": student})
            == 0
        )

    def test_a_parent_cannot_create_a_classroom(self, db, physics_11):
        parent = _user(db, role="parent")
        _as(db, parent)
        outcome = db.execute(
            text("SELECT outcome FROM app.create_space('Mine', :s)"), {"s": physics_11}
        ).scalar_one()
        assert outcome == "not_teacher"

    def test_nobody_inserts_a_join_code_directly(self, db, teacher, classroom):
        space_id, _ = classroom
        _as(db, teacher)
        message = _refused(
            db, "INSERT INTO join_code (space_id, code) VALUES (:s, 'AAAAAAAA')", {"s": space_id}
        )
        assert "permission denied" in message

    def test_teacher_cannot_move_a_classroom_to_another_subject(self, db, teacher, classroom):
        space_id, _ = classroom
        _as(db, teacher)
        message = _refused(
            db,
            "UPDATE classroom_space SET subject_id = :o WHERE id = :s",
            {"o": _subject(db, "Chemistry", level=11), "s": space_id},
        )
        assert "permission denied" in message

    def test_teacher_cannot_hand_a_classroom_to_someone_else(self, db, teacher, classroom):
        space_id, _ = classroom
        other = _user(db, role="teacher")
        _as(db, teacher)
        message = _refused(
            db,
            "UPDATE classroom_space SET owner_id = :o WHERE id = :s",
            {"o": other, "s": space_id},
        )
        assert "permission denied" in message

    def test_teacher_cannot_delete_a_classroom(self, db, teacher, classroom):
        space_id, _ = classroom
        _as(db, teacher)
        message = _refused(db, "DELETE FROM classroom_space WHERE id = :s", {"s": space_id})
        assert "permission denied" in message

    def test_teacher_can_rename_and_archive_their_own_classroom(self, db, teacher, classroom):
        """The control: without it, a policy refusing EVERY update would pass the tests above."""
        space_id, _ = classroom
        _as(db, teacher)
        updated = db.execute(
            text("UPDATE classroom_space SET title = 'Renamed', status = 'archived' WHERE id = :s"),
            {"s": space_id},
        ).rowcount
        assert updated == 1

    def test_teacher_cannot_rename_another_teachers_classroom(self, db, classroom):
        space_id, _ = classroom
        intruder = _user(db, role="teacher")
        _as(db, intruder)
        updated = db.execute(
            text("UPDATE classroom_space SET title = 'Mine now' WHERE id = :s"), {"s": space_id}
        ).rowcount
        assert updated == 0

    def test_teacher_cannot_grant_themselves_a_scope(self, db, teacher):
        _as(db, teacher)
        message = _refused(
            db,
            "INSERT INTO teacher_subject_scope (teacher_id, subject_id) VALUES (:u, :s)",
            {"u": teacher, "s": _subject(db, "Biology", level=11)},
        )
        assert "row-level security" in message

    def test_scope_rows_cannot_be_deleted_only_revoked(self, db, teacher, classroom):
        _as(db, teacher)
        message = _refused(
            db, "DELETE FROM teacher_subject_scope WHERE teacher_id = :u", {"u": teacher}
        )
        assert "permission denied" in message


# ── reads are scoped ────────────────────────────────────────────────────────


class TestReadsAreScoped:
    def test_a_member_cannot_read_the_join_code(self, db, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        assert (
            _count(db, "SELECT count(*) FROM join_code WHERE space_id = :s", {"s": space_id}) == 0
        )

    def test_another_teacher_cannot_read_the_join_code(self, db, classroom):
        space_id, _ = classroom
        _as(db, _user(db, role="teacher"))
        assert (
            _count(db, "SELECT count(*) FROM join_code WHERE space_id = :s", {"s": space_id}) == 0
        )

    def test_owner_reads_exactly_one_live_code_after_rotations(self, db, teacher, classroom):
        space_id, first = classroom
        second = _rotate(db, teacher, space_id)
        third = _rotate(db, teacher, space_id)
        _as(db, teacher)
        live = (
            db.execute(
                text("SELECT code FROM join_code WHERE space_id = :s AND revoked = false"),
                {"s": space_id},
            )
            .scalars()
            .all()
        )
        assert live == [third]
        assert len({first, second, third}) == 3

    def test_space_people_is_empty_for_a_non_member(self, db, classroom):
        space_id, _ = classroom
        _as(db, _user(db, role="student"))
        assert _count(db, "SELECT count(*) FROM app.space_people(:s)", {"s": space_id}) == 0

    def test_members_see_names_but_never_mute_flags(self, db, teacher, classroom):
        space_id, code = classroom
        a, b = _user(db, role="student"), _user(db, role="student")
        assert _join(db, a, code) == "joined"
        assert _join(db, b, code) == "joined"
        _as(db, a)
        rows = db.execute(
            text("SELECT user_id, is_owner, muted FROM app.space_people(:s)"), {"s": space_id}
        ).all()
        assert {str(r.user_id) for r in rows} == {teacher, a, b}
        assert all(r.muted is None for r in rows)
        _as(db, teacher)
        flags = (
            db.execute(
                text("SELECT muted FROM app.space_people(:s) WHERE NOT is_owner"), {"s": space_id}
            )
            .scalars()
            .all()
        )
        assert flags == [False, False]

    def test_another_teacher_cannot_rotate_or_remove(self, db, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, _user(db, role="teacher"))
        assert (
            db.execute(
                text("SELECT outcome FROM app.rotate_join_code(:s, :c)"),
                {"s": space_id, "c": generate_join_code()},
            ).scalar_one()
            == "forbidden"
        )
        assert (
            db.execute(
                text("SELECT app.remove_student(:s, :u)"), {"s": space_id, "u": student}
            ).scalar_one()
            is False
        )
        assert (
            db.execute(text("SELECT app.disable_join_code(:s)"), {"s": space_id}).scalar_one()
            is False
        )

    def test_my_spaces_shows_owner_and_member_views(self, db, teacher, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, teacher)
        owner_row = (
            db.execute(text("SELECT * FROM app.my_spaces() WHERE space_id = :s"), {"s": space_id})
            .mappings()
            .one()
        )
        assert (owner_row["viewer_role"], owner_row["can_manage"], owner_row["member_count"]) == (
            "owner",
            True,
            1,
        )
        _as(db, student)
        member_row = (
            db.execute(text("SELECT * FROM app.my_spaces() WHERE space_id = :s"), {"s": space_id})
            .mappings()
            .one()
        )
        assert (
            member_row["viewer_role"],
            member_row["can_manage"],
            member_row["member_count"],
        ) == ("member", False, None)


# ── the join matrix ─────────────────────────────────────────────────────────


class TestJoinMatrix:
    def test_unknown_code(self, db, classroom):
        assert _join(db, _user(db, role="student"), "ZZZZZZZZ") == "invalid_code"

    def test_codes_are_forgiving_about_case_spaces_and_dashes(self, db, classroom):
        _, code = classroom
        messy = f" {code[:4].lower()}-{code[4:].lower()} "
        assert _join(db, _user(db, role="student"), messy) == "joined"

    def test_a_rotated_away_code_no_longer_works(self, db, teacher, classroom):
        space_id, old = classroom
        _rotate(db, teacher, space_id)
        assert _join(db, _user(db, role="student"), old) == "invalid_code"

    def test_a_disabled_code_no_longer_works(self, db, teacher, classroom):
        space_id, code = classroom
        _as(db, teacher)
        assert (
            db.execute(text("SELECT app.disable_join_code(:s)"), {"s": space_id}).scalar_one()
            is True
        )
        assert _join(db, _user(db, role="student"), code) == "invalid_code"

    def test_an_archived_classroom_cannot_be_joined(self, db, teacher, classroom):
        space_id, code = classroom
        _as(db, teacher)
        db.execute(
            text("UPDATE classroom_space SET status = 'archived' WHERE id = :s"), {"s": space_id}
        )
        assert _join(db, _user(db, role="student"), code) == "invalid_code"

    def test_a_removed_student_gets_the_same_answer_as_an_unknown_code(
        self, db, teacher, classroom
    ):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, teacher)
        assert db.execute(
            text("SELECT app.remove_student(:s, :u)"), {"s": space_id, "u": student}
        ).scalar_one()
        assert _join(db, student, code) == "invalid_code"

    def test_a_student_who_left_may_rejoin(self, db, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, student)
        assert db.execute(text("SELECT app.leave_space(:s)"), {"s": space_id}).scalar_one() is True
        assert _join(db, student, code) == "joined"
        assert (
            _count(
                db,
                "SELECT count(*) FROM enrollment WHERE space_id = :s AND student_id = :u",
                {"s": space_id, "u": student},
            )
            == 1
        )

    def test_joining_twice_reports_already_member(self, db, classroom):
        _, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        assert _join(db, student, code) == "already_member"

    def test_board_mismatch(self, db, classroom):
        _, code = classroom
        assert _join(db, _user(db, role="student", board="STBB"), code) == "class_mismatch"

    def test_class_mismatch(self, db, classroom):
        _, code = classroom
        assert _join(db, _user(db, role="student", class_level=12), code) == "class_mismatch"

    def test_group_mismatch(self, db, teacher):
        # Class 11 Mathematics is taken by pre_engineering and ics, never pre_medical.
        _, code = _space(db, teacher, _subject(db, "Mathematics", level=11))
        student = _user(db, role="student", class_level=11, group="pre_medical")
        assert _join(db, student, code) == "class_mismatch"
        assert (
            _count(db, "SELECT count(*) FROM enrollment WHERE student_id = :u", {"u": student}) == 0
        )

    def test_a_teacher_cannot_join(self, db, classroom):
        _, code = classroom
        assert _join(db, _user(db, role="teacher"), code) == "not_student"

    def test_class_9_without_a_verified_guardian_is_gated(self, db, teacher):
        _, code = _space(db, teacher, _subject(db, "Physics", level=9))
        student = _user(db, role="student", class_level=9)
        assert _join(db, student, code) == "gate_pending"
        assert (
            _count(db, "SELECT count(*) FROM enrollment WHERE student_id = :u", {"u": student}) == 0
        )

    def test_class_9_with_a_pending_guardian_is_gated(self, db, teacher, make_link):
        _, code = _space(db, teacher, _subject(db, "Physics", level=9))
        student = _user(db, role="student", class_level=9)
        make_link(parent_id=_user(db, role="parent"), student_id=student, status="pending")
        assert _join(db, student, code) == "gate_pending"

    def test_class_9_with_a_verified_guardian_joins(self, db, teacher, make_link):
        _, code = _space(db, teacher, _subject(db, "Physics", level=9))
        student = _user(db, role="student", class_level=9)
        make_link(parent_id=_user(db, role="parent"), student_id=student, status="verified")
        assert _join(db, student, code) == "joined"

    def test_class_11_needs_no_guardian(self, db, classroom):
        _, code = classroom
        assert _join(db, _user(db, role="student", class_level=11), code) == "joined"


class TestLeaving:
    def test_leave_is_idempotent_and_reveals_nothing(self, db, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, student)
        assert db.execute(text("SELECT app.leave_space(:s)"), {"s": space_id}).scalar_one() is True
        assert db.execute(text("SELECT app.leave_space(:s)"), {"s": space_id}).scalar_one() is False
        assert db.execute(text("SELECT app.leave_space(:s)"), {"s": uuid4()}).scalar_one() is False

    def test_leave_works_on_an_archived_classroom(self, db, teacher, classroom):
        """Leaving is a consent right (prd.md:258); archiving must not trap a student."""
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, teacher)
        db.execute(
            text("UPDATE classroom_space SET status = 'archived' WHERE id = :s"), {"s": space_id}
        )
        _as(db, student)
        assert db.execute(text("SELECT app.leave_space(:s)"), {"s": space_id}).scalar_one() is True

    def test_a_left_student_disappears_from_my_spaces_and_people(self, db, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _as(db, student)
        db.execute(text("SELECT app.leave_space(:s)"), {"s": space_id})
        assert (
            _count(db, "SELECT count(*) FROM app.my_spaces() WHERE space_id = :s", {"s": space_id})
            == 0
        )
        assert _count(db, "SELECT count(*) FROM app.space_people(:s)", {"s": space_id}) == 0


class TestCapacity:
    def test_fiftieth_active_classroom_is_the_last(self, db, teacher, physics_11):
        for i in range(50):
            _create(db, teacher, physics_11, title=f"Class {i}")
        _as(db, teacher)
        assert (
            db.execute(
                text("SELECT outcome FROM app.create_space('One too many', :s)"), {"s": physics_11}
            ).scalar_one()
            == "classroom_limit"
        )

    def test_archiving_frees_a_slot(self, db, teacher, physics_11):
        ids = [_create(db, teacher, physics_11, title=f"Class {i}") for i in range(50)]
        _as(db, teacher)
        db.execute(
            text("UPDATE classroom_space SET status = 'archived' WHERE id = :s"), {"s": ids[0]}
        )
        assert (
            db.execute(
                text("SELECT outcome FROM app.create_space('Fits now', :s)"), {"s": physics_11}
            ).scalar_one()
            == "created"
        )

    def test_three_hundred_and_first_member_is_refused(self, db, classroom):
        _, code = classroom
        for _ in range(300):
            assert _join(db, _user(db, role="student"), code) == "joined"
        assert _join(db, _user(db, role="student"), code) == "classroom_full"


# ── B11: scope is self-declared and revocable ────────────────────────────────


def _provisioned_admin(service_conn) -> str:
    """An administrator that already exists, or skip (the test_authz_matrix.py:43-72 contract)."""
    admin = service_conn.execute(
        text("SELECT id FROM app_user WHERE role = 'admin' AND status = 'active' LIMIT 1")
    ).scalar_one_or_none()
    if admin is None:
        pytest.skip("needs an owner-provisioned administrator; see the phase 1b handoff, 1.6.6")
    return str(admin)


class TestScopeIsSelfDeclaredAndRevocable:
    def test_creating_a_classroom_declares_the_scope(self, db, teacher, classroom, physics_11):
        _as(db, teacher)
        assert (
            _count(
                db,
                "SELECT count(*) FROM teacher_subject_scope "
                "WHERE teacher_id = :u AND subject_id = :s AND revoked_at IS NULL",
                {"u": teacher, "s": physics_11},
            )
            == 1
        )

    def test_revoked_scope_ends_ownership_and_blocks_redeclaring(
        self, db, service_conn, teacher, classroom, physics_11
    ):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"

        _as(db, _provisioned_admin(service_conn))
        revoked = db.execute(
            text(
                "UPDATE teacher_subject_scope SET revoked_at = now() "
                "WHERE teacher_id = :u AND subject_id = :s"
            ),
            {"u": teacher, "s": physics_11},
        ).rowcount
        assert revoked == 1

        _as(db, teacher)
        assert db.execute(text("SELECT app.owns_space(:s)"), {"s": space_id}).scalar_one() is False
        assert (
            _count(db, "SELECT count(*) FROM join_code WHERE space_id = :s", {"s": space_id}) == 0
        )
        assert _count(db, "SELECT count(*) FROM app.space_people(:s)", {"s": space_id}) == 0
        assert (
            db.execute(
                text("SELECT outcome FROM app.create_space('Again', :s)"), {"s": physics_11}
            ).scalar_one()
            == "scope_revoked"
        )
        # The row is still VISIBLE (space_visible is unchanged) so the interface can explain why.
        assert (
            _count(db, "SELECT count(*) FROM classroom_space WHERE id = :s", {"s": space_id}) == 1
        )


# ── Phase 3: announcements (20261004130000) ─────────────────────────────────


def _post(db, teacher_id: str, space_id: UUID, *, body="Notice", in_future=False) -> UUID:
    _as(db, teacher_id)
    return db.execute(
        text(
            "INSERT INTO announcement (space_id, author_id, body, publish_at) "
            "VALUES (:s, :a, :b, CASE WHEN :future THEN now() + interval '1 hour' ELSE now() END) "
            "RETURNING id"
        ),
        {"s": space_id, "a": teacher_id, "b": body, "future": in_future},
    ).scalar_one()


class TestAnnouncementBoundary:
    def test_a_student_cannot_post(self, db, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        message = _refused(
            db,
            "INSERT INTO announcement (space_id, author_id, body) VALUES (:s, :u, 'hi')",
            {"s": space_id, "u": student},
        )
        assert "row-level security" in message

    def test_an_owner_cannot_post_as_someone_else(self, db, teacher, classroom):
        space_id, _ = classroom
        other = _user(db, role="teacher")
        _as(db, teacher)
        message = _refused(
            db,
            "INSERT INTO announcement (space_id, author_id, body) VALUES (:s, :u, 'forged')",
            {"s": space_id, "u": other},
        )
        assert "row-level security" in message

    def test_an_archived_classroom_is_read_only_for_its_owner(self, db, teacher, classroom):
        space_id, _ = classroom
        _as(db, teacher)
        db.execute(
            text("UPDATE classroom_space SET status = 'archived' WHERE id = :s"), {"s": space_id}
        )
        message = _refused(
            db,
            "INSERT INTO announcement (space_id, author_id, body) VALUES (:s, :u, 'late')",
            {"s": space_id, "u": teacher},
        )
        assert "row-level security" in message

    def test_a_scheduled_post_is_invisible_to_members_but_not_the_owner(
        self, db, teacher, classroom
    ):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        _post(db, teacher, space_id, body="now")
        _post(db, teacher, space_id, body="later", in_future=True)

        _as(db, teacher)
        owner_sees = (
            db.execute(
                text("SELECT body FROM announcement WHERE space_id = :s ORDER BY body"),
                {"s": space_id},
            )
            .scalars()
            .all()
        )
        assert owner_sees == ["later", "now"]

        _as(db, student)
        member_sees = (
            db.execute(text("SELECT body FROM announcement WHERE space_id = :s"), {"s": space_id})
            .scalars()
            .all()
        )
        assert member_sees == ["now"]

    def test_an_outsider_sees_nothing(self, db, teacher, classroom):
        space_id, _ = classroom
        _post(db, teacher, space_id)
        _as(db, _user(db, role="student"))
        assert (
            _count(db, "SELECT count(*) FROM announcement WHERE space_id = :s", {"s": space_id})
            == 0
        )

    def test_a_member_cannot_edit_or_delete(self, db, teacher, classroom):
        space_id, code = classroom
        student = _user(db, role="student")
        assert _join(db, student, code) == "joined"
        post = _post(db, teacher, space_id)
        _as(db, student)
        edited = db.execute(
            text("UPDATE announcement SET body = 'defaced' WHERE id = :p"), {"p": post}
        ).rowcount
        deleted = db.execute(text("DELETE FROM announcement WHERE id = :p"), {"p": post}).rowcount
        assert (edited, deleted) == (0, 0)

    def test_authorship_and_history_cannot_be_rewritten(self, db, teacher, classroom):
        space_id, _ = classroom
        post = _post(db, teacher, space_id)
        _as(db, teacher)
        message = _refused(
            db,
            "UPDATE announcement SET created_at = now() - interval '1 year' WHERE id = :p",
            {"p": post},
        )
        assert "permission denied" in message

    def test_the_author_can_edit_and_delete(self, db, teacher, classroom):
        """The control: a policy refusing everything would pass the tests above."""
        space_id, _ = classroom
        post = _post(db, teacher, space_id)
        _as(db, teacher)
        assert (
            db.execute(
                text("UPDATE announcement SET body = 'fixed' WHERE id = :p"), {"p": post}
            ).rowcount
            == 1
        )
        assert db.execute(text("DELETE FROM announcement WHERE id = :p"), {"p": post}).rowcount == 1


# ── Phase 4: assignments, submissions, grades (20261004140000) ──────────────


def _assign(db, teacher_id: str, space_id: UUID, *, points=10, scheduled=False) -> UUID:
    """An assignment inserted as its author — the direct path the policy governs."""
    _as(db, teacher_id)
    return db.execute(
        text(
            "INSERT INTO assignment (space_id, subject_id, author_id, title, points, publish_at) "
            "SELECT s.id, s.subject_id, :a, 'Lab 1', :pts, "
            "       CASE WHEN :sched THEN now() + interval '1 hour' ELSE now() END "
            "  FROM classroom_space s WHERE s.id = :s "
            "RETURNING id"
        ),
        {"s": space_id, "a": teacher_id, "pts": points, "sched": scheduled},
    ).scalar_one()


def _call(db, user_id: str, statement: str, params: dict):
    _as(db, user_id)
    return db.execute(text(statement), params).scalar_one()


@pytest.fixture
def member(db, classroom) -> str:
    _, code = classroom
    student = _user(db, role="student")
    assert _join(db, student, code) == "joined"
    return student


@pytest.fixture
def lab(db, teacher, classroom) -> UUID:
    return _assign(db, teacher, classroom[0])


class TestAssignmentBoundary:
    def test_a_student_cannot_create_an_assignment(self, db, classroom, member):
        message = _refused(
            db,
            "INSERT INTO assignment (space_id, subject_id, author_id, title) "
            "SELECT id, subject_id, :u, 'Mine' FROM classroom_space WHERE id = :s",
            {"s": classroom[0], "u": member},
        )
        assert "row-level security" in message

    def test_an_owner_cannot_author_as_someone_else(self, db, teacher, classroom):
        other = _user(db, role="teacher")
        _as(db, teacher)
        message = _refused(
            db,
            "INSERT INTO assignment (space_id, subject_id, author_id, title) "
            "SELECT id, subject_id, :u, 'Forged' FROM classroom_space WHERE id = :s",
            {"s": classroom[0], "u": other},
        )
        assert "row-level security" in message

    def test_a_scheduled_assignment_is_invisible_to_members_and_cannot_be_turned_in(
        self, db, teacher, classroom, member
    ):
        later = _assign(db, teacher, classroom[0], scheduled=True)
        _as(db, teacher)
        assert _count(db, "SELECT count(*) FROM assignment WHERE id = :a", {"a": later}) == 1
        _as(db, member)
        assert _count(db, "SELECT count(*) FROM assignment WHERE id = :a", {"a": later}) == 0
        outcome = _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": later})
        assert outcome == "forbidden"

    def test_nobody_writes_a_submission_or_a_grade_directly(self, db, classroom, member, lab):
        _as(db, member)
        submission = _refused(
            db,
            "INSERT INTO assignment_submission (assignment_id, space_id, student_id, body) "
            "VALUES (:a, :s, :u, 'mine')",
            {"a": lab, "s": classroom[0], "u": member},
        )
        grade = _refused(
            db,
            "INSERT INTO submission_grade (assignment_id, space_id, student_id, grade, graded_by) "
            "VALUES (:a, :s, :u, 10, :u)",
            {"a": lab, "s": classroom[0], "u": member},
        )
        assert "permission denied" in submission
        assert "permission denied" in grade

    def test_a_student_cannot_backdate_a_turn_in(self, db, member, lab):
        assert _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab}) == "turned_in"
        message = _refused(
            db,
            "UPDATE assignment_submission SET turned_in_at = '2020-01-01' WHERE assignment_id = :a",
            {"a": lab},
        )
        assert "permission denied" in message

    def test_a_student_cannot_grade_through_the_function(self, db, member, lab):
        outcome = _call(
            db, member, "SELECT app.save_grade(:a, :u, 10, 'self', true)", {"a": lab, "u": member}
        )
        assert outcome == "forbidden"

    def test_a_teacher_sees_work_only_once_turned_in_and_only_while_the_student_stays(
        self, db, teacher, classroom, member, lab
    ):
        def teacher_sees(table: str) -> int:
            _as(db, teacher)
            return _count(
                db,
                f"SELECT count(*) FROM {table} WHERE assignment_id = :a",  # noqa: S608 -- literal
                {"a": lab},
            )

        _call(db, member, "SELECT app.save_submission_draft(:a, 'draft', NULL)", {"a": lab})
        assert teacher_sees("assignment_submission") == 0  # a draft is the student's own
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        assert teacher_sees("assignment_submission") == 1
        _call(db, teacher, "SELECT app.save_grade(:a, :u, 7, '', false)", {"a": lab, "u": member})
        assert teacher_sees("submission_grade") == 1

        _call(db, member, "SELECT app.leave_space(:s)", {"s": classroom[0]})
        assert teacher_sees("assignment_submission") == 0  # user story 7.1
        assert teacher_sees("submission_grade") == 0

    def test_a_classmate_sees_nothing_of_another_students_work(self, db, classroom, member, lab):
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        classmate = _user(db, role="student")
        assert _join(db, classmate, classroom[1]) == "joined"
        _as(db, classmate)
        seen = _count(
            db, "SELECT count(*) FROM assignment_submission WHERE assignment_id = :a", {"a": lab}
        )
        assert seen == 0

    def test_a_grade_is_hidden_until_it_is_returned(self, db, teacher, member, lab):
        def student_sees() -> int:
            _as(db, member)
            return _count(
                db, "SELECT count(*) FROM submission_grade WHERE assignment_id = :a", {"a": lab}
            )

        grade = "SELECT app.save_grade(:a, :u, 9, 'Good', :r)"
        _call(db, teacher, grade, {"a": lab, "u": member, "r": False})
        assert student_sees() == 0
        _call(db, teacher, grade, {"a": lab, "u": member, "r": True})
        assert student_sees() == 1

    def test_graded_work_is_locked(self, db, teacher, member, lab):
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        _call(db, teacher, "SELECT app.save_grade(:a, :u, 9, '', false)", {"a": lab, "u": member})
        assert _call(db, member, "SELECT app.unsubmit_submission(:a)", {"a": lab}) == "graded"
        draft = "SELECT app.save_submission_draft(:a, 'x', NULL)"
        assert _call(db, member, draft, {"a": lab}) == "graded"

    def test_a_grade_above_the_points_is_refused(self, db, teacher, member, lab):
        outcome = _call(
            db, teacher, "SELECT app.save_grade(:a, :u, 11, '', false)", {"a": lab, "u": member}
        )
        assert outcome == "invalid_grade"

    def test_points_cannot_drop_below_an_existing_grade(self, db, teacher, member, lab):
        _call(db, teacher, "SELECT app.save_grade(:a, :u, 8, '', false)", {"a": lab, "u": member})
        _as(db, teacher)
        message = _refused(db, "UPDATE assignment SET points = 5 WHERE id = :a", {"a": lab})
        assert "row-level security" in message
        # The control: down to the grade itself is fine.
        lowered = db.execute(text("UPDATE assignment SET points = 8 WHERE id = :a"), {"a": lab})
        assert lowered.rowcount == 1

    def test_the_due_date_must_follow_publication(self, db, teacher, lab):
        _as(db, teacher)
        message = _refused(
            db,
            "UPDATE assignment SET due_at = publish_at - interval '1 day' WHERE id = :a",
            {"a": lab},
        )
        assert "ck_assignment_due_after_publish" in message

    def test_a_chapter_must_belong_to_the_classrooms_subject(
        self, db, service_conn, teacher, lab, physics_11
    ):
        _as(db, _provisioned_admin(service_conn))
        chemistry = _subject(db, "Chemistry", level=11)
        own, foreign = (
            db.execute(
                text(
                    "INSERT INTO chapter (subject_id, number, title) "
                    "VALUES (:s, 901, 'Test chapter') RETURNING id"
                ),
                {"s": subject},
            ).scalar_one()
            for subject in (physics_11, chemistry)
        )
        _as(db, teacher)
        message = _refused(
            db, "UPDATE assignment SET chapter_id = :c WHERE id = :a", {"c": foreign, "a": lab}
        )
        assert "fk_assignment_chapter_subject" in message
        tagged = db.execute(
            text("UPDATE assignment SET chapter_id = :c WHERE id = :a"), {"c": own, "a": lab}
        )
        assert tagged.rowcount == 1

    def test_internal_helpers_are_not_callable(self, db, member, lab):
        _as(db, member)
        for statement in (
            "SELECT app.submittable_space(:a)",
            "SELECT app.lock_submission(:a, :a)",
        ):
            assert "permission denied" in _refused(db, statement, {"a": lab})

    def test_an_assignment_is_deleted_only_through_the_function(self, db, teacher, lab):
        _as(db, teacher)
        message = _refused(db, "DELETE FROM assignment WHERE id = :a", {"a": lab})
        assert "permission denied" in message
        stranger = _user(db, role="teacher")
        delete = "SELECT deleted FROM app.delete_assignment(:a)"
        assert _call(db, stranger, delete, {"a": lab}) is False
        assert _call(db, teacher, delete, {"a": lab}) is True

    def test_the_author_can_edit(self, db, teacher, lab):
        """The control: a policy refusing everything would pass the tests above."""
        _as(db, teacher)
        edited = db.execute(
            text("UPDATE assignment SET title = 'Lab 1 (revised)' WHERE id = :a"), {"a": lab}
        )
        assert edited.rowcount == 1


# ── Phase 6: files (20261004150000) ─────────────────────────────────────────

_SHA = "0" * 64


def _sub_key(space_id: UUID, student: str) -> str:
    return f"u/{space_id}/{student}/{uuid4().hex}"


def _add_file(db, student: str, assignment: UUID, key: str) -> str:
    _as(db, student)
    return db.execute(
        text(
            "SELECT outcome FROM app.add_submission_file("
            "  :a, :k, 'lab.pdf', 'application/pdf', 100, :h)"
        ),
        {"a": assignment, "k": key, "h": _SHA},
    ).scalar_one()


def _attach(db, teacher: str, space_id: UUID, assignment: UUID) -> str:
    _as(db, teacher)
    return db.execute(
        text(
            "SELECT outcome FROM app.add_material_attachment("
            "  NULL, :a, :k, 'sheet.pdf', 'application/pdf', 100, :h)"
        ),
        {"a": assignment, "k": f"s/{space_id}/{uuid4().hex}", "h": _SHA},
    ).scalar_one()


class TestFileBoundary:
    def test_nobody_writes_a_file_row_directly(self, db, classroom, member, lab):
        _as(db, member)
        message = _refused(
            db,
            "INSERT INTO material_attachment (space_id, assignment_id, uploaded_by, object_key, "
            "  filename, content_type, size_bytes, sha256) "
            "VALUES (:s, :a, :u, :k, 'x.pdf', 'application/pdf', 1, :h)",
            {
                "s": classroom[0],
                "a": lab,
                "u": member,
                "k": f"s/{classroom[0]}/{'a' * 32}",
                "h": _SHA,
            },
        )
        assert "permission denied" in message

    def test_a_key_under_another_students_prefix_is_refused(self, db, classroom, member, lab):
        other = _user(db, role="student")
        _as(db, member)
        message = _refused(
            db,
            "SELECT * FROM app.add_submission_file(:a, :k, 'x.pdf', 'application/pdf', 1, :h)",
            {"a": lab, "k": _sub_key(classroom[0], other), "h": _SHA},
        )
        assert "ck_subfile_key" in message

    def test_a_teacher_sees_a_file_only_once_turned_in_and_while_the_student_stays(
        self, db, teacher, classroom, member, lab
    ):
        def teacher_sees() -> int:
            _as(db, teacher)
            return _count(db, "SELECT count(*) FROM submission_file", {})

        assert _add_file(db, member, lab, _sub_key(classroom[0], member)) == "added"
        assert teacher_sees() == 0  # a draft's files are the student's own
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        assert teacher_sees() == 1
        _call(db, member, "SELECT app.leave_space(:s)", {"s": classroom[0]})
        assert teacher_sees() == 0

    def test_a_classmate_sees_nothing(self, db, classroom, member, lab):
        _add_file(db, member, lab, _sub_key(classroom[0], member))
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        classmate = _user(db, role="student")
        assert _join(db, classmate, classroom[1]) == "joined"
        _as(db, classmate)
        assert _count(db, "SELECT count(*) FROM submission_file", {}) == 0

    def test_a_scheduled_posts_attachment_is_hidden_from_members(
        self, db, teacher, classroom, member, lab
    ):
        later = _assign(db, teacher, classroom[0], scheduled=True)
        assert _attach(db, teacher, classroom[0], later) == "added"
        assert _attach(db, teacher, classroom[0], lab) == "added"
        _as(db, teacher)
        assert _count(db, "SELECT count(*) FROM material_attachment", {}) == 2
        _as(db, member)
        visible = _count(
            db, "SELECT count(*) FROM material_attachment WHERE assignment_id = :a", {"a": lab}
        )
        hidden = _count(
            db, "SELECT count(*) FROM material_attachment WHERE assignment_id = :a", {"a": later}
        )
        assert (visible, hidden) == (1, 0)

    def test_only_the_owner_deletes_an_attachment(self, db, teacher, classroom, member, lab):
        _attach(db, teacher, classroom[0], lab)
        _as(db, member)
        assert db.execute(text("DELETE FROM material_attachment")).rowcount == 0
        _as(db, teacher)
        assert db.execute(text("DELETE FROM material_attachment")).rowcount == 1

    def test_the_sixth_file_is_refused(self, db, classroom, member, lab):
        outcomes = [_add_file(db, member, lab, _sub_key(classroom[0], member)) for _ in range(6)]
        assert outcomes == ["added"] * 5 + ["too_many_files"]

    def test_turned_in_work_takes_no_new_file_and_graded_work_none_at_all(
        self, db, teacher, classroom, member, lab
    ):
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        assert _add_file(db, member, lab, _sub_key(classroom[0], member)) == "turned_in"
        _call(db, teacher, "SELECT app.save_grade(:a, :u, 5, '', false)", {"a": lab, "u": member})
        assert _add_file(db, member, lab, _sub_key(classroom[0], member)) == "graded"

    def test_internal_helpers_are_not_callable(self, db, classroom, member):
        _as(db, member)
        for statement in (
            "SELECT app.space_storage_bytes(:s)",
            "SELECT app.lock_space_files(:s)",
        ):
            assert "permission denied" in _refused(db, statement, {"s": classroom[0]})

    def test_deleting_an_assignment_returns_every_key_even_of_a_student_who_left(
        self, db, teacher, classroom, member, lab
    ):
        student_key = _sub_key(classroom[0], member)
        _add_file(db, member, lab, student_key)
        _call(db, member, "SELECT app.leave_space(:s)", {"s": classroom[0]})
        _attach(db, teacher, classroom[0], lab)
        _as(db, teacher)
        row = (
            db.execute(
                text("SELECT deleted, object_keys FROM app.delete_assignment(:a)"), {"a": lab}
            )
            .mappings()
            .one()
        )
        assert row["deleted"] is True
        assert student_key in row["object_keys"]
        assert len(row["object_keys"]) == 2


# ── Phase 6b: several links on a piece of work (20261005120000) ─────────────


def _add_link(db, student: str, assignment: UUID, url: str = "https://example.com/work") -> str:
    _as(db, student)
    return db.execute(
        text("SELECT outcome FROM app.add_submission_link(:a, :u)"), {"a": assignment, "u": url}
    ).scalar_one()


class TestLinkBoundary:
    def test_nobody_writes_a_link_row_directly(self, db, classroom, member, lab):
        _add_link(db, member, lab)  # a draft row to aim at
        _as(db, member)
        message = _refused(
            db,
            "INSERT INTO submission_link (submission_id, space_id, student_id, url) "
            "SELECT id, space_id, student_id, 'https://example.com/x' "
            "  FROM assignment_submission WHERE assignment_id = :a",
            {"a": lab},
        )
        assert "permission denied" in message

    def test_only_an_https_link_is_stored(self, db, member, lab):
        for bad in ("javascript:alert(1)", "http://example.com", "https://a b.com", ""):
            assert _add_link(db, member, lab, bad) == "invalid_url"

    def test_a_teacher_sees_a_link_only_once_turned_in_and_while_the_student_stays(
        self, db, teacher, classroom, member, lab
    ):
        def teacher_sees() -> int:
            _as(db, teacher)
            return _count(db, "SELECT count(*) FROM submission_link", {})

        assert _add_link(db, member, lab) == "added"
        assert teacher_sees() == 0  # a draft's links are the student's own
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        assert teacher_sees() == 1
        _call(db, member, "SELECT app.leave_space(:s)", {"s": classroom[0]})
        assert teacher_sees() == 0

    def test_a_classmate_sees_nothing(self, db, classroom, member, lab):
        _add_link(db, member, lab)
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        classmate = _user(db, role="student")
        assert _join(db, classmate, classroom[1]) == "joined"
        _as(db, classmate)
        assert _count(db, "SELECT count(*) FROM submission_link", {}) == 0

    def test_the_same_link_twice_is_one_link_and_the_sixth_is_refused(self, db, member, lab):
        assert _add_link(db, member, lab, "https://example.com/1") == "added"
        assert _add_link(db, member, lab, "https://example.com/1") == "added"
        outcomes = [_add_link(db, member, lab, f"https://example.com/{n}") for n in range(2, 7)]
        assert outcomes == ["added"] * 4 + ["too_many_links"]
        _as(db, member)
        assert _count(db, "SELECT count(*) FROM submission_link", {}) == 5

    def test_turned_in_work_takes_no_new_link_and_graded_work_none_at_all(
        self, db, teacher, member, lab
    ):
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        assert _add_link(db, member, lab) == "turned_in"
        _call(db, teacher, "SELECT app.save_grade(:a, :u, 5, '', false)", {"a": lab, "u": member})
        assert _add_link(db, member, lab) == "graded"

    def test_only_the_student_removes_their_link_and_only_while_a_draft(
        self, db, teacher, classroom, member, lab
    ):
        _add_link(db, member, lab)
        _as(db, member)
        link = db.execute(text("SELECT id FROM submission_link")).scalar_one()
        classmate = _user(db, role="student")
        _join(db, classmate, classroom[1])
        for other in (classmate, teacher):
            assert _call(db, other, "SELECT app.remove_submission_link(:l)", {"l": link}) == (
                "forbidden"
            )
        _call(db, member, "SELECT app.turn_in_submission(:a)", {"a": lab})
        assert _call(db, member, "SELECT app.remove_submission_link(:l)", {"l": link}) == (
            "turned_in"
        )
        _call(db, member, "SELECT app.unsubmit_submission(:a)", {"a": lab})
        assert _call(db, member, "SELECT app.remove_submission_link(:l)", {"l": link}) == (
            "removed"
        )

    def test_a_scheduled_assignment_takes_no_link(self, db, teacher, classroom, member):
        later = _assign(db, teacher, classroom[0], scheduled=True)
        assert _add_link(db, member, later) == "forbidden"

    def test_deleting_an_assignment_takes_its_links_with_it(self, db, teacher, member, lab):
        _add_link(db, member, lab)
        _as(db, teacher)
        db.execute(text("SELECT * FROM app.delete_assignment(:a)"), {"a": lab})
        _as(db, member)
        assert _count(db, "SELECT count(*) FROM submission_link", {}) == 0
