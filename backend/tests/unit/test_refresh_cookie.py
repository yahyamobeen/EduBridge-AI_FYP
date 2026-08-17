"""
The refresh cookie's setter and its deleter must not drift (finding A2).

WHAT WENT WRONG: `logout()` revoked the refresh rows and nothing cleared the
cookie. The browser kept presenting it, the next `/auth/refresh` found
`revoked = true`, read that as two parties holding one token, revoked the whole
family and wrote a `refresh_token_reuse_detected` audit row. Every ordinary
sign-out fabricated a security incident, and the log that exists to surface real
theft filled with noise.

WHY THESE TESTS EXIST RATHER THAN JUST THE FIX: a browser only overwrites a
cookie when the name, path and domain match. A deletion that disagrees with the
setter on any of them silently leaves the old cookie in place — the response
looks correct, the header is present, and nothing fails. The attributes were
previously written out by hand at three call sites, so the failure mode was one
copy-paste away. These tests pin the two functions together.
"""

from http.cookies import SimpleCookie

from fastapi import Response

from app.auth.dependencies import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    clear_refresh_cookie,
    set_refresh_cookie,
)


def _emitted(response: Response) -> SimpleCookie:
    """Parse the Set-Cookie the response actually carries."""
    jar = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        jar.load(header)
    return jar


def _set() -> SimpleCookie:
    response = Response()
    set_refresh_cookie(response, "a-refresh-token")
    return _emitted(response)


def _cleared() -> SimpleCookie:
    response = Response()
    clear_refresh_cookie(response)
    return _emitted(response)


class TestTheDeletionMirrorsTheSetter:
    """
    The invariant. Each attribute is asserted against the SETTER's value rather
    than against a literal, so the pair stays welded together even if the policy
    changes — moving the cookie's path, for instance, cannot silently break
    deletion.
    """

    def test_same_name(self):
        assert REFRESH_COOKIE_NAME in _set()
        assert REFRESH_COOKIE_NAME in _cleared()

    def test_same_path(self):
        assert _cleared()[REFRESH_COOKIE_NAME]["path"] == _set()[REFRESH_COOKIE_NAME]["path"]
        assert _set()[REFRESH_COOKIE_NAME]["path"] == REFRESH_COOKIE_PATH

    def test_same_samesite(self):
        assert (
            _cleared()[REFRESH_COOKIE_NAME]["samesite"] == _set()[REFRESH_COOKIE_NAME]["samesite"]
        )

    def test_same_httponly(self):
        assert (
            _cleared()[REFRESH_COOKIE_NAME]["httponly"] == _set()[REFRESH_COOKIE_NAME]["httponly"]
        )

    def test_same_secure_flag(self):
        """
        Both read `settings.is_production`, so they agree by construction. This
        asserts the construction rather than the value — the test must not care
        which environment it runs in.
        """
        assert _cleared()[REFRESH_COOKIE_NAME]["secure"] == _set()[REFRESH_COOKIE_NAME]["secure"]


class TestTheCookieItself:
    def test_the_setter_carries_the_token(self):
        assert _set()[REFRESH_COOKIE_NAME].value == "a-refresh-token"

    def test_the_setter_is_http_only(self):
        """Not readable from JavaScript — the whole reason it is a cookie and
        not a field in the response body."""
        assert _set()[REFRESH_COOKIE_NAME]["httponly"]

    def test_the_setter_is_scoped_to_the_refresh_route(self):
        """Otherwise the credential rides on every API call, including ones that
        have no business seeing it."""
        assert _set()[REFRESH_COOKIE_NAME]["path"] == "/api/auth/refresh"

    def test_the_deletion_expires_it_immediately(self):
        assert _cleared()[REFRESH_COOKIE_NAME]["max-age"] in ("0", 0)

    def test_the_deletion_carries_no_value(self):
        assert _cleared()[REFRESH_COOKIE_NAME].value == ""
