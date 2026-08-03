"""
Rate limiting for the unauthenticated auth endpoints.

`errors.rate_limited()` and the `429 RATE_LIMITED` contract entry both existed;
nothing called them. The endpoints they were written for — register, login,
refresh — are the brute-force surface of the whole system, and the frontend
already renders a countdown for the response.

SCOPE, STATED PLAINLY: this is an IN-PROCESS fixed-window counter. It is a real
control for a single-process deployment and it is NOT sufficient for several
workers or several instances, because each keeps its own counters — N workers
means N times the allowance. `REDIS_URL` is already in the environment template
for exactly this reason; moving the store there is the upgrade, and the
interface here does not change when it happens.

Deliberately not a new dependency: adding one to a teammate's branch during a
review pass is the kind of decision that should be theirs.
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import Request

from app.core.errors import rate_limited


@dataclass(frozen=True)
class Limit:
    max_requests: int
    window_seconds: int


# Generous on purpose. This exists to stop credential stuffing and scripted
# enumeration, not to inconvenience a student who mistypes a password twice on a
# shared phone (prd.md §3.1).
LOGIN_LIMIT = Limit(max_requests=10, window_seconds=60)
REGISTER_LIMIT = Limit(max_requests=5, window_seconds=300)
REFRESH_LIMIT = Limit(max_requests=30, window_seconds=60)

# KAN-10b: 2FA, email verification and password reset.
#
# TWO LAYERS, because one address is not one user. The deployment target is
# Pakistani school labs and mobile carriers, where a whole cohort shares a
# public address — so an address-keyed limit of 10 verifications per 5 minutes
# means TEN 2FA ATTEMPTS PER FIVE MINUTES FOR THE ENTIRE BUILDING at morning
# sign-in. The address ceilings below are therefore deliberately loose (a crude
# net against a single flooding host), and the real control is the per-ACCOUNT
# limit applied inside the service once the token identifies whose account it
# is, together with the `locked_until` ladder in `two_factor_enrollment`.
TWO_FA_ENROLL_LIMIT = Limit(max_requests=60, window_seconds=300)
TWO_FA_CONFIRM_LIMIT = Limit(max_requests=100, window_seconds=300)
TWO_FA_VERIFY_LIMIT = Limit(max_requests=200, window_seconds=300)
TWO_FA_RESEND_LIMIT = Limit(max_requests=60, window_seconds=300)
EMAIL_VERIFY_LIMIT = Limit(max_requests=100, window_seconds=300)
EMAIL_RESEND_LIMIT = Limit(max_requests=30, window_seconds=300)
PASSWORD_FORGOT_LIMIT = Limit(max_requests=30, window_seconds=300)
PASSWORD_RESET_LIMIT = Limit(max_requests=60, window_seconds=300)

# Per-ACCOUNT. These are the numbers that actually bound an attack, and they are
# unaffected by how many people share an address.
TWO_FA_ENROLL_USER_LIMIT = Limit(max_requests=5, window_seconds=300)
TWO_FA_CONFIRM_USER_LIMIT = Limit(max_requests=5, window_seconds=300)
TWO_FA_VERIFY_USER_LIMIT = Limit(max_requests=10, window_seconds=300)
TWO_FA_RESEND_USER_LIMIT = Limit(max_requests=3, window_seconds=300)

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)


def _client_key(request: Request, bucket: str, subject: str | None = None) -> str:
    # An AUTHENTICATED or token-identified endpoint keys on the acting user, not
    # the address — see the note above the limits. Pre-identification buckets
    # (register, login, refresh, and the first pass at every KAN-10b endpoint)
    # have no user yet and stay on the address.
    #
    # `request.client.host` is the socket peer. Behind a proxy that is the
    # proxy, so the deployment must either set trusted-host forwarding or accept
    # that the limit is per-proxy. Noted rather than silently trusting an
    # X-Forwarded-For header, which any caller can set.
    if subject is not None:
        return f"{bucket}:u:{subject}"
    host = request.client.host if request.client else "unknown"
    return f"{bucket}:{host}"


def _hit(key: str, limit: Limit) -> None:
    now = time.monotonic()
    cutoff = now - limit.window_seconds

    with _lock:
        recent = [t for t in _hits[key] if t > cutoff]
        if len(recent) >= limit.max_requests:
            retry_after = int(recent[0] + limit.window_seconds - now) + 1
            _hits[key] = recent
            raise rate_limited_with_retry(retry_after)
        recent.append(now)
        _hits[key] = recent


def enforce(request: Request, *, bucket: str, limit: Limit, subject: str | None = None) -> None:
    """
    Raise `RATE_LIMITED` when the caller is over the limit for this bucket.

    Pass `subject` (the acting user id) on endpoints that have already resolved
    one; omit it on pre-authentication ones, which fall back to the address.
    """
    _hit(_client_key(request, bucket, subject), limit)


def enforce_subject(*, bucket: str, subject: str, limit: Limit) -> None:
    """
    The per-account half, for service code that identifies the user from a token
    rather than from a session and so has no `Request` in scope.
    """
    _hit(f"{bucket}:u:{subject}", limit)


def rate_limited_with_retry(retry_after_seconds: int):
    error = rate_limited()
    # The client renders a countdown from this, so it has to be present and
    # honest rather than a fixed guess.
    error.details["retry_after"] = max(1, retry_after_seconds)
    return error


def reset_for_tests() -> None:
    with _lock:
        _hits.clear()
