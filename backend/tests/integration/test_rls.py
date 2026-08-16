"""
Row Level Security — the Definition of Done items.

WHAT WAS WRONG WITH THE PREVIOUS VERSION OF THIS FILE, recorded because the same
traps are easy to fall back into:

  * It proved fail-closed on `board`, a REFERENCE table. That says nothing about
    user isolation, which is the property that matters — and since migration
    20260802140000 gave the reference tables a read policy, the old assertion is
    now wrong as well as beside the point.

  * `test_rls_own_row_only` set a RANDOM uuid, got zero rows, then asserted
    `all(...)` over an empty list. Vacuously true: it passed whether RLS worked,
    was disabled, or was deleted outright. A test that cannot fail is worse than
    no test, because it reads like coverage.

  * `test_rls_sees_rows_with_user_id_set` asserted `board` returned 2 rows with a
    random user bound. `board` had no policy at all, so it returned 0 — the file
    held two tests making opposite claims about the same query.

These assert against real user rows, with a real user bound.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.db import engine, set_current_user_id


def _make_user(session, email: str, **extra) -> str:
    """
    Bind the id BEFORE inserting.

    The applied database scopes app_user inserts to the acting user, so an
    unbound insert is refused — which is also why `register()` binds the id it
    is about to create. (The repo's 20260801120100 once showed the permissive
    `WITH CHECK (true)`; migration 20260802150000 reconciled the live database
    to the stricter owner-scoped form.)
    """
    from uuid import uuid4

    from app.core.db import set_current_user_id

    user_id = uuid4()
    set_current_user_id(session, user_id)
    role = extra.get("role", "student")
    columns = "id, email, password_hash, role, full_name"
    values = f":id, :email, 'x', '{role}', 'Test User'"
    if extra.get("verified"):
        columns += ", email_verified_at"
        values += ", now()"
    session.execute(
        text(f"INSERT INTO app_user ({columns}) VALUES ({values})"),  # noqa: S608
        {"id": user_id, "email": email},
    )
    return str(user_id)


class TestFailClosed:
    """With no user bound, owner-scoped policies return NOTHING."""

    def test_user_rows_are_invisible_without_a_bound_user(self, db, unique_email):
        _make_user(db, unique_email("rls"))
        db.flush()

        # Creating the row required a binding (the applied INSERT policy is
        # owner-scoped), so clear it and ask again. `app.current_user_id()` is
        # NULLIF(setting, '')::uuid, so an empty string is genuinely "unset".
        db.execute(text("SELECT set_config('app.current_user_id', '', true)"))

        count = db.execute(text("SELECT count(*) FROM app_user")).scalar_one()
        assert count == 0, (
            "app_user returned rows with no user bound, so RLS is not fail-closed. "
            "Check that DATABASE_URL connects as app_backend and that FORCE ROW "
            "LEVEL SECURITY is still set."
        )

    def test_student_profiles_are_invisible_too(self, db):
        assert db.execute(text("SELECT count(*) FROM student_profile")).scalar_one() == 0


class TestOwnRowsOnly:
    """
    With a user bound, exactly that user's row comes back and no one else's.
    Two REAL users, so the assertion is capable of failing.
    """

    def test_sees_own_row_and_not_the_others(self, db, unique_email):
        mine = _make_user(db, unique_email("mine"))
        theirs = _make_user(db, unique_email("theirs"))
        db.flush()

        set_current_user_id(db, mine)
        visible = {str(r[0]) for r in db.execute(text("SELECT id FROM app_user")).fetchall()}

        assert mine in visible, "the bound user could not see their own row"
        assert theirs not in visible, "another user's row leaked through RLS"


class TestReferenceDataIsReadable:
    """
    Migration 20260802140000. These tables were caught by the blanket
    ENABLE/FORCE loop and never given a policy, so they were deny-all for
    app_backend — which is why /reference/enums needed a privileged connection.
    """

    @pytest.mark.parametrize("table", ["board", "class_level", "subject", "subject_group"])
    def test_reference_tables_are_readable_by_the_app_role(self, db, table):
        count = db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert count > 0, f"{table} is not readable by app_backend"

    def test_reference_data_is_not_writable(self, db):
        """
        SELECT only, deliberately. app_backend holds write grants on every
        table, so a `FOR ALL` policy here would have handed the application
        curriculum mutation as a side effect.
        """
        with pytest.raises((ProgrammingError, DBAPIError)):
            db.execute(text("INSERT INTO board (code, name) VALUES ('PCTB', 'should be denied')"))
            db.flush()


class TestAnswerKeysStayUnreachable:
    """
    NFR-8 database backstop. `question_key` has NO policy on purpose, and the
    reference-data migration deliberately did not give it one. If this ever
    starts returning rows, someone has "fixed" a table that was never broken.
    """

    def test_question_key_is_denied_even_with_a_user_bound(self, db, unique_email):
        user_id = _make_user(db, unique_email("keys"))
        db.flush()
        set_current_user_id(db, user_id)

        assert db.execute(text("SELECT count(*) FROM question_key")).scalar_one() == 0


class TestConnectionRole:
    def test_app_backend_cannot_bypass_rls(self):
        """
        The rule the whole design rests on. A role with rolbypassrls or rolsuper
        makes every policy inert while the application looks perfectly healthy,
        which is exactly why it is asserted rather than trusted.
        """
        with engine.connect() as conn:
            is_super, bypasses = conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()

        assert is_super is False, "connected as a superuser; RLS would be bypassed"
        assert bypasses is False, "connected as a role with BYPASSRLS"

    def test_startup_check_agrees(self):
        from app.core.db import assert_backend_role_cannot_bypass_rls

        assert_backend_role_cannot_bypass_rls()


class TestSetCurrentUserId:
    def test_rejects_a_non_uuid(self, db):
        """
        The identifier is parsed before it reaches SQL. `set_config` takes it as
        a bind parameter now, but the parse is what stops a caller passing
        something meaningless and getting silent zero-row behaviour.
        """
        with pytest.raises(ValueError):
            set_current_user_id(db, "not-a-uuid")

    def test_binding_is_visible_within_the_transaction(self, db):
        user_id = str(uuid4())
        set_current_user_id(db, user_id)
        bound = db.execute(text("SELECT current_setting('app.current_user_id', true)")).scalar_one()
        assert bound == user_id


class TestUnboundAppUserInsertRefused:
    """
    RBAC-002 Phase 1. The app_user INSERT policy is owner-scoped
    (`WITH CHECK (id = app.current_user_id())`), so an application connection
    that forgets to bind a user FAILS the insert instead of silently creating a
    row nobody can read back. `register()` binds before inserting, so this never
    fires in normal operation.
    """

    def test_insert_without_a_bound_user_is_refused(self, db, unique_email):
        from uuid import uuid4

        with pytest.raises((ProgrammingError, DBAPIError)):
            db.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
                    "VALUES (:id, :email, 'x', 'student', 'active', 'unbound')"
                ),
                {"id": uuid4(), "email": unique_email("unbound")},
            )
            db.flush()


class TestPartitionDirectAccessDenied:
    """
    RBAC-002 Phase 1. The blanket ENABLE/FORCE loop in 20260801120100 skipped
    `*_default` partitions, leaving the audit and request-log DEFAULT partitions
    with RLS disabled — a direct `SELECT * FROM audit_log_default` read the
    whole audit trail past `audit_admin_read`. The migration enabled+forced RLS
    on them with no policies, so direct access is default-deny while
    parent-routed writes still land.
    """

    def test_audit_log_default_is_not_readable_by_a_bound_non_admin(self, db, unique_email):
        user_id = _make_user(db, unique_email("audit"))
        db.flush()
        set_current_user_id(db, user_id)

        assert db.execute(text("SELECT count(*) FROM audit_log_default")).scalar_one() == 0

    def test_api_request_log_default_is_not_readable_either(self, db, unique_email):
        user_id = _make_user(db, unique_email("reqlog"))
        db.flush()
        set_current_user_id(db, user_id)

        assert db.execute(text("SELECT count(*) FROM api_request_log_default")).scalar_one() == 0


class TestParentReadsProgressButNeverChat:
    """
    prd.md §4.2 / §21 TEL-3: a verified parent reads a child's PROGRESS
    (student_profile via is_verified_guardian_of) but never the tutor chat
    content (chat_session/message are student-owner-only). Asserted per table so
    the boundary is explicit.
    """

    def test_verified_parent_reads_progress_but_zero_chat_rows(self, db, unique_email, make_link):
        from uuid import uuid4

        student_id = _make_user(db, unique_email("par"), verified=True)
        set_current_user_id(db, student_id)
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, 'PCTB', 9, 'science', 'en', 'en')"
            ),
            {"id": student_id},
        )
        chat_id = uuid4()
        db.execute(
            text("INSERT INTO chat_session (id, student_id) VALUES (:id, :sid)"),
            {"id": chat_id, "sid": student_id},
        )
        db.execute(
            text("INSERT INTO message (session_id, role, content) VALUES (:sid, 'student', 'hi')"),
            {"sid": chat_id},
        )

        parent_id = _make_user(db, unique_email("par"), role="parent")
        set_current_user_id(db, parent_id)
        db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": parent_id})
        db.flush()
        # Through the real confirm path: since 20260803090000 a verified link
        # cannot be inserted or updated into existence directly.
        make_link(parent_id=parent_id, student_id=student_id, status="verified")

        set_current_user_id(db, parent_id)
        progress = db.execute(
            text("SELECT count(*) FROM student_profile WHERE user_id = :s"), {"s": student_id}
        ).scalar_one()
        sessions = db.execute(
            text("SELECT count(*) FROM chat_session WHERE student_id = :s"), {"s": student_id}
        ).scalar_one()
        messages = db.execute(
            text("SELECT count(*) FROM message WHERE session_id = :c"), {"c": chat_id}
        ).scalar_one()

        assert progress == 1, "a verified parent must read the child's progress"
        assert sessions == 0, "a parent must not see the child's chat sessions"
        assert messages == 0, "a parent must not see the child's messages"

    def test_an_unverified_parent_reads_nothing(self, db, unique_email):
        student_id = _make_user(db, unique_email("par"))
        set_current_user_id(db, student_id)
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, 'PCTB', 9, 'science', 'en', 'en')"
            ),
            {"id": student_id},
        )
        parent_id = _make_user(db, unique_email("par"), role="parent")
        set_current_user_id(db, parent_id)
        db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": parent_id})
        db.execute(
            text(
                "INSERT INTO guardian_link (parent_id, student_id, status) "
                "VALUES (:p, :s, 'pending')"
            ),
            {"p": parent_id, "s": student_id},
        )
        db.flush()

        set_current_user_id(db, parent_id)
        progress = db.execute(
            text("SELECT count(*) FROM student_profile WHERE user_id = :s"), {"s": student_id}
        ).scalar_one()

        assert progress == 0, "a pending (unverified) parent must not read progress"


class TestAdminIsNotSelfRegistrable:
    """
    Finding A1, second layer. Migration 20260816120000.

    The first layer is `RegistrableRole`, which removes `admin` from the
    registration schema and is asserted in tests/unit/test_register_schema.py.
    This is the layer that holds when the first is bypassed — a future endpoint
    that writes `app_user` without going through `RegisterRequest`, for
    instance. Card 1.5 promises the database catches a missed application check;
    for this one field, it now does.

    Deliberately NOT a test of the API. `POST /auth/register` cannot even
    express the request any more, so an endpoint test would assert Pydantic's
    behaviour rather than the policy's.
    """

    def test_app_backend_cannot_insert_an_administrator(self, db):
        user_id = uuid4()
        set_current_user_id(db, user_id)

        # A savepoint, so the deliberate failure does not poison the rest of the
        # enclosing test transaction.
        with pytest.raises((ProgrammingError, DBAPIError)) as caught, db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
                    "VALUES (:id, :email, 'x', 'admin', 'active', 'Should Not Exist')"
                ),
                {"id": user_id, "email": f"admin-{user_id}@example.com"},
            )

        # 42501 is insufficient_privilege, which is what a WITH CHECK violation
        # raises. Asserting the message rather than only the type, because a
        # unique-violation or a bad-enum error would also be a ProgrammingError
        # and would make this pass for the wrong reason.
        assert "row-level security" in str(caught.value).lower()

    def test_the_same_insert_succeeds_for_a_non_administrator(self, db):
        """
        The control. Without it, a policy that refused EVERY insert would pass
        the test above and nobody could register at all.
        """
        user_id = uuid4()
        set_current_user_id(db, user_id)

        db.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
                "VALUES (:id, :email, 'x', 'teacher', 'active', 'Perfectly Fine')"
            ),
            {"id": user_id, "email": f"teacher-{user_id}@example.com"},
        )
        db.flush()

        assert (
            db.execute(
                text("SELECT count(*) FROM app_user WHERE id = :id"), {"id": user_id}
            ).scalar_one()
            == 1
        )
