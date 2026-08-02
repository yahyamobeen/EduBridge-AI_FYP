"""
The rate limiter. No database, no HTTP — just the counter.

`429 RATE_LIMITED` was in the contract and `errors.rate_limited()` existed from
the start; nothing ever called either. These assert the control actually holds
and, just as importantly, that it lets normal use through.
"""

import pytest
from fastapi import Request

from app.core.errors import AppError
from app.core.ratelimit import Limit, enforce, reset_for_tests


def make_request(host: str = "1.2.3.4") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": [],
            "client": (host, 12345),
        }
    )


@pytest.fixture(autouse=True)
def _clean():
    reset_for_tests()
    yield
    reset_for_tests()


def test_allows_up_to_the_limit():
    limit = Limit(max_requests=3, window_seconds=60)
    for _ in range(3):
        enforce(make_request(), bucket="t", limit=limit)


def test_blocks_the_one_after():
    limit = Limit(max_requests=3, window_seconds=60)
    for _ in range(3):
        enforce(make_request(), bucket="t", limit=limit)

    with pytest.raises(AppError) as caught:
        enforce(make_request(), bucket="t", limit=limit)

    assert caught.value.code == "RATE_LIMITED"
    assert caught.value.status_code == 429


def test_reports_a_usable_retry_after():
    """The client renders a countdown from this, so it has to be real."""
    limit = Limit(max_requests=1, window_seconds=60)
    enforce(make_request(), bucket="t", limit=limit)

    with pytest.raises(AppError) as caught:
        enforce(make_request(), bucket="t", limit=limit)

    retry_after = caught.value.details["retry_after"]
    assert 0 < retry_after <= 61


def test_buckets_are_independent():
    """Exhausting login must not lock a user out of registering."""
    limit = Limit(max_requests=1, window_seconds=60)
    enforce(make_request(), bucket="login", limit=limit)
    enforce(make_request(), bucket="register", limit=limit)


def test_callers_are_independent():
    """One noisy address must not lock out everyone else on the platform."""
    limit = Limit(max_requests=1, window_seconds=60)
    enforce(make_request("1.1.1.1"), bucket="t", limit=limit)
    enforce(make_request("2.2.2.2"), bucket="t", limit=limit)

    with pytest.raises(AppError):
        enforce(make_request("1.1.1.1"), bucket="t", limit=limit)
