"""SSE streaming for `POST /api/tutor/ask` (tdd.md §3.2).

The repo's first streaming endpoint, so these tests pin the properties that are easy to
break and silent when broken: frame order, the transaction boundary, and the fact that
a failure after the first byte cannot become an HTTP status.
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.dependencies import AuthContext, authenticated, require_guardian_verified
from app.main import create_app
from app.retrieval.physics9.generator import PhysicsGenerator
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
    def __init__(self, session_id):
        self.session_id = session_id
        self.statements: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append((sql, params or {}))
        if "INSERT INTO chat_session" in sql:
            return _Result([{"id": self.session_id, "chapter": (params or {}).get("chapter")}])
        if "SELECT id, chapter FROM chat_session" in sql:
            return _Result([{"id": self.session_id, "chapter": 7}])
        if "INSERT INTO message" in sql:
            return _Result([uuid4()])
        return _Result([])

    def inserts_into(self, table: str) -> list[dict]:
        return [p for sql, p in self.statements if f"INSERT INTO {table}" in sql]


class _FakeGenerator:
    """Stands in for Gemini. `chunks` is what the model 'produces'."""

    def __init__(self, chunks, api_key="test-key", explode_after=None):
        self.chunks = chunks
        self.api_key = api_key
        self.explode_after = explode_after
        self.saw_history = None

    def stream_tokens(self, question, hits, history=None):
        self.saw_history = history
        for index, chunk in enumerate(self.chunks):
            if self.explode_after is not None and index == self.explode_after:
                raise RuntimeError("upstream died")
            yield chunk


def _client(monkeypatch, app, generator, session_id=None):
    fake_db = _FakeSession(session_id or uuid4())
    ctx = AuthContext(session=fake_db, user_id=uuid4(), role="student")
    app.dependency_overrides[authenticated] = lambda: ctx
    app.dependency_overrides[require_guardian_verified] = lambda: ctx
    app.dependency_overrides[require_class_9_student] = lambda: ctx
    monkeypatch.setattr("app.tutor.routes.get_physics_generator", lambda: generator)
    return TestClient(app), fake_db


def _events(body: str) -> list[tuple[str, str]]:
    """Parse the SSE body into (event, data) pairs."""
    out = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next((line[len("event: ") :] for line in lines if line.startswith("event: ")), None)
        data = next((line[len("data: ") :] for line in lines if line.startswith("data: ")), None)
        if event:
            out.append((event, data or ""))
    return out


def test_pages_arrive_before_the_first_token(monkeypatch):
    """Citations render while the answer is still being written.

    The ordering is the entire user-visible benefit of streaming here: retrieval
    finishes in milliseconds and generation takes seconds, so a student sees which
    pages were found long before the prose arrives.
    """
    app = create_app()
    client, _ = _client(monkeypatch, app, _FakeGenerator(["Heat ", "is ", "energy."]))
    resp = client.post("/api/tutor/ask", json={"message": "what is heat"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # The header that stops a reverse proxy buffering the whole body and turning a
    # streamed answer back into one slow response.
    assert resp.headers["x-accel-buffering"] == "no"

    events = [name for name, _ in _events(resp.text)]
    assert events[0] == "pages"
    assert events[-1] == "done"
    assert events.count("token") == 3
    assert events.index("pages") < events.index("token")


def test_done_carries_the_session_and_message_ids(monkeypatch):
    app = create_app()
    session_id = uuid4()
    client, _ = _client(monkeypatch, app, _FakeGenerator(["ok"]), session_id=session_id)
    resp = client.post("/api/tutor/ask", json={"message": "what is heat"})

    done = dict(_events(resp.text))["done"]
    assert str(session_id) in done
    assert '"error": null' in done or '"error":null' in done


def test_both_turns_are_persisted_at_the_end(monkeypatch):
    """One transaction covers the question and the answer.

    Writing the question up front would leave an orphan when generation fails - a
    transcript showing the student asking and the tutor silent, which reads as a refusal
    rather than a fault.
    """
    app = create_app()
    client, db = _client(monkeypatch, app, _FakeGenerator(["Heat ", "is energy."]))
    resp = client.post("/api/tutor/ask", json={"message": "what is heat"})
    assert resp.status_code == 200

    messages = db.inserts_into("message")
    assert [m["role"] for m in messages] == ["student", "assistant"]
    assert messages[0]["content"] == "what is heat"
    assert messages[1]["content"] == "Heat is energy."
    assert len(db.inserts_into("visual_aid")) == 1


def test_nothing_is_persisted_when_the_model_produces_nothing(monkeypatch):
    """No tokens means no turn - not a question paired with an empty answer."""
    app = create_app()
    client, db = _client(monkeypatch, app, _FakeGenerator([]))
    resp = client.post("/api/tutor/ask", json={"message": "what is heat"})
    assert resp.status_code == 200
    assert db.inserts_into("message") == []


def test_missing_api_key_is_a_503_before_any_byte(monkeypatch):
    """A failure the client can still read as an error, with the catalogued code.

    ⚠️ And NOT the old path's from-memory fallback (defect P2): a student who cannot be
    answered is told so, rather than handed physics with a page number attached to it.
    """
    app = create_app()
    client, db = _client(monkeypatch, app, _FakeGenerator(["x"], api_key=""))
    resp = client.post("/api/tutor/ask", json={"message": "what is heat"})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    # Nothing was written, and the body is a real envelope rather than a stream.
    assert db.inserts_into("message") == []
    assert not resp.headers["content-type"].startswith("text/event-stream")


def test_midstream_failure_reports_on_done_and_keeps_what_arrived(monkeypatch):
    """After the first byte there is no status line left to change.

    So the failure is reported on `done`, the client keeps the citations and the partial
    text it already rendered, and nothing is invented to fill the gap.
    """
    app = create_app()
    generator = _FakeGenerator(["Heat is ", "energy in ", "transit"], explode_after=2)
    client, db = _client(monkeypatch, app, generator)
    resp = client.post("/api/tutor/ask", json={"message": "what is heat"})

    assert resp.status_code == 200  # the status was committed before the failure
    events = _events(resp.text)
    # The text, not the frame count: the marker guard holds back a trailing tail and
    # flushes it at the end, so the number of frames is an implementation detail.
    streamed = "".join(json.loads(data)["text"] for name, data in events if name == "token")
    assert streamed == "Heat is energy in "
    assert "MODEL_UNAVAILABLE" in dict(events)["done"]
    # What did arrive is still the student's transcript.
    assert db.inserts_into("message")[1]["content"] == "Heat is energy in "


def test_resuming_reads_history_from_the_database(monkeypatch):
    app = create_app()
    generator = _FakeGenerator(["sure"])
    session_id = uuid4()
    client, db = _client(monkeypatch, app, generator, session_id=session_id)
    resp = client.post(
        "/api/tutor/ask",
        json={"message": "explain that again", "session_id": str(session_id)},
    )
    assert resp.status_code == 200
    assert db.inserts_into("chat_session") == []
    assert any("SELECT role, content FROM message" in sql for sql, _ in db.statements)
    assert generator.saw_history is not None


def test_dependency_outlives_the_stream():
    """⚠️ GUARD, NOT A FEATURE TEST.

    Persistence happens inside the streaming generator, which is only safe because
    FastAPI finalises dependencies-with-yield AFTER the response body is streamed.
    That ordering CHANGED in fastapi 0.106, and if it changes back every transcript
    silently stops being saved - no error, no failing request, just an empty history.

    So this asserts the framework behaviour directly. If it fails after an upgrade, the
    fix is to give the stream its own session, not to delete this test.
    """
    from fastapi import Depends, FastAPI
    from fastapi.responses import StreamingResponse

    order: list[str] = []
    probe = FastAPI()

    def dep():
        try:
            yield "resource"
        finally:
            order.append("dependency closed")

    @probe.post("/probe")
    def route(_resource: str = Depends(dep)) -> StreamingResponse:
        def gen():
            yield b"a"
            order.append("generator finished")

        return StreamingResponse(gen())

    with TestClient(probe) as client:
        client.post("/probe")

    assert order == ["generator finished", "dependency closed"], (
        f"FastAPI finalisation order changed: {order}. Persistence inside a streaming "
        f"generator is no longer safe - see app/tutor/streaming.py."
    )


def test_no_identity_reaches_gemini():
    """The mitigation deviation V3 rests on (tdd.md §14.2).

    Only the question text and the page images leave the platform. An anonymous physics
    question is a materially weaker claim on "data about minors" than an identified one,
    and this is the assertion that keeps it true.

    ⚠️ Asserts on real identity VALUES, deliberately, rather than on substrings like
    "@" or "user_id". An earlier version searched for "@" and began failing when the
    system prompt gained the `@@FIGURE` sentinel - a test that fails for a reason
    unrelated to its subject gets deleted rather than fixed, and this one must survive.
    """
    user_id = "6f0a1e6c-6a7f-4f0e-9a1d-2b3c4d5e6f70"
    session_id = "11111111-2222-3333-4444-555555555555"
    email = "student@example.edu.pk"
    full_name = "Ayesha Khan"

    generator = PhysicsGenerator(api_key="k", pages_dir=None)
    payload = generator.build_payload(
        question="what is heat",
        hits=[
            {
                "page": 151,
                "chapter": 7,
                "score": 18.0,
                "url": "/api/x/151",
                # Even if a caller passes identifiers alongside the hit, none of them
                # may reach the request body.
                "student_id": user_id,
                "session_id": session_id,
            }
        ],
        history=[{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
    )

    body = repr(payload)
    for value in (user_id, session_id, email, full_name):
        assert value not in body, f"{value!r} reached the Gemini payload"


def test_history_is_bounded_to_four_turns():
    """An unbounded window grows the prompt - and, with a hosted generator, the
    exposure - without limit (tdd.md §4.1)."""
    generator = PhysicsGenerator(api_key="k", pages_dir=None)
    history = [{"role": "user", "content": f"q{i}"} for i in range(20)]
    payload = generator.build_payload("now what", [{"page": 1}], history)
    # Four replayed turns plus the current question.
    assert len(payload["contents"]) == 5
    assert "q19" in repr(payload)
    assert "q15" not in repr(payload)
