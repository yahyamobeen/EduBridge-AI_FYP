"""
Transactional email HTML templates (KAN-10b).

Three templates for this card: email verification, password reset, and
two-factor OTP. The guardian invite template is stubbed — Mujtaba's card
(KAN-guardian) will complete it.

Templates are deliberately simple HTML. They are functional, not designed —
production email design is a separate concern. Every template receives
pre-built URLs or codes; no template constructs a URL itself.
"""

from __future__ import annotations

from app.core.config import get_settings


def _wrap(title: str, body_html: str) -> str:
    """Minimal HTML wrapper with inline styles for basic email rendering."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 40px auto; padding: 0 20px; color: #1a1a1a;">
{body_html}
<p style="font-size: 12px; color: #888; margin-top: 40px;">
This email was sent by EduBridge AI. If you did not request this, you can safely ignore it.
</p>
</body>
</html>"""


def verification_email(url: str) -> tuple[str, str]:
    """
    Email verification link.

    Returns ``(subject, html_body)``.
    """
    subject = "Verify your EduBridge AI email"
    body = f"""\
<h2>Verify your email</h2>
<p>Click the button below to verify your email address and continue setting up your EduBridge AI account.</p>
<p style="text-align: center; margin: 32px 0;">
  <a href="{url}" style="display: inline-block; background: #1a73e8; color: #fff; text-decoration: none; padding: 12px 32px; border-radius: 6px; font-weight: 600;">
    Verify Email
  </a>
</p>
<p style="font-size: 13px; color: #555;">Or copy this link into your browser:</p>
<p style="font-size: 13px; word-break: break-all; color: #1a73e8;">{url}</p>"""
    return subject, _wrap(subject, body)


def password_reset_email(url: str) -> tuple[str, str]:
    """
    Password reset link.

    Returns ``(subject, html_body)``.
    """
    subject = "Reset your EduBridge AI password"
    body = f"""\
<h2>Reset your password</h2>
<p>We received a request to reset your password. Click the button below to choose a new one.</p>
<p style="text-align: center; margin: 32px 0;">
  <a href="{url}" style="display: inline-block; background: #1a73e8; color: #fff; text-decoration: none; padding: 12px 32px; border-radius: 6px; font-weight: 600;">
    Reset Password
  </a>
</p>
<p style="font-size: 13px; color: #555;">This link expires in 1 hour. If you did not request a reset, ignore this email — your password will not change.</p>"""
    return subject, _wrap(subject, body)


def two_factor_otp_email(code: str, expires_minutes: int = 10) -> tuple[str, str]:
    """
    Two-factor email OTP code.

    Returns ``(subject, html_body)``.
    """
    subject = f"Your EduBridge AI verification code: {code}"
    body = f"""\
<h2>Your verification code</h2>
<p style="text-align: center; margin: 32px 0;">
  <span style="font-size: 36px; font-weight: 700; letter-spacing: 8px; font-family: monospace;">{code}</span>
</p>
<p style="font-size: 13px; color: #555;">This code expires in {expires_minutes} minutes. Do not share it with anyone.</p>"""
    return subject, _wrap(subject, body)


def guardian_invite_email(url: str, student_name: str) -> tuple[str, str]:
    """
    Guardian invite link (STUB — Mujtaba's card will complete this).

    Returns ``(subject, html_body)``.
    """
    subject = f"{student_name} invited you to join EduBridge AI as a guardian"
    body = f"""\
<h2>Guardian invitation</h2>
<p><strong>{student_name}</strong> has invited you to link your account as their guardian on EduBridge AI.</p>
<p style="text-align: center; margin: 32px 0;">
  <a href="{url}" style="display: inline-block; background: #1a73e8; color: #fff; text-decoration: none; padding: 12px 32px; border-radius: 6px; font-weight: 600;">
    Accept Invitation
  </a>
</p>
<p style="font-size: 13px; color: #555;">You will need to create an EduBridge AI account (or sign in) before you can confirm the link.</p>"""
    return subject, _wrap(subject, body)


def build_verification_url(token: str) -> str:
    """Build the full verification URL from a token."""
    settings = get_settings()
    return f"{settings.app_base_url}/en/verify-email?token={token}"


def build_password_reset_url(token: str) -> str:
    """Build the full password reset URL from a token."""
    settings = get_settings()
    return f"{settings.app_base_url}/en/reset-password?token={token}"
