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


def _make_user(session, email: str) -> str:
    """`app_user_insert` is WITH CHECK (true), so this needs no bound user."""
    return str(
        session.execute(
            text(
                "INSERT INTO app_user (email, password_hash, role, full_name) "
                "VALUES (:email, 'x', 'student', 'RLS Test') RETURNING id"
            ),
            {"email": email},
        ).scalar_one()
    )


class TestFailClosed:
    """With no user bound, owner-scoped policies return NOTHING."""

    def test_user_rows_are_invisible_without_a_bound_user(self, db, unique_email):
        _make_user(db, unique_email("rls"))
        db.flush()

        # Same session, same transaction — simply no app.current_user_id set.
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
