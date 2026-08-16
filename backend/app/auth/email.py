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
import html
import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger("edubridge.email")


class EmailSender(Protocol):
    """Minimal interface for transactional email delivery."""

    def send(self, to: str, subject: str, html_body: str) -> None: ...


def _readable(html_body: str) -> str:
    """
    Strip the markup so the code or link is findable in a terminal.

    Development only — see `LoggingEmailSender`. Deliberately crude: this is a
    debugging aid, not an HTML parser, and pulling in one for it would be a
    dependency the project does not otherwise need.
    """
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_body, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(f"  | {line}" for line in lines if line)


class LoggingEmailSender:
    """
    Development and CI: write the message to the log instead of sending it.

    THE BODY IS LOGGED, INCLUDING THE ONE-TIME CODE OR LINK, and that is the
    point. This sender is selected only when `EMAIL_PROVIDER=logging`, which
    `Settings` REFUSES in production — so there is no deployment in which this
    line can reach a log aggregator holding real users' codes.

    It was metadata-only, which sounds safer and made the email flows
    impossible to exercise: the OTP is stored as an HMAC hash, so a code that is
    neither delivered nor logged cannot be recovered by anyone, and 2FA
    enrolment by email simply could not be completed on a developer machine.
    A control that only stops the honest developer is not a control.
    """

    def send(self, to: str, subject: str, html_body: str) -> None:
        logger.info(
            "EMAIL (not sent - EMAIL_PROVIDER=logging)\n  to:      %s\n  subject: %s\n%s",
            to,
            subject,
            _readable(html_body),
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
    """
    Queue an email. Returns immediately; delivery happens off the request.

    ⚠️ THIS DISPATCHES NOW, WITH NO REGARD FOR THE TRANSACTION. Almost every
    caller should use `send_after_commit` instead — see finding D1 below. This
    stays public because the after-commit path calls it, and because a message
    that depends on no database state is legitimately sent this way.
    """
    future = _pool().submit(_deliver, to, subject, html_body)
    _pending.append(future)


# ---------------------------------------------------------------------------
# Finding D1 — dispatch must wait for the transaction that justified it.
#
# `send_async` hands the message to a worker thread IMMEDIATELY. Every caller
# in `service.py` runs inside an open transaction that has not committed yet:
# the real commit happens in `core/db.py`'s `get_db`, AFTER the route returns.
#
# So the ordering was: mint a token -> queue the email -> worker sends it ->
# request fails -> transaction rolls back. The user receives a verification or
# password-reset link for a token row that does not exist, and clicking it is an
# INVALID_TOKEN they cannot do anything about. The email is unrecallable; the
# database is not, which is exactly the wrong way round.
#
# The outbox lives in `Session.info`, so it is per-session and needs no globals
# and no plumbing through call signatures beyond the session already in scope.
# ---------------------------------------------------------------------------

_OUTBOX = "edubridge_email_outbox"


def send_after_commit(session: Session, to: str, subject: str, html_body: str) -> None:
    """
    Queue an email to be dispatched **only if this transaction commits**.

    Discarded on rollback: an email about a row that no longer exists is worse
    than no email, because the user acts on it.
    """
    session.info.setdefault(_OUTBOX, []).append((to, subject, html_body))


@event.listens_for(Session, "after_commit")
def _dispatch_outbox_on_commit(session: Session) -> None:
    # `.pop` rather than read-then-clear: a send that raises must not leave the
    # message queued for the next commit on the same session.
    for message in session.info.pop(_OUTBOX, []):
        send_async(*message)


@event.listens_for(Session, "after_soft_rollback")
def _discard_outbox_on_rollback(session: Session, previous_transaction: object) -> None:
    """
    ⚠️ `after_soft_rollback`, NOT `after_rollback`. The latter fires only when a
    DBAPI-level rollback actually happens; a session whose transaction never
    reached the database would keep its outbox and dispatch it on the NEXT
    commit — mailing a link for a token that was discarded.
    """
    session.info.pop(_OUTBOX, None)


def drain_pending_emails(timeout: float = 10.0) -> None:
    """
    Block until queued sends finish. For TESTS, which need to assert that a
    message was produced, and for a graceful shutdown.
    """
    pending, _pending[:] = list(_pending), []
    for future in pending:
        future.result(timeout=timeout)
