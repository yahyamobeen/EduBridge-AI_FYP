"""
Email delivery seam (KAN-10b).

The protocol is trivial; swapping providers means adding one class that
implements ``EmailSender``. No route or service code changes.

Two implementations ship:

* ``LoggingEmailSender`` — writes structured metadata to the Python logger.
  Development and CI. The token is in the HTML body, which is NOT logged
  (only ``to``, ``subject``, and ``body_length`` are), so secrets do not
  leak into log aggregators.

* ``ResendEmailSender`` — sends via the Resend REST API. Production.

The factory picks based on ``settings.email_provider``.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger("edubridge.email")


class EmailSender(Protocol):
    """Minimal interface for transactional email delivery."""

    def send(self, to: str, subject: str, html_body: str) -> None: ...


class LoggingEmailSender:
    """
    Development: log every email's metadata. The token is in the HTML body,
    which is deliberately NOT logged — only the recipient, subject, and body
    length are recorded, so secrets do not leak into log aggregators.
    """

    def send(self, to: str, subject: str, html_body: str) -> None:
        logger.info(
            "EMAIL  to=%s  subject=%r  body_length=%d",
            to,
            subject,
            len(html_body),
        )


class ResendEmailSender:
    """Production: send via the Resend API (https://resend.com)."""

    def send(self, to: str, subject: str, html_body: str) -> None:
        import resend

        settings = get_settings()
        resend.api_key = settings.resend_api_key
        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html_body,
            }
        )
        logger.info("EMAIL SENT  to=%s  subject=%r", to, subject)


def get_email_sender() -> EmailSender:
    """
    Factory. Returns ``ResendEmailSender`` when ``EMAIL_PROVIDER=resend``,
    ``LoggingEmailSender`` otherwise. The default (``logging``) is safe for
    development, CI, and any environment without a configured API key.
    """
    settings = get_settings()
    if settings.email_provider == "resend":
        return ResendEmailSender()
    return LoggingEmailSender()
