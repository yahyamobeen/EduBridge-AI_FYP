"""
Column-level UPDATE authorization — findings B2, B3 and B4.

Row-Level Security decides WHICH ROWS a request may touch. Until
`20260816160000` nothing decided WHICH COLUMNS: every grant was table-wide, and
`pg_attribute.attacl` was `NULL` for every column in the schema. Combined with
`app_user_self_update` — `USING (id = app.current_user_id())` — that let a bound
user rewrite their own `role`, `status`, `email_verified_at` and `password_hash`,
and a student rewrite their own `class_level`, the parental-consent gate input.

⚠️ EVERY REFUSAL BELOW IS A `permission denied for column …` FROM POSTGRESQL,
   not an application check. That is the point: this is the second layer, and it
   has to hold when the first has a bug. `backend/app/` contains **zero**
   statements that update either table, so nothing here is testing application
   behaviour.

Each refusal gets its own test function rather than sharing one, because a
permission error aborts the transaction and everything after it in the same
transaction would fail for the wrong reason.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.db import set_current_user_id


def _student(db, email: str, *, class_level: int = 9) -> str:
    """A student who owns their own rows, bound as themselves."""
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
            "VALUES (:id, :e, 'x', 'student', 'active', 'Test User')"
        ),
        {"id": user_id, "e": email},
    )
    db.execute(
        text(
            "INSERT INTO student_profile "
            "(user_id, board, class_level, student_group, medium, language_pref) "
            "VALUES (:id, 'PCTB', :lvl, 'science', 'en', 'en')"
        ),
        {"id": user_id, "lvl": class_level},
    )
    db.flush()
    return str(user_id)


def _teacher(db, email: str) -> str:
    """
    A teacher, bound as themselves.

    Exists for one assertion: FR-A8 grants account management to ALL FOUR roles,
    and until `20260816200000` `language_pref` lived on `student_profile` — a
    table this user has no row in. There was nowhere to store the answer, so
    `app.lookup_user_for_email_flow` returned NULL and every teacher, parent and
    administrator silently received English mail.
    """
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
            "VALUES (:id, :e, 'x', 'teacher', 'active', 'Test Teacher')"
        ),
        {"id": user_id, "e": email},
    )
    db.execute(
        text("INSERT INTO teacher_profile (user_id, institution) VALUES (:id, 'Test School')"),
        {"id": user_id},
    )
    db.flush()
    return str(user_id)


def _refused(db, statement: str, params: dict) -> str:
    with pytest.raises(ProgrammingError) as exc:
        db.execute(text(statement), params)
        db.flush()
    return str(exc.value)


class TestAppUserColumnsAreRefused:
    """
    Finding **B3**. Each of these is a privilege escalation on its own, and the
    row-level policy permits every one of them — `app_user_self_update` says
    only that the row must be yours, never which parts of it you may change.
    """

    @pytest.mark.parametrize(
        ("column", "value", "why"),
        [
            ("role", "'admin'", "become an administrator"),
            ("status", "'active'", "un-suspend themselves"),
            ("email_verified_at", "now()", "skip email verification"),
            ("password_hash", "'x'", "set a known password hash without the current one"),
        ],
    )
    def test_a_user_cannot_rewrite_their_own(self, db, unique_email, column, value, why):
        user_id = _student(db, unique_email("colgrant"))
        set_current_user_id(db, user_id)

        message = _refused(
            db,
            # noqa: S608 -- a COLUMN NAME cannot be a bound parameter, and the
            # only values interpolated are the literals in the parametrize list
            # directly above. The house rule against SQL interpolation holds
            # everywhere it can: :uid is still bound.
            f"UPDATE app_user SET {column} = {value} WHERE id = :uid",  # noqa: S608
            {"uid": user_id},
        )

        assert "permission denied" in message.lower(), why
        assert column in message


class TestTheColumnsThatAreAllowed:
    def test_a_user_may_edit_their_own_full_name(self, db, unique_email):
        """
        The control. Without it, a migration that revoked UPDATE and granted
        nothing would pass every test above while breaking `PATCH /auth/me`
        before it is even written.
        """
        user_id = _student(db, unique_email("colgrant"))
        set_current_user_id(db, user_id)

        db.execute(
            text("UPDATE app_user SET full_name = :n WHERE id = :uid"),
            {"n": "Renamed Person", "uid": user_id},
        )
        db.flush()

        name = db.execute(
            text("SELECT full_name FROM app_user WHERE id = :uid"), {"uid": user_id}
        ).scalar()
        assert name == "Renamed Person"

    def test_a_teacher_may_set_their_own_stored_language(self, db, unique_email):
        """
        FR-A8 for the three roles it never reached.

        The control for `20260816200000`'s grant. Before that migration this
        statement had no column to write: `language_pref` was on
        `student_profile`, and a teacher has no row there. A migration that
        added the column and forgot `GRANT UPDATE (language_pref)` would pass
        every refusal test in this file and fail here — which is the failure
        worth catching, because §2.2 revoked table-wide UPDATE and a new column
        therefore arrives ungranted.
        """
        user_id = _teacher(db, unique_email("colgrant"))
        set_current_user_id(db, user_id)

        db.execute(
            text("UPDATE app_user SET language_pref = 'ur' WHERE id = :uid"),
            {"uid": user_id},
        )
        db.flush()

        pref = db.execute(
            text("SELECT language_pref FROM app_user WHERE id = :uid"), {"uid": user_id}
        ).scalar()
        assert str(pref) == "ur"

    def test_the_stored_language_reaches_the_email_flow_lookup(self, db, unique_email):
        """
        ⚠️ THE ASSERTION THAT MAKES THE MIGRATION WORTH ANYTHING, and the one a
        column-grant test alone would miss.

        `app.lookup_user_for_email_flow` is what decides the locale of outgoing
        mail (`service.py:676-678`), and it is SECURITY DEFINER, so a grant
        tells you nothing about what it returns. Before `20260816200000` it
        LEFT JOINed `student_profile` and handed back NULL for this user; the
        caller then fell back to English, silently and for ever.

        Asserted through the function rather than through the ORM on purpose —
        the function is what production calls.
        """
        email = unique_email("colgrant")
        user_id = _teacher(db, email)
        set_current_user_id(db, user_id)
        db.execute(
            text("UPDATE app_user SET language_pref = 'ur' WHERE id = :uid"),
            {"uid": user_id},
        )
        db.flush()

        pref = db.execute(
            text("SELECT language_pref FROM app.lookup_user_for_email_flow(:e)"),
            {"e": email},
        ).scalar()
        assert pref is not None, "a teacher's language is NULL again -- the LEFT JOIN is back"
        assert str(pref) == "ur"

    def test_the_updated_at_trigger_still_fires_without_a_grant_on_it(self, db, unique_email):
        """
        ⚠️ THE REASON `updated_at` IS NOT GRANTED, pinned as a test rather than
        left as a claim in a comment.

        `trg_app_user_updated` is a `BEFORE UPDATE` trigger that assigns
        `NEW.updated_at`. PostgreSQL checks column privileges against the columns
        named in the STATEMENT, not against columns a trigger assigns — so the
        trigger works even though `app_backend` holds no UPDATE on `updated_at`.

        If a future PostgreSQL changed that, this test fails and the fix is one
        extra column in the grant. Without this test the failure would surface as
        "permission denied for column updated_at" on a statement that never
        mentions `updated_at`, which is a genuinely confusing thing to debug.
        """
        user_id = _student(db, unique_email("colgrant"))
        set_current_user_id(db, user_id)
        before = db.execute(
            text("SELECT updated_at FROM app_user WHERE id = :uid"), {"uid": user_id}
        ).scalar()

        db.execute(
            text("UPDATE app_user SET full_name = 'Trigger Probe' WHERE id = :uid"),
            {"uid": user_id},
        )
        db.flush()

        after = db.execute(
            text("SELECT updated_at FROM app_user WHERE id = :uid"), {"uid": user_id}
        ).scalar()
        assert after >= before


class TestStudentProfileColumnsAreRefused:
    """
    Finding **B4**, the parental-consent gate bypass.

    `20260803090000` spent an entire migration proving that `guardian_link.status
    = 'verified'` is reachable by exactly one path — while the decision to
    *require* a guardian at all stayed student-writable through `class_level`.
    A 14-year-old setting 11 made consent never apply again.
    """

    # ⚠️ EVERY VALUE HERE MUST BE VALID FOR ITS COLUMN, or the test measures the
    #    wrong thing. `board = 'FBISE'` was tried first and failed with
    #    `invalid input value for enum board_code` — an invalid literal is
    #    rejected while the statement is being analysed, BEFORE the column
    #    privilege is checked, so a typo silently turns an authorization test
    #    into a spelling test that passes for the wrong reason. `board_code` is
    #    (PCTB, STBB) and the fixture uses PCTB, so STBB is the real probe.
    @pytest.mark.parametrize(
        ("column", "value", "why"),
        [
            ("class_level", "11", "escape the parental-consent gate"),
            ("board", "'STBB'", "reinterpret every progress record ever written"),
            ("student_group", "'pre_medical'", "same, for the elective scope"),
        ],
    )
    def test_a_student_cannot_rewrite_their_own(self, db, unique_email, column, value, why):
        user_id = _student(db, unique_email("colgrant"), class_level=9)
        set_current_user_id(db, user_id)

        message = _refused(
            db,
            f"UPDATE student_profile SET {column} = {value} WHERE user_id = :uid",  # noqa: S608
            {"uid": user_id},
        )

        assert "permission denied" in message.lower(), why
        assert column in message

    def test_the_real_escape_shape_is_refused(self, db, unique_email):
        """
        ⚠️ THE TEST THAT ALMOST DID NOT GET WRITTEN, and the one that matters.

        Probing `SET class_level = 11` alone, before the migration, does NOT come
        back as a permission error — it comes back as a CHECK VIOLATION on
        `ck_group_matches_class`, because `science` is not a Class 11 group. It
        would have been easy to read that as "B4 is already mitigated by a
        constraint". It is not.

        The constraint blocks an INCONSISTENT pair, not the escalation. Measured
        before the migration: setting `class_level` and `student_group` together
        succeeded, moving a Class 9 student to Class 11 `pre_medical` — out of
        the parental-consent gate entirely, which is exactly finding **B4**.

        Data validation is not authorization. This asserts the authorization.
        """
        user_id = _student(db, unique_email("colgrant"), class_level=9)
        set_current_user_id(db, user_id)

        message = _refused(
            db,
            "UPDATE student_profile SET class_level = 11, student_group = 'pre_medical' "
            "WHERE user_id = :uid",
            {"uid": user_id},
        )

        assert "permission denied" in message.lower()
        # ...and specifically a COLUMN privilege, not a row-level refusal: the
        # policy would happily allow this, because the row is theirs.
        assert "class_level" in message or "student_group" in message

    def test_a_student_may_change_their_interface_language(self, db, unique_email):
        user_id = _student(db, unique_email("colgrant"))
        set_current_user_id(db, user_id)

        db.execute(
            text("UPDATE student_profile SET language_pref = 'ur' WHERE user_id = :uid"),
            {"uid": user_id},
        )
        db.flush()

        pref = db.execute(
            text("SELECT language_pref FROM student_profile WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar()
        assert str(pref) == "ur"


class TestRegistrationStillWritesWholeRows:
    def test_insert_is_untouched(self, db, unique_email):
        """
        INSERT is a separate privilege from UPDATE and is deliberately still
        table-wide. Registration writes `role`, `status` and `email_verified_at`
        in one statement; narrowing UPDATE must not narrow that.

        `_student` above already exercises it, but asserted explicitly so that a
        future migration revoking INSERT by symmetry fails here with a clear
        reason rather than breaking sign-up.
        """
        user_id = _student(db, unique_email("colgrant"))
        set_current_user_id(db, user_id)

        row = (
            db.execute(text("SELECT role, status FROM app_user WHERE id = :uid"), {"uid": user_id})
            .mappings()
            .one()
        )
        assert (str(row["role"]), str(row["status"])) == ("student", "active")


class TestTheGrantsAreWhereWeThinkTheyAre:
    def test_only_the_intended_columns_carry_their_own_grant(self, db):
        """
        The schema-level assertion, and the one that catches a REVOKE that never
        landed. Before `20260816160000` this returned zero rows for the whole
        schema — finding **B2**.

        ⚠️ THIS TEST CAUGHT A GAP IN MY OWN WORK, which is the argument for
        pinning the whole set rather than only the columns a given migration
        touches. It was written during §2.2, when the answer was two rows. §2.3
        then added `GRANT INSERT (user_id, plan_code) ON subscription` — the
        narrowing that stops a user self-granting an active subscription (B5) —
        and this failed on the next run. Nothing was wrong with the migration;
        the assertion had gone stale, and a test that only checked "app_user and
        student_profile are present" would have said nothing at all.

        THE PRIVILEGE LETTER IS ASSERTED TOO, not just the column name. `w` is
        UPDATE and `a` is INSERT, and the distinction is load-bearing: an
        accidental `GRANT UPDATE` on `subscription.plan_code` would let a user
        move themselves onto a different plan, and a column-name-only assertion
        would pass straight through it.

        IT HAS NOW CAUGHT A FOURTH CHANGE. `20260816200000` moved
        `language_pref` onto `app_user` for FR-A8 (a teacher has no
        `student_profile` row, so no teacher could ever receive Urdu email) and
        granted UPDATE on the new column. This failed on the next run naming
        exactly that column, and was updated only afterwards -- the order
        matters, because an expectation edited in advance of the change it is
        meant to catch has proved nothing.
        """
        rows = db.execute(
            text(
                "SELECT c.relname, a.attname, a.attacl::text "
                "  FROM pg_attribute a "
                "  JOIN pg_class c ON c.oid = a.attrelid "
                "  JOIN pg_namespace n ON n.oid = c.relnamespace "
                " WHERE n.nspname = 'public' AND a.attacl IS NOT NULL "
                " ORDER BY 1, 2"
            )
        ).all()

        # (table, column, privilege) — 'w' = UPDATE, 'a' = INSERT.
        actual = [(r[0], r[1], "UPDATE" if "=w/" in r[2] else "INSERT") for r in rows]

        # ⚠️ ORDERED BY (table, column) — the query says so, and the first
        #    attempt at this list put `auth_token` before `app_user` and failed
        #    on the ordering rather than on the contents. Keep it sorted.
        assert actual == [
            # 20260816160000 (B2, B3, B4) — the only self-editable fields.
            ("app_user", "full_name", "UPDATE"),
            # 20260816200000 (FR-A8) — the stored preference that governs
            # outgoing email, for every role rather than students only.
            ("app_user", "language_pref", "UPDATE"),
            # 20260817120000 (Phase 4) — `revoke_user_tokens` (logout) is the
            # only plain UPDATE against `auth_token` in the application, and it
            # names this column alone. Narrowed when `family_started_at`,
            # `revoked_at` and `revoked_reason` arrived: table-wide UPDATE plus
            # the `WITH CHECK (revoked = true)` policy would have let a caller
            # author their own revocation reason and rewrite the family start,
            # defeating the absolute session cap that migration exists to create.
            ("auth_token", "revoked", "UPDATE"),
            # Kept deliberately: dropping it would leave `student_profile` with
            # no updatable column at all. Nothing READS it any more —
            # `app_user.language_pref` is the source of truth as of
            # 20260816200000 — but the grant is still the thing that proves
            # `board`, `class_level` and `student_group` are not writable.
            ("student_profile", "language_pref", "UPDATE"),
            # 20260816170000 (B5) — INSERT only, so `status` and
            # `current_period_end` cannot be supplied and take their defaults.
            ("subscription", "plan_code", "INSERT"),
            ("subscription", "user_id", "INSERT"),
        ]
