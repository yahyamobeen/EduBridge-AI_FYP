"""Unit tests for the Class 9 Physics AI Tutor module."""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthContext
from app.core.errors import AppError
from app.main import create_app
from app.retrieval.physics9.base import CHAPTERS, chapter_of
from app.retrieval.physics9.generator import PhysicsGenerator
from app.retrieval.physics9.heuristic import HeuristicRetriever
from app.retrieval.physics9.service import answer_physics_query
from app.tutor.routes import require_class_9_student


def test_chapter_mapping():
    assert chapter_of(1) is None  # Front matter
    assert chapter_of(5) == 1
    assert chapter_of(27) == 1
    assert chapter_of(148) == 7
    assert chapter_of(155) == 7
    assert chapter_of(160) == 7
    assert chapter_of(195) is None  # Index / back matter
    assert len(CHAPTERS) == 9


def test_retriever_search_top_k():
    retriever = HeuristicRetriever()
    hits, timings = retriever.search("thermocouple working", top_k=3)
    assert len(hits) == 3
    assert all("page" in h and "chapter" in h and "score" in h and "url" in h for h in hits)
    # Thermocouple is in chapter 7 (p154-155)
    pages = [h["page"] for h in hits]
    assert 154 in pages or 155 in pages
    # The heuristic tier has no query encoder, so `encode` is genuinely zero.
    assert timings.encode == 0.0
    assert timings.search >= 0.0


def test_anchor_is_a_prior_not_a_filter():
    """An anchored chapter reorders; it never drops pages from other chapters.

    Guards the failure the anchor is designed to avoid: a prerequisite question asked
    while anchored to another chapter must still return something (tdd.md §5.3f).
    """
    retriever = HeuristicRetriever()
    unanchored, _ = retriever.search("vernier callipers parts", top_k=3)
    anchored, _ = retriever.search("vernier callipers parts", top_k=3, chapter=7)

    assert len(anchored) == len(unanchored) == 3
    # Chapter 1 content, asked while anchored to chapter 7: still returned, not filtered.
    assert {h["page"] for h in anchored} == {h["page"] for h in unanchored}


def test_generator_fallback_multilingual(monkeypatch):
    # `PhysicsGenerator.__init__` reads `api_key or os.environ["GEMINI_API_KEY"]`, so
    # passing "" does NOT select the no-key path — it falls through to the environment.
    # Without this the test passed in CI (no key) and, on a developer machine with a key
    # set, made a REAL paid Gemini call and then failed on its assertions. A unit test
    # must not reach the network: `tests/unit` is the suite that runs with no connection
    # string and no live project (backend/CLAUDE.md §5).
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gen = PhysicsGenerator(api_key="")
    hits = [
        {"page": 155, "chapter": 7, "score": 18.0, "url": "/api/tutor/class9/physics/pages/155"}
    ]

    # English
    reply_en, _, err_en = gen.generate("How does a thermocouple work?", hits, lang="en")
    assert "thermocouple" in reply_en.lower()
    assert "(p155)" in reply_en or "page 155" in reply_en.lower()
    assert err_en is not None  # Notes no api key

    # Roman Urdu
    reply_ur_latn, _, _ = gen.generate("thermocouple kaise kaam karta hai?", hits, lang="ur-Latn")
    assert "thermocouple" in reply_ur_latn.lower()  # Kept in English script
    assert "p155" in reply_ur_latn or "155" in reply_ur_latn

    # Urdu script
    reply_ur, _, _ = gen.generate("تھرمو کپل کیسے کام کرتا ہے؟", hits, lang="ur")
    assert "thermocouple" in reply_ur.lower()  # Kept in English script per pedagogical rule


def test_service_answer_physics_query():
    res = answer_physics_query("Explain Pascal's law with formula", lang="en", top_k=2)
    assert "reply" in res
    assert len(res["pages"]) == 2
    assert "timings" in res
    assert "encode" in res["timings"]
    assert "pascal" in res["reply"].lower()


def test_require_class_9_student_guard():
    user_id = uuid4()
    mock_session = MagicMock()

    # Case 1: Not a student
    teacher_ctx = AuthContext(session=mock_session, user_id=user_id, role="teacher")
    with pytest.raises(AppError) as exc_info:
        require_class_9_student(teacher_ctx)
    assert exc_info.value.code == "FORBIDDEN_SCOPE"

    # Case 2: Student in Class 10
    mock_result = MagicMock()
    mock_result.mappings.return_value.one_or_none.return_value = {"class_level": 10}
    mock_session.execute.return_value = mock_result
    student_10_ctx = AuthContext(session=mock_session, user_id=user_id, role="student")
    with pytest.raises(AppError) as exc_info:
        require_class_9_student(student_10_ctx)
    assert exc_info.value.code == "FORBIDDEN_SCOPE"

    # Case 3: Student in Class 9 -> passes
    mock_result.mappings.return_value.one_or_none.return_value = {"class_level": 9}
    student_9_ctx = AuthContext(session=mock_session, user_id=user_id, role="student")
    result_ctx = require_class_9_student(student_9_ctx)
    assert result_ctx.user_id == user_id


