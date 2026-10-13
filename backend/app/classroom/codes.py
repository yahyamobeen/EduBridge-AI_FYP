"""
Classroom join codes.

The Python half of a two-part invariant. Since 20261004120000 the database will
only accept a code matching `ck_join_code_format` (`^[A-HJ-NP-Z2-9]{8}$`), and
only through `app.rotate_join_code`; this module is what mints one. Entropy
lives here because the house rule is that credentials are generated in Python
with `secrets`, never in SQL.

No database or settings imports, so it is testable without a connection string.
"""

import secrets

# 32 symbols: A-H, J-N, P-Z and 2-9. No I, O, 0 or 1 — the four characters a
# student most often misreads when copying a code off a classroom board.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# 32**8 = 2**40 codes. With CLASSROOM_JOIN_LIMIT at 10 attempts per 5 minutes
# per account, guessing a live code is not a strategy.
CODE_LENGTH = 8


def generate_join_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
