"""Class 9 Physics visual retrieval (tdd.md §3.2a).

`base` holds the book structure and the `Retriever` protocol; `heuristic`, `remote` and
`local` implement it; `service` selects one and degrades between them. `local` is NOT
imported here - it needs the `[retrieval]` extra, which is absent wherever the backend
actually runs, so `service` imports it lazily inside a `try`.
"""

from app.retrieval.physics9.base import (
    BOOK_PAGES,
    CHAPTER_NAMES,
    CHAPTERS,
    Hit,
    RetrievalUnavailableError,
    Retriever,
    Timings,
    chapter_of,
    page_url,
)
from app.retrieval.physics9.generator import PhysicsGenerator
from app.retrieval.physics9.heuristic import HeuristicRetriever
from app.retrieval.physics9.service import (
    answer_physics_query,
    get_physics_generator,
    get_physics_retriever,
    search,
)

__all__ = [
    "BOOK_PAGES",
    "CHAPTERS",
    "CHAPTER_NAMES",
    "HeuristicRetriever",
    "Hit",
    "PhysicsGenerator",
    "RetrievalUnavailableError",
    "Retriever",
    "Timings",
    "answer_physics_query",
    "chapter_of",
    "get_physics_generator",
    "get_physics_retriever",
    "page_url",
    "search",
]
