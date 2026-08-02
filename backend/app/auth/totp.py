"""
TOTP secret generation, QR code rendering, and code verification.

Isolated from service.py so it can be unit-tested without a database
connection or a live Supabase project. `pyotp` handles RFC 6238 TOTP;
`qrcode` produces a valid SVG with no <script> injection surface — the
frontend renders it as a base64 data-URI <img>, never as HTML (tdd.md §6.11).

The encryption helpers use Fernet (AES-128-CBC + HMAC-SHA256 from the
`cryptography` library). The key lives in application config, not in the
database, so a database dump alone does not yield usable secrets (tdd.md §6.9).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from functools import lru_cache

import pyotp
import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet

from app.core.config import get_settings


def generate_totp_secret() -> str:
    """Base32-encoded secret suitable for TOTP enrolment."""
    return pyotp.random_base32()


def build_otpauth_uri(secret: str, email: str) -> str:
    """``otpauth://`` URI that authenticator apps scan from the QR code."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name="EduBridge AI")


def generate_qr_svg(otpauth_uri: str) -> str:
    """
    A valid QR code as an SVG string.

    Uses ``SvgPathImage`` which produces only ``<rect>`` and ``<path>``
    elements — no ``<script>`` tags, no external references. The frontend
    renders this as a base64 ``data:`` URI inside an ``<img>``, where SVG is
    processed in a restricted mode that runs no scripts (tdd.md §6.11).
    """
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(otpauth_uri, image_factory=factory)
    buffer = io.BytesIO()
    img.save(buffer)
    return buffer.getvalue().decode("utf-8")


def verify_totp_code(
    secret: str,
    code: str,
    *,
    last_counter: int | None = None,
) -> int | None:
    """
    Verify a 6-digit TOTP code with ±1 window tolerance (tdd.md §6.9).

    Returns the time-step counter if valid — used to populate
    ``last_used_counter`` as a replay guard. Returns ``None`` if the code is
    invalid or if its counter is at or below ``last_counter`` (already consumed
    within its window).
    """
    totp = pyotp.TOTP(secret)
    now = datetime.now(UTC)

    for offset in (-1, 0, 1):
        # Compute the time for this offset, then get the counter for that time.
        adjusted_time = now.timestamp() + (offset * totp.interval)
        if totp.verify(code, for_time=adjusted_time):
            counter = int(adjusted_time) // totp.interval
            if last_counter is not None and counter <= last_counter:
                # Replay guard: this code was already accepted.
                continue
            return counter

    return None


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """
    Built on first use, not at import — same pattern as ``_password_hasher``
    in ``security.py``. Reading settings at module scope would make importing
    this module require a complete ``.env``, which broke unit tests that never
    touch encryption.
    """
    settings = get_settings()
    return Fernet(settings.totp_encryption_key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    """
    AES-encrypt a TOTP secret for storage in
    ``two_factor_enrollment.totp_secret_encrypted``.
    """
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    """
    Decrypt a TOTP secret. Raises ``cryptography.fernet.InvalidToken`` on
    tampering or wrong key — the caller should treat that as a configuration
    error, not a user-facing failure.
    """
    return _fernet().decrypt(ciphertext).decode()
