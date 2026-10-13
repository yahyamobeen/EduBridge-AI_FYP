"""Retrieval over HTTP against the ColQwen2 service (tdd.md §3.2a).

**The default tier.** The model is 2.2B parameters and needs ~5 GB resident at
bfloat16; the backend runs on a 512 MB instance. Keeping the model out of this process
is what lets the backend stay small and carry no `torch` dependency at all.

The service is reached through a tunnel, so there is no inbound port on the host and no
certificate to manage. `RETRIEVAL_SHARED_SECRET` is defence in depth - the service also
binds to 127.0.0.1 behind its tunnel daemon.
"""

from __future__ import annotations

import logging

import httpx

from app.retrieval.physics9.base import (
    BOOK_PAGES,
    Hit,
    RetrievalUnavailableError,
    Timings,
    make_hits,
)

logger = logging.getLogger("edubridge.retrieval.physics9.remote")

# Short on purpose. The retrieval host scales to zero or stops on a schedule, so a cold
# first request can take minutes - and waiting minutes is worse for the student than a
# keyword answer now. We fail fast, degrade to the heuristic tier, and the request we
# just abandoned has already triggered the host to start, so the next question lands on
# a warm model. Raising these to cover a cold start would make every outage a hang.
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 20.0


class RemoteRetriever:
    """`RETRIEVAL_MODE=remote`. Raises `RetrievalUnavailableError`; the caller degrades."""

    def __init__(self, endpoint: str, shared_secret: str = "") -> None:
        if not endpoint:
            raise ValueError("RETRIEVAL_ENDPOINT is required when RETRIEVAL_MODE=remote")
        self._url = endpoint.rstrip("/") + "/retrieve"
        self._secret = shared_secret

    @property
    def name(self) -> str:
        return "remote"

    def search(
        self, question: str, top_k: int = 3, chapter: int | None = None
    ) -> tuple[list[Hit], Timings]:
        payload: dict[str, object] = {"question": question, "top_k": top_k}
        if chapter is not None:
            payload["chapter"] = chapter

        headers = {"X-Retrieval-Secret": self._secret} if self._secret else {}

        try:
            with httpx.Client(timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)) as c:
                response = c.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            # The message is logged, never returned: an endpoint URL or a header name is
            # not something a student's error state should carry. The secret itself is
            # never in the message - httpx does not echo request headers in its errors -
            # but keep this branch narrow regardless.
            logger.warning("retrieval service unreachable (%s)", type(exc).__name__)
            raise RetrievalUnavailableError(str(type(exc).__name__)) from exc

        return make_hits(_validate(body, top_k)), Timings(
            encode=_seconds(body.get("encode_ms")),
            search=_seconds(body.get("search_ms")),
        )


def _seconds(milliseconds: object) -> float:
    """Milliseconds from the wire to seconds, defensively.

    A missing or non-numeric timing is reported as 0.0 rather than raising: a timing is
    telemetry, and losing it must not cost the student their answer.
    """
    try:
        return float(milliseconds) / 1000.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _validate(body: object, top_k: int) -> list[tuple[int, float]]:
    """Check the response before it becomes a citation.

    The retrieval service is a separate process we do not hold a transaction with, so
    its output is input. A page number outside the book, or a pages/scores length
    mismatch, would surface as a citation link to a page that does not exist - which in
    the interface is indistinguishable from the retriever being wrong.
    """
    if not isinstance(body, dict):
        raise RetrievalUnavailableError("response was not an object")

    pages, scores = body.get("pages"), body.get("scores")
    if not isinstance(pages, list) or not isinstance(scores, list):
        raise RetrievalUnavailableError("response missing pages or scores")
    if len(pages) != len(scores):
        raise RetrievalUnavailableError(f"{len(pages)} pages against {len(scores)} scores")

    out: list[tuple[int, float]] = []
    for page, score in list(zip(pages, scores, strict=True))[:top_k]:
        if not isinstance(page, int) or isinstance(page, bool):
            raise RetrievalUnavailableError("page number was not an integer")
        if not 1 <= page <= BOOK_PAGES:
            raise RetrievalUnavailableError(f"page {page} is outside 1-{BOOK_PAGES}")
        try:
            out.append((page, float(score)))
        except (TypeError, ValueError) as exc:
            raise RetrievalUnavailableError("score was not a number") from exc

    if not out:
        raise RetrievalUnavailableError("response contained no pages")
    return out
