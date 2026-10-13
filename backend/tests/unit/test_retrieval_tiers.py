"""The retrieval seam: tier selection, degradation, and response validation.

`RemoteRetriever` talks to a separate process, so its response is INPUT and is treated
as such. These tests cover the contract between the two and the degradation path, which
is the behaviour that decides whether a cold retrieval host costs answer quality or
costs availability (tdd.md §3.2a).

No socket is bound and no model is loaded: `httpx.Client.post` is monkeypatched, so this
stays a unit test (backend/CLAUDE.md §5).
"""

from __future__ import annotations

import httpx
import pytest

from app.retrieval.physics9 import service
from app.retrieval.physics9.base import RetrievalUnavailableError
from app.retrieval.physics9.remote import RemoteRetriever


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self):
        return self._payload


def _reply(monkeypatch, payload, status_code=200):
    """Make every outgoing retrieval POST answer with `payload`."""
    captured: dict = {}

    def fake_post(self, url, json=None, headers=None):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers or {}
        return _Response(payload, status_code)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return captured


GOOD = {
    "pages": [155, 154, 157],
    "scores": [18.4, 17.9, 12.1],
    "encode_ms": 310.0,
    "search_ms": 18.0,
}


def test_remote_happy_path(monkeypatch):
    captured = _reply(monkeypatch, GOOD)
    retriever = RemoteRetriever(
        endpoint="https://r.example.com/",
        shared_secret="s3cret",  # noqa: S106 -- a test fixture, asserted below never to leak
    )

    hits, timings = retriever.search("how does a thermocouple work", top_k=3, chapter=7)

    assert [h["page"] for h in hits] == [155, 154, 157]
    # The chapter is derived on this side, so a remote tier never has to agree with us
    # about the book's structure.
    assert [h["chapter"] for h in hits] == [7, 7, 7]
    assert hits[0]["url"] == "/api/tutor/class9/physics/pages/155"
    # Milliseconds on the wire, seconds in the application.
    assert timings.encode == pytest.approx(0.310)
    assert timings.search == pytest.approx(0.018)

    assert captured["url"] == "https://r.example.com/retrieve"
    assert captured["json"] == {
        "question": "how does a thermocouple work",
        "top_k": 3,
        "chapter": 7,
    }
    assert captured["headers"]["X-Retrieval-Secret"] == "s3cret"


def test_chapter_is_omitted_when_absent(monkeypatch):
    captured = _reply(monkeypatch, GOOD)
    RemoteRetriever(endpoint="https://r.example.com").search("x")
    assert "chapter" not in captured["json"]


def test_no_secret_sends_no_header(monkeypatch):
    captured = _reply(monkeypatch, GOOD)
    RemoteRetriever(endpoint="https://r.example.com").search("x")
    assert "X-Retrieval-Secret" not in captured["headers"]


def test_endpoint_is_required():
    with pytest.raises(ValueError, match="RETRIEVAL_ENDPOINT"):
        RemoteRetriever(endpoint="")


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"scores": [1.0]}, "pages missing"),
        ({"pages": [155]}, "scores missing"),
        ({"pages": [155, 154], "scores": [1.0]}, "length mismatch"),
        ({"pages": [0], "scores": [1.0]}, "page below range"),
        ({"pages": [201], "scores": [1.0]}, "page above range"),
        ({"pages": ["155"], "scores": [1.0]}, "page not an integer"),
        ({"pages": [True], "scores": [1.0]}, "bool is not a page"),
        ({"pages": [155], "scores": ["high"]}, "score not a number"),
        ({"pages": [], "scores": []}, "no pages at all"),
        ("not an object", "response is not a dict"),
    ],
)
def test_malformed_responses_are_refused(monkeypatch, payload, reason):
    """A bad response must never become a citation.

    An out-of-range page renders as a link to a page that does not exist, which in the
    interface is indistinguishable from the retriever simply being wrong.
    """
    _reply(monkeypatch, payload)
    with pytest.raises(RetrievalUnavailableError):
        RemoteRetriever(endpoint="https://r.example.com").search("x")


def test_transport_failure_is_refused_not_raised_raw(monkeypatch):
    def explode(self, url, json=None, headers=None):  # noqa: A002
        raise httpx.ConnectTimeout("cold host")

    monkeypatch.setattr(httpx.Client, "post", explode)
    with pytest.raises(RetrievalUnavailableError):
        RemoteRetriever(endpoint="https://r.example.com").search("x")


def test_secret_never_appears_in_the_error(monkeypatch):
    """The failure reason is logged and surfaced; the credential is not part of it."""

    def explode(self, url, json=None, headers=None):  # noqa: A002
        raise httpx.ConnectTimeout("cold host")

    monkeypatch.setattr(httpx.Client, "post", explode)
    with pytest.raises(RetrievalUnavailableError) as caught:
        RemoteRetriever(
            endpoint="https://r.example.com",
            shared_secret="s3cret",  # noqa: S106 -- the value this test proves is not leaked
        ).search("x")
    assert "s3cret" not in str(caught.value)


def test_service_degrades_to_heuristic_and_says_so(monkeypatch):
    """The point of the seam: a dead remote tier costs answer quality, not availability.

    And the reported tier must change, because a degraded answer presented as a neural
    one is the failure this design exists to prevent.
    """

    def explode(self, url, json=None, headers=None):  # noqa: A002
        raise httpx.ConnectTimeout("cold host")

    monkeypatch.setattr(httpx.Client, "post", explode)
    monkeypatch.setenv("RETRIEVAL_MODE", "remote")
    monkeypatch.setenv("RETRIEVAL_ENDPOINT", "https://r.example.com")
    from app.core.config import get_settings

    get_settings.cache_clear()
    service.reset_for_tests()
    try:
        hits, timings, tier = service.search("how does a thermocouple work", top_k=3)
        assert tier == "heuristic"
        assert {h["page"] for h in hits} & {154, 155}
        assert timings.encode == 0.0
    finally:
        get_settings.cache_clear()
        service.reset_for_tests()


def test_misconfigured_remote_degrades_at_construction(monkeypatch):
    """RETRIEVAL_MODE=remote with no endpoint must not take the tutor down."""
    monkeypatch.setenv("RETRIEVAL_MODE", "remote")
    monkeypatch.setenv("RETRIEVAL_ENDPOINT", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    service.reset_for_tests()
    try:
        assert service.get_physics_retriever().name == "heuristic"
    finally:
        get_settings.cache_clear()
        service.reset_for_tests()
