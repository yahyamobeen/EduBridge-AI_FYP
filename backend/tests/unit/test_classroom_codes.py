"""
Join codes — the Python half of the invariant the database enforces with
`ck_join_code_format` (`^[A-HJ-NP-Z2-9]{8}$`, migration 20261004120000). A code
this module produced that the CHECK refused would surface as a 500 on classroom
creation, so the two are pinned to each other here.
"""

import re

from app.classroom.codes import ALPHABET, CODE_LENGTH, generate_join_code

# Copied from the migration on purpose: if either side changes alone, this fails.
DATABASE_FORMAT = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


class TestJoinCodes:
    def test_alphabet_is_the_32_unambiguous_symbols(self):
        assert len(ALPHABET) == 32
        assert len(set(ALPHABET)) == 32
        assert not set("IO01") & set(ALPHABET)

    def test_every_code_satisfies_the_database_check(self):
        for _ in range(2000):
            code = generate_join_code()
            assert len(code) == CODE_LENGTH
            assert DATABASE_FORMAT.fullmatch(code), code

    def test_every_alphabet_symbol_is_accepted_by_the_database_check(self):
        assert all(DATABASE_FORMAT.fullmatch(symbol * CODE_LENGTH) for symbol in ALPHABET)

    def test_codes_do_not_repeat(self):
        # 2^40 space: a repeat in 10 000 draws would mean the source is not random.
        codes = {generate_join_code() for _ in range(10_000)}
        assert len(codes) == 10_000
