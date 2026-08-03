"""
Unit tests for backup code utilities.

Tests cover:
- Generation of 10 unique 8-character codes
- Unambiguous alphabet (no 0, O, 1, I)
- Argon2id hashing
- Case-insensitive verification
"""

from app.auth.backup_codes import (
    _ALPHABET,
    generate_backup_codes,
    hash_backup_code,
    verify_backup_code,
)


class TestGenerateBackupCodes:
    def test_generates_10_codes(self):
        codes = generate_backup_codes(10)
        assert len(codes) == 10

    def test_all_unique(self):
        codes = generate_backup_codes(10)
        assert len(set(codes)) == 10

    def test_each_is_8_chars(self):
        codes = generate_backup_codes(10)
        for code in codes:
            assert len(code) == 8

    def test_uses_unambiguous_alphabet(self):
        codes = generate_backup_codes(100)  # Generate more to increase coverage
        for code in codes:
            for char in code:
                assert char in _ALPHABET
                # Explicitly check for excluded characters
                assert char not in "0O1I"


class TestHashBackupCode:
    def test_is_argon2id(self):
        code = "ABCDEF12"
        hashed = hash_backup_code(code)
        assert hashed.startswith("$argon2id$")

    def test_different_hashes_for_same_code(self):
        """Argon2id uses random salts, so same code produces different hashes."""
        code = "ABCDEF12"
        h1 = hash_backup_code(code)
        h2 = hash_backup_code(code)
        # Hashes should be different (different salts)
        assert h1 != h2
        # But both should verify the same code
        assert verify_backup_code(code, h1) is True
        assert verify_backup_code(code, h2) is True

    def test_case_insensitive_hashing(self):
        """Different cases should all verify against any hash of the uppercase version."""
        code1 = "ABCDEF12"
        code2 = "abcdef12"
        code3 = "AbCdEf12"
        h1 = hash_backup_code(code1)
        # All variations should verify against the same hash
        assert verify_backup_code(code1, h1) is True
        assert verify_backup_code(code2, h1) is True
        assert verify_backup_code(code3, h1) is True


class TestVerifyBackupCode:
    def test_correct_code_verifies(self):
        code = "ABCDEF12"
        hashed = hash_backup_code(code)
        assert verify_backup_code(code, hashed) is True

    def test_wrong_code_fails(self):
        code = "ABCDEF12"
        hashed = hash_backup_code(code)
        assert verify_backup_code("WRONGCODE", hashed) is False

    def test_case_insensitive_verification(self):
        code = "ABCDEF12"
        hashed = hash_backup_code(code)
        assert verify_backup_code("abcdef12", hashed) is True
        assert verify_backup_code("AbCdEf12", hashed) is True
        assert verify_backup_code("ABCDEF12", hashed) is True

    def test_empty_code_fails(self):
        code = "ABCDEF12"
        hashed = hash_backup_code(code)
        assert verify_backup_code("", hashed) is False
