"""
Schema-wide Row-Level Security coverage — finding B19.

WHY THIS FILE EXISTS. Protection and permission were established by two
mechanisms with different lifetimes, and that asymmetry is the finding:

  - GRANTS ARE FORWARD-LOOKING. `ALTER DEFAULT PRIVILEGES` means every table
    created from now on is granted to `app_backend` automatically.
  - PROTECTION WAS A ONE-SHOT LOOP. `20260801120100:126-137` iterated the tables
    that existed at that moment and enabled row-level security on them.

So a table added tomorrow is **readable and writable by the application by
default, and protected only if somebody remembers**. It has already been missed
three times: the two default partitions (finding **F1**, reconciled by
`20260816130000`), and `two_factor_status_v`, which the loop could not see at all
because it reads `pg_tables` and a view is not a table (finding **B1**, closed by
`20260816150000`).

Every other test in this suite asserts a behaviour. These assert a **property of
the schema**, which is the only shape that catches the table nobody has written a
test for yet — because it does not need to know the table exists.

⚠️ THE EXEMPTION LISTS BELOW ARE THE POINT. A new table with no policy fails
   this suite, and the only ways to make it pass are to give it a policy or to
   add it here with a reason. Both are decisions; forgetting is not.
"""

import pytest
from sqlalchemy import text

# Tables that are deliberately deny-all: row-level security is enabled and
# FORCED, and there is NO policy, so nothing matches and every row is refused to
# `app_backend`. That is the strongest possible setting, not a gap.
NO_POLICY_BY_DESIGN = {
    # Answer keys. `question_key` is reachable ONLY through the grading path,
    # which runs inside SECURITY DEFINER functions as the owner. A policy here
    # would be strictly weaker than none: it would describe a way in.
    "question_key",
}

# Views cannot carry row-level security at all — policies attach to tables. A
# view is safe only if it runs as its CALLER, so the policies on the tables
# underneath apply. Anything listed here is asserting the opposite and needs a
# written reason; the list is empty on purpose.
VIEWS_WITHOUT_SECURITY_INVOKER: set[str] = set()

RELATIONS = text("""
    SELECT c.relname,
           c.relkind,
           c.relrowsecurity      AS enabled,
           c.relforcerowsecurity AS forced,
           (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies,
           coalesce(array_to_string(c.reloptions, ','), '') AS options
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
     ORDER BY c.relname
""")


@pytest.fixture
def relations(db_connection):
    # Function-scoped, matching `db_connection`. Re-reading the catalogue per
    # test costs a few milliseconds and keeps the transaction boundary the rest
    # of the suite relies on.
    return db_connection.execute(RELATIONS).mappings().all()


def _tables(relations):
    return [r for r in relations if r["relkind"] in ("r", "p")]


def _views(relations):
    return [r for r in relations if r["relkind"] in ("v", "m")]


class TestEveryTableIsProtected:
    def test_row_level_security_is_enabled_everywhere(self, relations):
        missing = [r["relname"] for r in _tables(relations) if not r["enabled"]]

        assert missing == [], (
            "row-level security is OFF on these tables, and `app_backend` holds a "
            f"grant on them by default: {missing}"
        )

    def test_row_level_security_is_forced_everywhere(self, relations):
        """
        ENABLED is not enough. Without FORCE, the table OWNER bypasses every
        policy — and `app.*` SECURITY DEFINER functions execute as the owner, so
        an unforced table is unprotected on exactly the paths that run
        privileged.
        """
        missing = [r["relname"] for r in _tables(relations) if r["enabled"] and not r["forced"]]

        assert missing == [], f"row-level security is enabled but NOT FORCED on: {missing}"

    def test_every_table_has_a_policy_or_a_recorded_exemption(self, relations):
        undecided = [
            r["relname"]
            for r in _tables(relations)
            if r["policies"] == 0 and r["relname"] not in NO_POLICY_BY_DESIGN
        ]

        assert undecided == [], (
            "these tables have NO policy and are not in NO_POLICY_BY_DESIGN. Either "
            "give them a policy, or add them to that set with the reason — a table "
            f"with no policy is deny-all, which may be right, but must be chosen: {undecided}"
        )

    def test_the_exemption_list_has_not_gone_stale(self, relations):
        """
        The mirror of the test above. If an exempt table later gains a policy,
        the exemption is a lie and the next reader will trust it.
        """
        by_name = {r["relname"]: r for r in _tables(relations)}
        wrong = [
            name
            for name in NO_POLICY_BY_DESIGN
            if name in by_name and by_name[name]["policies"] > 0
        ]

        assert wrong == [], f"these are listed as deny-all by design but now HAVE policies: {wrong}"

    def test_the_exemption_list_names_only_real_tables(self, relations):
        names = {r["relname"] for r in _tables(relations)}
        ghosts = NO_POLICY_BY_DESIGN - names

        assert ghosts == set(), f"NO_POLICY_BY_DESIGN names tables that no longer exist: {ghosts}"


class TestEveryViewRunsAsItsCaller:
    def test_views_have_security_invoker(self, relations):
        """
        Finding **B1**, generalised so it cannot happen twice.

        `two_factor_status_v` ran as its owner, so the owner-scoped policies on
        `two_factor_enrollment` and `two_factor_backup_code` were skipped
        entirely — measured before the fix: a caller bound to a user who owned
        nothing read **7 of 7** accounts through the view while the table itself
        correctly returned 0. `GRANT … ON ALL TABLES` includes views, and the
        enable-and-force loop reads `pg_tables`, which does not list them, so
        nothing in the original design could have caught it.
        """
        leaking = [
            r["relname"]
            for r in _views(relations)
            if "security_invoker=true" not in r["options"]
            and r["relname"] not in VIEWS_WITHOUT_SECURITY_INVOKER
        ]

        assert leaking == [], (
            "these views execute as their OWNER, so the policies on the tables "
            "underneath do not apply and `app_backend` reads every row: "
            f"{leaking}. Add `security_invoker = true`, or drop the view."
        )

    def test_there_is_at_least_one_view_to_check(self, relations):
        """A guard on the guard: an empty sweep passes vacuously."""
        assert len(_views(relations)) >= 1


class TestTheSweepIsActuallySeeingTheSchema:
    def test_it_found_the_expected_scale(self, relations):
        """
        The whole file passes trivially if the query returns nothing — a wrong
        schema name, a permissions change, a catalogue rename. Pinned loosely, so
        it catches "zero rows" without failing every time a table is added.
        """
        assert len(_tables(relations)) > 30, (
            f"only {len(_tables(relations))} tables found in `public`; the sweep is "
            "not seeing the schema"
        )
