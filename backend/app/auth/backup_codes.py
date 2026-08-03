"""
Backup code generation and verification (tdd.md §6.9, SEC-14).

10 codes per enrolment, 8 alphanumeric characters each, argon2id-hashed,
single-use. The plaintext exists only in the one response that issues them —
the database stores only hashes.

Codes are compared CASE-INSENSITIVELY by uppercasing both sides before hashing
and before verification. This is deliberate: printed codes may be re-typed
with different casing, and a case-sensitive comparison would silently reject
a valid code.

The alphabet excludes visually ambiguous characters (0/O and 1/I) so printed
codes are unambiguous on paper.
"""

from __future__ import annotations

import secrets

from app.auth.security import hash_password, verify_password

# Excludes 0/O and 1/I to prevent visual ambiguity on printed codes.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate ``count`` random 8-character codes."""
    return ["".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH)) for _ in range(count)]


def hash_backup_code(code: str) -> str:
    """
    Hash a code for storage. Case-insensitive: uppercased before hashing so
    that ``AbCd1234`` and ``ABCD1234`` produce the same hash.
    """
    return hash_password(code.upper())


def verify_backup_code(code: str, code_hash: str) -> bool:
    """
    Verify a submitted code against a stored hash. Case-insensitive:
    uppercases the input before comparison.
    """
    return verify_password(code.upper(), code_hash)
