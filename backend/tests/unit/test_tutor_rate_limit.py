"""The tutor rate limit (tdd.md §3.2a).

⚠️ Unlike every other bucket in `ratelimit.py`, this one is a CORRECTNESS control rather
than an abuse control. One ColQwen2 instance answers one query at a time, with the
forward pass lock-serialised, so an unbounded caller is a denial of service against every
other student in the class - and the retrieval service's own bounded wait starts
returning 503s that look like an outage.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthContext, authenticated, require_guardian_verified
from app.core.ratelimit import TUTOR_ASK_LIMIT, reset_for_tests
from app.main import create_app
from app.tutor.routes import require_class_9_student


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def scalars(self):
        return self

    def one(self):
        return self._rows[0]

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self):
        self.session_id = uuid4()

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        if "INSERT INTO chat_session" in sql:
            return _Result([{"id": self.session_id, "chapter": None}])
        if "SELECT id, chapter FROM chat_session" in sql:
            return _Result([{"id": self.session_id, "chapter": None}])
        if "INSERT INTO message" in sql:
            return _Result([uuid4()])
        return _Result([])


class _FakeGenerator:
    api_key = "test-key"

    def stream_tokens(self, question, hits, history=None):
        yield "answer"


@pytest.fixture(autouse=True)
def _clean_counters():
    """The limiter holds module-level state, so a leaked bucket would make the next
    test fail for a reason that has nothing to do with it."""
    reset_for_tests()
    yield
    reset_for_tests()


def _client(monkeypatch, user_id=None):
    app = create_app()
    ctx = AuthContext(session=_FakeSession(), user_id=user_id or uuid4(), role="student")
    app.dependency_overrides[authenticated] = lambda: ctx
    app.dependency_overrides[require_guardian_verified] = lambda: ctx
    app.dependency_overrides[require_class_9_student] = lambda: ctx
    monkeypatch.setattr("app.tutor.routes.get_physics_generator", lambda: _FakeGenerator())
    return TestClient(app)


def test_the_limit_is_enforced_and_uses_the_catalogued_code(monkeypatch):
    client = _client(monkeypatch)
    allowed = TUTOR_ASK_LIMIT.max_requests

    for index in range(allowed):
        resp = client.post("/api/tutor/ask", json={"message": "what is heat"})
        assert resp.status_code == 200, f"request {index + 1} of {allowed} was refused"

    resp = client.post("/api/tutor/ask", json={"message": "what is heat"})
    assert resp.status_code == 429
    body = resp.json()["error"]
    # tdd.md §7.3's code, not a bespoke one. No endpoint invents a code.
    assert body["code"] == "RATE_LIMITED"
    # The client needs to know how long to wait. ⚠️ Carried in the BODY, not a
    # Retry-After header - recorded as deviation V6 in tdd.md §14.2.
    assert body["details"]["retry_after"] >= 1


def test_ask_and_chat_share_one_bucket(monkeypatch):
    """⚠️ THE POINT OF A SHARED BUCKET.

    Separate buckets would let a client double its budget by alternating the two routes.
    The two do the same expensive thing - one serialised forward pass and three page
    scans to a metered API - so one ceiling has to cover both.
    """
    client = _client(monkeypatch)
    half = TUTOR_ASK_LIMIT.max_requests // 2

    for _ in range(half):
        assert client.post("/api/tutor/ask", json={"message": "what is heat"}).status_code == 200
    for _ in range(TUTOR_ASK_LIMIT.max_requests - half):
        resp = client.post("/api/tutor/class9/physics/chat", json={"message": "what is heat"})
        assert resp.status_code == 200

    # Budget exhausted across BOTH routes, so either one is now refused.
    assert client.post("/api/tutor/ask", json={"message": "x"}).status_code == 429
    assert client.post("/api/tutor/class9/physics/chat", json={"message": "x"}).status_code == 429


def test_the_limit_is_per_user_not_per_address(monkeypatch):
    """A whole school shares one NAT'd address (tdd.md §6.3).

    On an address key, one student exhausting the bucket would throttle the entire
    computer lab - which is the failure the limiter's own `_client_key` comment exists
    to prevent. This asserts it for the tutor specifically.
    """
    first = _client(monkeypatch)
    for _ in range(TUTOR_ASK_LIMIT.max_requests):
        assert first.post("/api/tutor/ask", json={"message": "what is heat"}).status_code == 200
    assert first.post("/api/tutor/ask", json={"message": "x"}).status_code == 429

    # A different student, same process and same address.
    second = _client(monkeypatch)
    assert second.post("/api/tutor/ask", json={"message": "what is heat"}).status_code == 200


def test_reading_transcripts_has_its_own_looser_bucket(monkeypatch):
    """Exhausting the expensive bucket must not stop a student reading what they already
    have - the two cost completely different things."""
    client = _client(monkeypatch)
    for _ in range(TUTOR_ASK_LIMIT.max_requests):
        client.post("/api/tutor/ask", json={"message": "what is heat"})
    assert client.post("/api/tutor/ask", json={"message": "x"}).status_code == 429

    assert client.get("/api/tutor/sessions").status_code == 200
