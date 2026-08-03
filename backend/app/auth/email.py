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

import atexit
import logging
from concurrent.futures import Future, ThreadPoolExecutor
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
    """
    Production: send via the Resend API (https://resend.com).

    The SDK is an OPTIONAL extra (`uv sync --extra email`), because no provider
    is settled yet and a hard dependency on one is a decision this card was told
    not to make on its own. Imported inside `send` so an environment that never
    mails never needs it installed.
    """

    def send(self, to: str, subject: str, html_body: str) -> None:
        try:
            import resend
        except ImportError as exc:  # pragma: no cover -- configuration error
            raise RuntimeError(
                "EMAIL_PROVIDER=resend but the resend SDK is not installed. "
                "Run `uv sync --extra email`, or set EMAIL_PROVIDER=logging."
            ) from exc

        settings = get_settings()
        if not settings.resend_api_key:
            raise RuntimeError("EMAIL_PROVIDER=resend but RESEND_API_KEY is empty.")
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


# ---------------------------------------------------------------------------
# Out-of-band dispatch.
#
# WHY THIS EXISTS: `password/forgot` and `email/resend` must answer identically
# for a known and an unknown address — body, status AND TIMING (tdd.md §6.11).
# A dummy argon2 verify was equalising the wrong thing: the known-address branch
# went on to make a SYNCHRONOUS HTTP request to the mail provider, hundreds of
# milliseconds that the unknown-address branch never paid. Anyone with a
# stopwatch could enumerate the user table.
#
# Sending off the request thread removes the dominant term. What remains is one
# INSERT (single-digit milliseconds) against an argon2 verify (deliberately ~100)
# — inside the noise floor rather than a signal.
#
# In-process, like `ratelimit.py`, and for the same reason: this is an FYP-scale
# deployment and a queue is a dependency nobody has committed to. The seam is
# here when Celery lands (tdd.md §2.2) — `send_async` is the only call site.
# ---------------------------------------------------------------------------

_executor: ThreadPoolExecutor | None = None
_pending: list[Future] = []


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edubridge-email")
        atexit.register(_executor.shutdown, wait=True)
    return _executor


def _deliver(to: str, subject: str, html_body: str) -> None:
    try:
        get_email_sender().send(to, subject, html_body)
    except Exception:  # noqa: BLE001 -- a failed send must not kill the worker
        # Deliberately no address, subject or body in the log line beyond what
        # the sender already records: this runs after the response, so there is
        # nobody to tell, and an exception here would otherwise be swallowed
        # silently by the executor.
        logger.exception("email delivery failed")


def send_async(to: str, subject: str, html_body: str) -> None:
    """Queue an email. Returns immediately; delivery happens off the request."""
    future = _pool().submit(_deliver, to, subject, html_body)
    _pending.append(future)


def drain_pending_emails(timeout: float = 10.0) -> None:
    """
    Block until queued sends finish. For TESTS, which need to assert that a
    message was produced, and for a graceful shutdown.
    """
    pending, _pending[:] = list(_pending), []
    for future in pending:
        future.result(timeout=timeout)
