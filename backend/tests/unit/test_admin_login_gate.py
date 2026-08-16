"""
Segregated administrator authentication (prd.md FR-A2a) — no network, no database.

`login()` now takes `admin_portal`, and the endpoint and the account's role must
agree in BOTH directions: an administrator is refused at `POST /auth/login`, and
everyone else is refused at `POST /auth/admin/login`.

WHAT THESE TESTS ARE REALLY GUARDING is not the refusal — it is that the refusal
is *indistinguishable* from a wrong password. A version of this feature that
answered `403 FORBIDDEN` would refuse exactly as effectively and would still be a
vulnerability, because anyone could then submit an address to the public form and
read the status code to learn whether it belongs to an administrator. So every
test below asserts the whole envelope — code, message and status together —
against the wrong-password refusal captured from the same code path, rather than
asserting `== 401`. A test that only checked the status would pass against the
leaky design.

The database is a stand-in for `app.lookup_user_for_login`, which gained its
`role` column in migration 20260816140000.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.auth.schemas import LoginRequest
from app.auth.service import login
from app.core.errors import AppError

PASSWORD = "correct-horse-battery"  # noqa: S105 -- a fixture credential
WRONG_PASSWORD = "not-the-password"  # noqa: S105 -- a fixture credential
TOKEN = "a-shared-test-token"  # noqa: S105 -- the captcha spy accepts anything


def _fake_login_db(user_row: dict | None):
    """A Session stand-in answering the two reads `login()` makes."""

    class _Mappings:
        def __init__(self, row):
            self._row = row

        def one_or_none(self):
            return self._row

    class _Result:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return _Mappings(self._row)

    class _Db:
        def __init__(self):
            self.executed = 0

        def execute(self, *a, **k):
            self.executed += 1
            if self.executed == 1:
                return _Result(user_row)
            # The 2FA read; `None` means no enrolment yet.
            return _Result(None)

    return _Db()


@pytest.fixture
def service(monkeypatch):
    """`login()` with the captcha and the token writer stubbed out."""
    import app.auth.service as service_module

    monkeypatch.setattr(service_module, "verify_turnstile_token", lambda _t: True)
    monkeypatch.setattr(service_module, "issue_challenge_token", lambda *_a, **_k: "tok")
    return service_module


def _row(role: str, password: str = PASSWORD) -> dict:
    from app.auth.security import hash_password

    return {
        "id": uuid4(),
        "password_hash": hash_password(password),
        "status": "active",
        "email_verified_at": datetime.now(UTC),
        "role": role,
    }


def _attempt(row: dict | None, *, admin_portal: bool, password: str = PASSWORD):
    return login(
        _fake_login_db(user_row=row),
        LoginRequest(email="someone@example.com", password=password, turnstile_token=TOKEN),
        admin_portal=admin_portal,
    )


def _envelope(exc_info) -> tuple[str, str, int]:
    error: AppError = exc_info.value
    return (error.code, error.message, error.status_code)


@pytest.fixture
def wrong_password_envelope(service):
    """
    The refusal every other refusal in this file must be identical to.

    Captured from the real code path rather than written as a literal, so that
    changing the wrong-password message in `service.py` cannot leave these tests
    asserting a string that no longer exists while the gate quietly starts
    answering something distinguishable.
    """
    with pytest.raises(AppError) as exc:
        _attempt(_row("student"), admin_portal=False, password=WRONG_PASSWORD)
    return _envelope(exc)


class TestAdministratorsAreRefusedAtThePublicEndpoint:
    def test_admin_with_the_correct_password_is_refused(self, service, wrong_password_envelope):
        with pytest.raises(AppError) as exc:
            _attempt(_row("admin"), admin_portal=False)

        # THE POINT OF THE TEST: identical, not merely 401.
        assert _envelope(exc) == wrong_password_envelope

    def test_no_details_leak_alongside_the_message(self, service):
        with pytest.raises(AppError) as exc:
            _attempt(_row("admin"), admin_portal=False)

        assert exc.value.details == {}

    def test_the_password_is_still_verified_first(self, service, monkeypatch):
        """
        Timing, not correctness. tdd.md §6.11 forbids revealing an account fact
        by body, status code OR TIMING — so the role check must sit AFTER the
        argon2 verify. Moving it earlier would make an administrator's address
        answer measurably faster than any other, which is the same oracle in a
        different form.
        """
        calls: list[str] = []
        real_verify = service.verify_password
        monkeypatch.setattr(
            service,
            "verify_password",
            lambda p, h: calls.append("password") or real_verify(p, h),
        )

        with pytest.raises(AppError):
            _attempt(_row("admin"), admin_portal=False)

        assert calls == ["password"]


class TestEveryoneElseIsRefusedAtTheAdministratorEndpoint:
    @pytest.mark.parametrize("role", ["student", "teacher", "parent"])
    def test_non_admin_is_refused(self, service, wrong_password_envelope, role):
        with pytest.raises(AppError) as exc:
            _attempt(_row(role), admin_portal=True)

        assert _envelope(exc) == wrong_password_envelope

    def test_unknown_address_is_refused_the_same_way(self, service, wrong_password_envelope):
        """
        A missing row never reaches the role check at all — it is refused by the
        dummy-hash branch. Asserted anyway, because the administrator endpoint
        must not become an oracle for "is there any account at this address".
        """
        with pytest.raises(AppError) as exc:
            _attempt(None, admin_portal=True)

        assert _envelope(exc) == wrong_password_envelope


class TestTheMatchingPairsStillWork:
    def test_admin_at_the_admin_endpoint_proceeds(self, service):
        result = _attempt(_row("admin"), admin_portal=True)

        # No enrolment row in the stand-in, so the account is sent to enrol —
        # which is the same first step every other role gets, deliberately.
        assert result["status"] == "two_factor_enrollment_required"

    @pytest.mark.parametrize("role", ["student", "teacher", "parent"])
    def test_non_admin_at_the_public_endpoint_proceeds(self, service, role):
        result = _attempt(_row(role), admin_portal=False)

        assert result["status"] == "two_factor_enrollment_required"

    def test_the_public_endpoint_is_the_default(self, service, wrong_password_envelope):
        """
        `admin_portal` defaults to False. If that ever flips, every ordinary user
        in the product is locked out at once and every administrator gains a
        public door — so the default is pinned here rather than left implicit.
        """
        with pytest.raises(AppError) as exc:
            login(
                _fake_login_db(user_row=_row("admin")),
                LoginRequest(email="someone@example.com", password=PASSWORD, turnstile_token=TOKEN),
            )

        assert _envelope(exc) == wrong_password_envelope


class TestTheRefusalIsNotSpecialCasedElsewhere:
    def test_an_inactive_admin_is_refused_identically(self, service, wrong_password_envelope):
        """
        The status check runs before the role check. Both answer the same 401, so
        the order between them is not observable — pinned so that a future edit
        which reorders them cannot introduce a difference nobody notices.
        """
        row = _row("admin")
        row["status"] = "suspended"

        with pytest.raises(AppError) as exc:
            _attempt(row, admin_portal=True)

        assert _envelope(exc) == wrong_password_envelope