def test_tutor_info_endpoint():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/tutor/class9/physics/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["subject"] == "Physics"
    assert data["class_level"] == 9
    assert data["board"] == "PCTB"
    assert data["book_pages"] == 200


def test_page_image_bounds_check():
    from app.tutor.routes import get_physics_page_image

    # Page 0 and 201 should raise 404
    with pytest.raises(HTTPException) as exc1:
        get_physics_page_image(0)
    assert exc1.value.status_code == 404

    with pytest.raises(HTTPException) as exc2:
        get_physics_page_image(201)
    assert exc2.value.status_code == 404


def test_quota_429_is_not_retried_against_the_same_model(monkeypatch):
    """A per-day quota 429 must drop the model, not re-ask it.

    ⚠️ The free tier is 20 requests per day per model, and a quota 429 advertises a
    `retryDelay` of hours. Every retry spends another of the 20, so retrying here
    burns the day's budget on a refusal already received - while the student waits
    through a `time.sleep` for each one.
    """
    import httpx

    from app.retrieval.physics9 import generator as gen_mod

    quota_body = json.dumps(
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                        ],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "29673s"},
                ],
            }
        }
    )

    attempted: list[str] = []
    slept: list[float] = []
    monkeypatch.setattr(gen_mod.time, "sleep", lambda s: slept.append(s))

    class _Resp:
        status_code = 429
        text = quota_body

        def read(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, _method, url, **_kw):
            attempted.append(url.rsplit("/", 1)[-1].split(":")[0])
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)

    g = gen_mod.PhysicsGenerator(
        api_key="k", model_name="gemini-3.6-flash", fallback_models=["gemini-3.5-flash"]
    )
    with pytest.raises(RuntimeError):
        list(g.stream_tokens(question="q", hits=[], history=None))

    # Each model asked exactly once; the primary's duplicate pass is skipped.
    assert attempted == ["gemini-3.6-flash", "gemini-3.5-flash"]
    assert len(attempted) == len(set(attempted)), "a model was asked twice after a quota refusal"
    # And no blocking sleep, because waiting out hours cannot help.
    assert slept == []


def test_api_key_never_appears_in_the_request_url(monkeypatch):
    """The key travels as a header, never as `?key=` in the URL.

    ⚠️ REGRESSION. httpx logs the full request URL at INFO, so a key in the query
    string was written verbatim into the application log on every call - the live key
    appeared in plaintext in production output beside a `200 OK`. The URL is also what
    reverse proxies, access logs and error trackers record, so no amount of log-level
    tuning in this application would have contained it. `backend/CLAUDE.md` §6 says
    secrets are never logged; only a header keeps that promise.
    """
    import httpx

    from app.retrieval.physics9 import generator as gen_mod

    secret = "AQ.test-key-must-not-be-logged"  # noqa: S105 -- a fixture, not a credential
    seen: dict[str, object] = {}

    class _Resp:
        status_code = 500
        text = "{}"

        def read(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, _method, url, **kw):
            seen["url"] = url
            seen["params"] = kw.get("params") or {}
            seen["headers"] = kw.get("headers") or {}
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(gen_mod.time, "sleep", lambda _s: None)

    g = gen_mod.PhysicsGenerator(api_key=secret, model_name="gemini-3.6-flash")
    with pytest.raises(RuntimeError):
        list(g.stream_tokens(question="q", hits=[], history=None))

    assert secret not in str(seen["url"])
    # `params` is what httpx appends to the logged URL, so the key must not be there.
    assert secret not in str(seen["params"])
    assert "key" not in seen["params"]
    assert seen["headers"]["x-goog-api-key"] == secret


def test_payload_disables_thinking_and_leaves_room_for_the_answer():
    """Reasoning tokens come out of `max_output_tokens`, so they can eat the answer.

    ⚠️ REGRESSION. Gemini 3.x flash models think before answering, and the budget is
    shared. Measured on a real tutor prompt: 854 thinking tokens against 180 of answer
    and `finishReason: MAX_TOKENS` - the student saw a reply that stopped mid-sentence
    while the log showed `200 OK` and no error of any kind. Nothing downstream can
    detect that; it has to be prevented in the request.
    """
    from app.retrieval.physics9.generator import PhysicsGenerator

    g = PhysicsGenerator(api_key="k", model_name="gemini-3-flash-preview")
    cfg = g.build_payload(question="what is a vernier calliper", hits=[], history=None)[
        "generation_config"
    ]

    assert cfg["thinking_config"]["thinking_budget"] == 0
    # Headroom over the ~400 answer tokens a full reply measured at.
    assert cfg["max_output_tokens"] >= 2048
