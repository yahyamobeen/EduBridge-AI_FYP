"""
Unit tests for TOTP utilities.

Tests cover:
- Secret generation (base32, 32 chars)
- otpauth URI format
- QR SVG validity (no <script> tags)
- Fernet encrypt/decrypt roundtrip
- Tampered ciphertext rejection
- TOTP code verification with ±1 window and replay guard
"""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from cryptography.fernet import InvalidToken

from app.auth.totp import (
    build_otpauth_uri,
    decrypt_secret,
    encrypt_secret,
    generate_qr_svg,
    generate_totp_secret,
    verify_totp_code,
)

# A published RFC-6238 example secret. Hardcoded on purpose: these tests
# assert TOTP arithmetic, which needs a fixed input.
TEST_SECRET = "JBSWY3DPEHPK3PXP"  # noqa: S105 -- test vector, not a credential


class TestGenerateTotpSecret:
    def test_is_base32(self):
        secret = generate_totp_secret()
        # base32 alphabet: A-Z, 2-7
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)

    def test_is_32_chars(self):
        secret = generate_totp_secret()
        assert len(secret) == 32

    def test_is_unique(self):
        s1 = generate_totp_secret()
        s2 = generate_totp_secret()
        assert s1 != s2


class TestBuildOtpauthUri:
    def test_starts_with_otpauth(self):
        secret = TEST_SECRET
        uri = build_otpauth_uri(secret, "test@example.com")
        assert uri.startswith("otpauth://totp/")

    def test_contains_secret(self):
        secret = TEST_SECRET
        uri = build_otpauth_uri(secret, "test@example.com")
        assert secret in uri

    def test_contains_issuer(self):
        secret = TEST_SECRET
        uri = build_otpauth_uri(secret, "test@example.com")
        assert "EduBridge%20AI" in uri or "EduBridge AI" in uri

    def test_contains_email(self):
        secret = TEST_SECRET
        uri = build_otpauth_uri(secret, "test@example.com")
        assert "test@example.com" in uri or "test%40example.com" in uri


class TestGenerateQrSvg:
    def test_starts_with_svg(self):
        uri = "otpauth://totp/EduBridge%20AI:test@example.com?secret=JBSWY3DPEHPK3PXP&issuer=EduBridge%20AI"
        svg = generate_qr_svg(uri)
        # QR library may include XML declaration before <svg>
        assert "<svg" in svg

    def test_ends_with_svg(self):
        uri = "otpauth://totp/EduBridge%20AI:test@example.com?secret=JBSWY3DPEHPK3PXP&issuer=EduBridge%20AI"
        svg = generate_qr_svg(uri)
        assert svg.rstrip().endswith("</svg>")

    def test_no_script_tags(self):
        uri = "otpauth://totp/EduBridge%20AI:test@example.com?secret=JBSWY3DPEHPK3PXP&issuer=EduBridge%20AI"
        svg = generate_qr_svg(uri)
        assert "<script" not in svg.lower()
        assert "</script>" not in svg.lower()


class TestFernetEncryption:
    def test_roundtrip(self):
        plaintext = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_secret(plaintext)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == plaintext

    def test_encrypted_is_bytes(self):
        plaintext = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_secret(plaintext)
        assert isinstance(encrypted, bytes)

    def test_encrypted_differs_from_plaintext(self):
        plaintext = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_secret(plaintext)
        assert encrypted != plaintext.encode()

    def test_tampered_ciphertext_fails(self):
        plaintext = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_secret(plaintext)
        # Tamper with a byte in the middle
        tampered = encrypted[:10] + bytes([encrypted[10] ^ 0xFF]) + encrypted[11:]
        with pytest.raises(InvalidToken):
            decrypt_secret(tampered)

    def test_different_ciphertexts_for_same_plaintext(self):
        plaintext = "JBSWY3DPEHPK3PXP"
        e1 = encrypt_secret(plaintext)
        e2 = encrypt_secret(plaintext)
        # Fernet includes a timestamp, so encryptions should differ
        assert e1 != e2


class TestVerifyTotpCode:
    def test_valid_code(self):
        secret = TEST_SECRET
        totp = pyotp.TOTP(secret)
        code = totp.now()
        counter = verify_totp_code(secret, code)
        assert counter is not None
        assert isinstance(counter, int)

    def test_wrong_code(self):
        """
        A code that is none of the three the guard accepts.

        The previous version passed "000000" and then asserted NOTHING, with a
        comment explaining that it could not tell whether the result was right.
        A pinned clock makes it decidable: compute every code the +/-1 window
        would accept, then submit one that is not among them.
        """
        anchor = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
        totp = pyotp.TOTP(TEST_SECRET)
        accepted = {totp.at(anchor.timestamp() + offset * totp.interval) for offset in (-1, 0, 1)}
        wrong = next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in accepted)

        assert verify_totp_code(TEST_SECRET, wrong, now=anchor) is None

    def test_replay_guard(self):
        secret = TEST_SECRET
        totp = pyotp.TOTP(secret)
        code = totp.now()

        # First verification should succeed
        counter1 = verify_totp_code(secret, code)
        assert counter1 is not None

        # Second verification with the same counter should fail
        counter2 = verify_totp_code(secret, code, last_counter=counter1)
        assert counter2 is None

    def test_a_code_from_the_previous_step_is_still_accepted(self):
        """
        The +/-1 tolerance, asserted rather than hoped for. The old test built
        codes for the previous and next steps and then checked only the CURRENT
        one -- which `test_valid_code` already covers -- because without a
        pinned clock the other two could not be relied on.
        """
        anchor = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
        totp = pyotp.TOTP(TEST_SECRET)

        previous = totp.at(anchor.timestamp() - totp.interval)
        upcoming = totp.at(anchor.timestamp() + totp.interval)

        assert verify_totp_code(TEST_SECRET, previous, now=anchor) is not None
        assert verify_totp_code(TEST_SECRET, upcoming, now=anchor) is not None

    def test_a_code_two_steps_old_is_rejected(self):
        """The window is +/-1, not "recently"."""
        anchor = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
        totp = pyotp.TOTP(TEST_SECRET)
        stale = totp.at(anchor.timestamp() - 2 * totp.interval)

        assert verify_totp_code(TEST_SECRET, stale, now=anchor) is None

    def test_the_replay_guard_still_admits_a_later_step(self):
        """
        Fail-closed must not mean fail-stuck: consuming step N blocks N, not
        everything after it.
        """
        anchor = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
        totp = pyotp.TOTP(TEST_SECRET)

        used = verify_totp_code(TEST_SECRET, totp.at(anchor.timestamp()), now=anchor)
        assert used is not None

        later = anchor + timedelta(seconds=totp.interval)
        assert (
            verify_totp_code(TEST_SECRET, totp.at(later.timestamp()), last_counter=used, now=later)
            is not None
        )
