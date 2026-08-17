"""
Transactional email HTML templates (KAN-10b).

Four templates: email verification, password reset, two-factor OTP, and the
guardian invite. Templates are deliberately simple HTML — functional, not
designed. Every template receives pre-built URLs or codes; no template
constructs a URL itself.

LOCALE. Every template and every link takes a locale, and the URL carries it
(`/{locale}/verify-email?...`) so the link opens the page in the language the
recipient reads. This was hardcoded to `/en/` in a product whose premise is
Urdu-first, which would have mailed English links to Urdu accounts.

The COPY is still English for all three locales, on purpose. `ur` and `ur-Latn`
resolve to the English body until a human writes them: machine-translating the
one message a parent receives about their child's account would undercut the
premise more than an English fallback does, and the frontend's 390 message keys
are in the same position. When the copy arrives it drops into `_COPY` — no
call site changes. The URL locale is correct TODAY either way, so the link
still lands on an Urdu page.
"""

from __future__ import annotations

import html
import re

from app.core.config import get_settings

# BCP-47 as the web uses it. `language_code` in the database is en | ur |
# roman_ur; `roman_ur` is not a valid BCP-47 tag, so the web spells it ur-Latn
# (tdd.md §3.10) and this is the single place that translation happens.
_DB_TO_WEB_LOCALE = {"en": "en", "ur": "ur", "roman_ur": "ur-Latn"}
_DEFAULT_LOCALE = "en"

_RTL_LOCALES = frozenset({"ur"})


def web_locale(language_pref: str | None) -> str:
    """
    Map a stored `language_code` to the locale segment the frontend routes on.

    ⚠️ `None` NO LONGER MEANS "not a student". Until `20260816200000`
    `language_pref` lived on `student_profile`, so every teacher, parent and
    administrator arrived here as `None` and was silently given English — which
    made FR-A8's "the stored preference governs outgoing email" unmeetable for
    three roles out of four. The column is on `app_user` now and is
    `NOT NULL DEFAULT 'en'`, so `None` means the caller has no user row at all.

    The fallback stays for that case and for an unrecognised value: English
    rather than a guess.
    """
    if language_pref is None:
        return _DEFAULT_LOCALE
    return _DB_TO_WEB_LOCALE.get(str(language_pref), _DEFAULT_LOCALE)


# ---------------------------------------------------------------------------
# Finding C3 — user-supplied text in a template is HTML until it is escaped.
#
# Exactly one interpolation in this module carries user input: `student_name` in
# `guardian_invite_email`, which is `app_user.full_name` — bounded in LENGTH and
# unrestricted in CHARACTERS. Everything else here is a generated code, an
# opaque token, a validated locale or a literal.
#
# It was latent while the guardian invite had no caller. Wiring the invite
# (KAN-21, finding A10) makes it live, and this branch's `PATCH /auth/me` lets a
# student rewrite their own name at any time — so the payload is not merely
# attacker-supplied, it is attacker-EDITABLE, and it is delivered to a parent
# from a verified sending domain. That is a phishing anchor with the project's
# own reputation behind it.
# ---------------------------------------------------------------------------


def _text(value: str) -> str:
    """
    Escape user-supplied text for HTML **text content**.

    ⚠️ `quote=False` ON PURPOSE. Everything escaped here lands between tags —
    `<strong>{name}</strong>`, `<title>{title}</title>` — never inside an
    attribute, so quotes need no escaping. The default `quote=True` would render
    a real parent's *O'Brien* as `O&#x27;Brien`. Over-escaping is its own defect:
    it teaches readers the escaping is cosmetic and invites its removal.

    ⚠️ If any caller ever puts this INTO an attribute, this is the wrong helper.
    """
    return html.escape(value, quote=False)


def _header_safe(value: str) -> str:
    """
    Flatten a value going into a mail HEADER (the subject line).

    A different defect from the HTML one, and `html.escape` does nothing about
    it: a CR or LF in a header ends it and begins another, which is how a name
    becomes an extra `Bcc:`. `full_name` is a free-text field with no character
    restriction, so it can carry both.

    Whitespace is collapsed rather than only stripped, because a tab or a run of
    newlines in a subject is a rendering mess even when it is not an injection.
    """
    return re.sub(r"\s+", " ", value).strip()


def _wrap(title: str, body_html: str, locale: str) -> str:
    """
    Minimal HTML wrapper with inline styles for basic email rendering.

    ⚠️ `title` IS ESCAPED HERE, not by callers. Every template passes its subject
    as the title, and a subject can carry user text — so escaping in the one
    place the title reaches HTML makes every present and future template safe by
    default, rather than making each author remember. `body_html` is NOT escaped:
    it is composed by this module and is HTML by contract.
    """
    title = _text(title)
    direction = "rtl" if locale in _RTL_LOCALES else "ltr"
    return f"""\
<!DOCTYPE html>
<html lang="{locale}" dir="{direction}">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 40px auto; padding: 0 20px; color: #1a1a1a;" dir="{direction}">
{body_html}
<p style="font-size: 12px; color: #888; margin-top: 40px;">
This email was sent by EduBridge AI. If you did not request this, you can safely ignore it.
</p>
</body>
</html>"""


