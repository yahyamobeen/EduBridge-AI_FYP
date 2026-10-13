"""Tier selection and the retrieve-then-generate path (tdd.md §3.2a).

One place decides which retrieval backend answers, and one place decides what happens
when it cannot. Both matter more than they look: the failure this guards against is not
an outage but a *silent downgrade* - keyword matches served while the interface implies
neural retrieval. Every answer therefore carries the name of the tier that produced it.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.retrieval.physics9.base import RetrievalUnavailableError, Retriever, Timings
from app.retrieval.physics9.generator import PhysicsGenerator
from app.retrieval.physics9.heuristic import HeuristicRetriever

logger = logging.getLogger("edubridge.retrieval.physics9.service")

_retriever: Retriever | None = None
_fallback: HeuristicRetriever | None = None
_generator: PhysicsGenerator | None = None


def _build_retriever() -> Retriever:
    """Construct the configured tier, or degrade to the heuristic one.

    Degrading at construction is deliberate and is logged at a level that matches the
    cause: a missing `[retrieval]` extra is the expected state on a deployment host and
    logs at info, while a present-but-invalid embeddings file is a misconfiguration and
    logs at warning. Either way the process starts and the tutor answers - and reports
    `heuristic`, so nothing claims a model it did not load.
    """
    settings = get_settings()
    mode = settings.retrieval_mode

    if mode == "heuristic":
        return HeuristicRetriever()

    try:
        if mode == "remote":
            from app.retrieval.physics9.remote import RemoteRetriever

            return RemoteRetriever(
                endpoint=settings.retrieval_endpoint,
                shared_secret=settings.retrieval_shared_secret,
            )

        from app.retrieval.physics9.local import LocalRetriever

        return LocalRetriever(
            embeddings_path=settings.physics_embeddings_path or None,
            pages_dir=settings.physics_pages_dir or None,
        )
    except RetrievalUnavailableError as exc:
        logger.info("RETRIEVAL_MODE=%s unavailable (%s); using heuristic tier", mode, exc)
    except ValueError as exc:
        # A misconfiguration rather than an absence - e.g. RETRIEVAL_MODE=remote with no
        # RETRIEVAL_ENDPOINT. Loud, because it is silently answerable and should not be.
        logger.warning("RETRIEVAL_MODE=%s is misconfigured (%s); using heuristic tier", mode, exc)

    return HeuristicRetriever()


def get_physics_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = _build_retriever()
    return _retriever


def _get_fallback() -> HeuristicRetriever:
    """The degraded tier, held separately so a per-request remote failure has somewhere
    to go without rebuilding anything."""
    global _fallback
    if _fallback is None:
        _fallback = HeuristicRetriever()
    return _fallback


def get_physics_generator() -> PhysicsGenerator:
    global _generator
    if _generator is None:
        settings = get_settings()
        _generator = PhysicsGenerator(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            pages_dir=_pages_dir(),
        )
    return _generator


def _pages_dir():
    """Where the page scans live.

    Asked of the retriever when it knows (the local tier resolves it while loading), and
    resolved independently otherwise - the remote and heuristic tiers have no reason to
    know about image files, but generation still needs them.
    """
    from app.retrieval.physics9.local import _resolve_pages_dir

    settings = get_settings()
    retriever = get_physics_retriever()
    return getattr(retriever, "pages_dir", None) or _resolve_pages_dir(
        settings.physics_pages_dir or None
    )


def search(question: str, top_k: int = 3, chapter: int | None = None):
    """Retrieve, degrading to the heuristic tier if the configured one fails mid-request.

    Returns `(hits, timings, tier_name)`. A remote tier fails per-request, not just at
    startup - the host scales to zero or stops on a schedule - so the fallback has to
    live on this path and not only in construction.
    """
    retriever = get_physics_retriever()
    try:
        hits, timings = retriever.search(question, top_k=top_k, chapter=chapter)
        return hits, timings, retriever.name
    except RetrievalUnavailableError as exc:
        logger.warning("%s tier failed mid-request (%s); degrading", retriever.name, exc)

    fallback = _get_fallback()
    hits, timings = fallback.search(question, top_k=top_k, chapter=chapter)
    return hits, timings, fallback.name


def search_index(question: str, top_k: int = 3, chapter: int | None = None):
    """Keyword index only, bypassing the configured tier. Returns `(hits, timings)`.

    For an explicit reference - "chp 4 ex 4.5 q 3", "numerical 7.3". MaxSim over a
    150 DPI page scan is particularly bad at these: "7.3" is a handful of dark pixels
    on a page full of them, while the syllabus index maps the reference directly.

    ⚠️ This returns the heuristic tier by DESIGN, not by degradation. The caller must
    pass the intent through to the client, or a correct reference lookup is
    indistinguishable from the retrieval service being down.
    """
    return _get_fallback().search(question, top_k=top_k, chapter=chapter)


def answer_physics_query(
    question: str,
    lang: str = "en",
    history: list[dict[str, str]] | None = None,
    top_k: int = 3,
    chapter: int | None = None,
) -> dict[str, Any]:
    """Retrieve grounded textbook pages and generate a tutor response."""
    hits, timings, tier = search(question, top_k=top_k, chapter=chapter)
    reply, generate_s, gen_error = get_physics_generator().generate(
        question=question,
        hits=hits,
        history=history,
        lang=lang,
    )

    return {
        "reply": reply,
        "pages": hits,
        # `retriever` is not telemetry: a degraded answer must be visibly degraded, and
        # the client renders differently when keyword matching produced the citations.
        "retriever": tier,
        "timings": {
            "encode": round(timings.encode, 3),
            "search": round(timings.search, 4),
            "generate": round(generate_s, 3),
        },
        "gen_error": gen_error,
    }


def reset_for_tests() -> None:
    """Drop the cached tiers so a test can change `RETRIEVAL_MODE` and rebuild."""
    global _retriever, _fallback, _generator
    _retriever = _fallback = _generator = None


__all__ = [
    "Timings",
    "answer_physics_query",
    "get_physics_generator",
    "get_physics_retriever",
    "reset_for_tests",
    "search",
]
