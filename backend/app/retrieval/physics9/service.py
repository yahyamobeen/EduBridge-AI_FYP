"""Physics 9 Service coordinator.

Provides a unified interface combining retrieval and generation for Class 9 Physics tutoring.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.retrieval.physics9.generator import PhysicsGenerator
from app.retrieval.physics9.retriever import PhysicsRetriever

logger = logging.getLogger("edubridge.retrieval.physics9.service")

_retriever: PhysicsRetriever | None = None
_generator: PhysicsGenerator | None = None


def get_physics_retriever() -> PhysicsRetriever:
    global _retriever
    if _retriever is None:
        settings = get_settings()
        _retriever = PhysicsRetriever(
            embeddings_path=settings.physics_embeddings_path,
            pages_dir=settings.physics_pages_dir,
            load_model=False,  # Loaded lazily or on explicit config
        )
    return _retriever


def get_physics_generator() -> PhysicsGenerator:
    global _generator
    if _generator is None:
        settings = get_settings()
        retriever = get_physics_retriever()
        _generator = PhysicsGenerator(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            pages_dir=retriever.pages_dir,
        )
    return _generator


def answer_physics_query(
    question: str,
    lang: str = "en",
    history: list[dict[str, str]] | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """Retrieves grounded textbook pages and generates a tutor response."""
    retriever = get_physics_retriever()
    generator = get_physics_generator()

    hits, encode_s, search_s = retriever.search(question, top_k=top_k)
    reply, generate_s, gen_error = generator.generate(
        question=question,
        hits=hits,
        history=history,
        lang=lang,
    )

    return {
        "reply": reply,
        "pages": hits,
        "timings": {
            "encode": round(encode_s, 3),
            "search": round(search_s, 4),
            "generate": round(generate_s, 3),
        },
        "gen_error": gen_error,
    }