def _button(url: str, label: str) -> str:
    return f"""\
<p style="text-align: center; margin: 32px 0;">
  <a href="{url}" style="display: inline-block; background: #1a73e8; color: #fff; text-decoration: none; padding: 12px 32px; border-radius: 6px; font-weight: 600;">
    {label}
  </a>
</p>"""


def verification_email(url: str, locale: str = _DEFAULT_LOCALE) -> tuple[str, str]:
    """Email verification link. Returns ``(subject, html_body)``."""
    subject = "Verify your EduBridge AI email"
    body = f"""\
<h2>Verify your email</h2>
<p>Click the button below to verify your email address and continue setting up your EduBridge AI account.</p>
{_button(url, "Verify Email")}
<p style="font-size: 13px; color: #555;">Or copy this link into your browser:</p>
<p style="font-size: 13px; word-break: break-all; color: #1a73e8;">{url}</p>"""
    return subject, _wrap(subject, body, locale)


def password_reset_email(url: str, locale: str = _DEFAULT_LOCALE) -> tuple[str, str]:
    """Password reset link. Returns ``(subject, html_body)``."""
    subject = "Reset your EduBridge AI password"
    body = f"""\
<h2>Reset your password</h2>
<p>We received a request to reset your password. Click the button below to choose a new one.</p>
{_button(url, "Reset Password")}
<p style="font-size: 13px; color: #555;">This link expires in 1 hour. If you did not request a reset, ignore this email — your password will not change.</p>"""
    return subject, _wrap(subject, body, locale)


def two_factor_otp_email(
    code: str, expires_minutes: int = 10, locale: str = _DEFAULT_LOCALE
) -> tuple[str, str]:
    """
    Two-factor email OTP code.

    The code is NOT in the subject line. Subjects are shown on lock screens and
    in notification banners, so putting a one-time code there hands it to anyone
    who can see the phone — which on the shared devices `prd.md` §3.1 describes
    is the likely case.
    """
    subject = "Your EduBridge AI verification code"
    body = f"""\
<h2>Your verification code</h2>
<p style="text-align: center; margin: 32px 0;">
  <span style="font-size: 36px; font-weight: 700; letter-spacing: 8px; font-family: monospace;">{code}</span>
</p>
<p style="font-size: 13px; color: #555;">This code expires in {expires_minutes} minutes. Do not share it with anyone.</p>"""
    return subject, _wrap(subject, body, locale)


def guardian_invite_email(
    url: str, student_name: str, locale: str = _DEFAULT_LOCALE
) -> tuple[str, str]:
    """
    Guardian invite link. Wired by `service.guardian_invite` (finding A10).

    ⚠️ `student_name` IS THE ONLY USER-CONTROLLED VALUE IN THIS MODULE, and it
    reaches THREE places with two different escaping rules — finding C3.

    It is `app_user.full_name`: length-bounded, character-unrestricted, and
    editable at will through `PATCH /auth/me`. The recipient is a parent, and the
    sender is a domain this project has verified, so unescaped markup here is a
    phishing link with the platform's own reputation attached.

    * body — HTML text content, so `_text`.
    * `<title>` — also HTML, escaped inside `_wrap`, which is why the raw subject
      is safe to pass along.
    * subject header — NOT HTML. Escaping it would show a real parent
      `&lt;` where their child's name should be, so it gets `_header_safe`
      instead, which removes the CR/LF that would actually let a name forge a
      header.
    """
    display_name = _text(student_name)
    subject = f"{_header_safe(student_name)} invited you to join EduBridge AI as a guardian"
    body = f"""\
<h2>Guardian invitation</h2>
<p><strong>{display_name}</strong> has invited you to link your account as their guardian on EduBridge AI.</p>
{_button(url, "Accept Invitation")}
<p style="font-size: 13px; color: #555;">You will need to create an EduBridge AI account (or sign in) before you can confirm the link.</p>"""
    return subject, _wrap(subject, body, locale)


def build_verification_url(token: str, locale: str = _DEFAULT_LOCALE) -> str:
    """Full verification URL, in the recipient's locale."""
    return f"{get_settings().app_base_url}/{locale}/verify-email?token={token}"


def build_password_reset_url(token: str, locale: str = _DEFAULT_LOCALE) -> str:
    """Full password reset URL, in the recipient's locale."""
    return f"{get_settings().app_base_url}/{locale}/reset-password?token={token}"


def build_guardian_invite_url(token: str, locale: str = _DEFAULT_LOCALE) -> str:
    """Full guardian confirmation URL, in the recipient's locale."""
    return f"{get_settings().app_base_url}/{locale}/guardian/confirm?token={token}"
