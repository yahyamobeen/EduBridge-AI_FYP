"""
Server-side Turnstile verification (register/login only).

NEVER RETURN the raw `error-codes` to a client: they name Cloudflare internals
and this repo's rule is that a caller never sees more than the envelope
(errors.py `_unhandled_error_response`). They are logged and the client gets
one generic `CAPTCHA_FAILED`.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("edubridge.turnstile")

# Verified against Cloudflare docs at implementation time; the URL below is the
# documented one as of the last check.
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile_token(token: str) -> bool:
    """
    POST the widget's token to siteverify as application/x-www-form-urlencoded.
    Returns True only when the response has `success: true`.

    FAIL-CLOSED: a network failure or a malformed response counts as a
    failure. The consequence of refusing a real visitor is a re-check; the
    consequence of accepting a bot is the thing the captcha exists to stop,
    and on this endpoint that is credential stuffing against minors' accounts.
    """
    settings = get_settings()
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                SITEVERIFY_URL,
                data={
                    "secret": settings.turnstile_secret_key,
                    "response": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        # ValueError covers a non-JSON body. Logged, client never sees why.
        logger.warning("turnstile siteverify failed to contact the provider")
        return False

    success = payload.get("success")
    if not isinstance(success, bool):
        logger.warning("turnstile siteverify returned an unexpected payload")
        return False

    if not success:
        # error-codes is a list of Cloudflare codes; log only.
        logger.error("turnstile rejected token: %s", payload.get("error-codes"))
        return False
    return True
