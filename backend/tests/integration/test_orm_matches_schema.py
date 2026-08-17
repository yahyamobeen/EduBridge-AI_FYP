"""
The ORM models describe the applied schema — finding D14.

⚠️ NOTHING ELSE CHECKS THIS, AND NOTHING ELSE CAN. Every statement that actually
runs is SQLAlchemy Core with hand-written `text()`, so a model can describe a
column wrongly for ever and no test notices. That is how `AppUser.email` came to
be declared `Text` against a `citext` column, and `Board.code` `Text` against the
`board_code` enum — while `StudentProfile.board`, three files away, mapped the
same database type correctly.

The cost is not theoretical: the first ORM query written against one of these
inherits a type that disagrees with the database, and the failure arrives far
from the declaration. A model is documentation that the compiler can check, and
it is only worth having if something checks it.

This compares each mapped column's POSTGRES-compiled type against
`information_schema`, live. It is a sweep rather than a list, so a model added
later is covered without anyone remembering to add it here.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from app.models.base import Base

_PG = postgresql.dialect()

# `information_schema.columns.data_type` reports a domain/enum as `USER-DEFINED`
# and names it in `udt_name`, so the comparison uses `udt_name` throughout and
# maps SQLAlchemy's compiled spelling onto it.
_COMPILED_TO_UDT = {
    "TIMESTAMP WITH TIME ZONE": "timestamptz",
    "TIMESTAMP WITHOUT TIME ZONE": "timestamp",
    "TEXT": "text",
    "CITEXT": "citext",
    "BOOLEAN": "bool",
    "INTEGER": "int4",
    "SMALLINT": "int2",
    "BIGINT": "int8",
    "UUID": "uuid",
    "JSONB": "jsonb",
    "DOUBLE PRECISION": "float8",
}


def _expected_udt(column) -> str:
    compiled = column.type.compile(dialect=_PG).upper()
    if compiled in _COMPILED_TO_UDT:
        return _COMPILED_TO_UDT[compiled]
    # A named enum compiles to its own type name, which IS the udt_name.
    return column.type.compile(dialect=_PG).lower()


def _live_types(db, table: str) -> dict[str, str]:
    rows = db.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            " WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    ).all()
    return {r[0]: r[1] for r in rows}


def _mapped_tables():
    return sorted(Base.metadata.tables.values(), key=lambda t: t.name)


class TestEveryMappedColumnMatchesTheAppliedType:
    @pytest.mark.parametrize("table", _mapped_tables(), ids=lambda t: t.name)
    def test_types_agree(self, db, table):
        live = _live_types(db, table.name)
        if not live:
            pytest.skip(f"{table.name} is mapped but not applied")

        mismatches = []
        for column in table.columns:
            actual = live.get(column.name)
            if actual is None:
                mismatches.append(f"{column.name}: mapped but ABSENT from the database")
                continue
            expected = _expected_udt(column)
            if expected != actual:
                mismatches.append(
                    f"{column.name}: model says {expected!r}, database says {actual!r}"
                )

        assert not mismatches, f"{table.name}\n  " + "\n  ".join(mismatches)


class TestTheTwoD14ColumnsSpecifically:
    """
    Named explicitly as well as swept, because these are the two the finding was
    about and a regression on either should say so by name rather than as one
    line inside a table-wide diff.
    """

    def test_app_user_email_is_citext_not_text(self, db):
        assert _live_types(db, "app_user")["email"] == "citext"
        from app.models.identity import AppUser

        assert AppUser.__table__.c.email.type.compile(dialect=_PG).upper() == "CITEXT", (
            "the model calls email case-sensitive while the database does not"
        )

    def test_board_code_is_the_enum_not_text(self, db):
        assert _live_types(db, "board")["code"] == "board_code"
        from app.models.curriculum import Board
        from app.models.identity import StudentProfile

        assert Board.__table__.c.code.type.compile(dialect=_PG) == "board_code"
        # The two models must describe the same database type the same way.
        assert Board.__table__.c.code.type.compile(
            dialect=_PG
        ) == StudentProfile.__table__.c.board.type.compile(dialect=_PG)
