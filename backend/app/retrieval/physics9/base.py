"""Shared vocabulary for Class 9 Physics retrieval (tdd.md §3.2a).

Holds the book's structure, the hit/timing shapes, and the `Retriever` protocol the
three implementations satisfy. Nothing here imports torch, httpx or the model — so a
module that only needs `chapter_of()` does not pull in a retrieval backend.

⚠️ This is NOT the `Retriever` of tdd.md §3.4. That one is `search(query, filters)`
with a separate `rerank()`, over BGE-M3 text embeddings and `curriculum_item` ids. This
one has no `filters` (there is no metadata to filter on), no `rerank` (late interaction
*is* the ranking) and returns `Timings` (the pilot exists to be measured). The contract
records both on purpose; they must not be collapsed before the knowledge base lands.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol, TypedDict

# Windows consoles default to cp1252, which cannot encode Urdu. Any path that prints a
# question - a traceback, a debug line - dies inside the error handler and surfaces as
# an unrelated failure. This bit the project twice. Render runs UTF-8 already; this is
# for Windows development.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Chapter page ranges from the official PCTB Class 9 Physics textbook (Contents, p6).
# Pages outside every range are front or back matter and belong to no chapter.
CHAPTERS: dict[int, tuple[int, int]] = {
    1: (5, 27),  # Physical Quantities and Measurements
    2: (28, 51),  # Kinematics
    3: (52, 79),  # Dynamics
    4: (80, 104),  # Turning Effects of Force
    5: (105, 126),  # Work, Energy and Power
    6: (127, 147),  # Mechanical Properties of Matter
    7: (148, 160),  # Thermal Properties of Matter
    8: (161, 180),  # Magnetism
    9: (181, 193),  # Nature of Science
}

CHAPTER_NAMES: dict[int, str] = {
    1: "Physical Quantities and Measurements",
    2: "Kinematics",
    3: "Dynamics",
    4: "Turning Effects of Force",
    5: "Work, Energy and Power",
    6: "Mechanical Properties of Matter",
    7: "Thermal Properties of Matter",
    8: "Magnetism",
    9: "Nature of Science",
}

BOOK_PAGES = 200


class RetrievalUnavailableError(Exception):
    """A retrieval tier could not answer, and the caller should degrade to another.

    Deliberately NOT an `AppError`: this is an internal signal, not a response. A
    retrieval backend being cold is something the student should never see - the
    service falls through to the heuristic tier and reports which tier answered. Only
    an exhausted fallback chain becomes `503 MODEL_UNAVAILABLE` (tdd.md §7.3).

    Its message names the failure class, never an endpoint, header or secret.
    """


class Hit(TypedDict):
    """One retrieved page.

    A plain dict rather than a dataclass because this is the JSON that reaches the
    client almost unchanged - `tutor/routes.py` builds its response model straight
    from these keys, and a dataclass would add a conversion step for nothing.

    `score` is comparable only WITHIN one retriever. MaxSim sums per-query-token
    maxima, and the models differ in both token count and patch count, so "14.2 beats
    11.8" across models is meaningless (tdd.md §8.2, `SIM_THRESHOLD`). The heuristic
    tier's scores are not similarities at all - they are rank placeholders.
    """

    page: int
    chapter: int | None
    score: float
    url: str


@dataclass(frozen=True)
class Timings:
    """Seconds spent encoding the query and searching the index.

    Separate fields because they answer different questions: `encode` is the hot path
    that decides whether this approach is viable at all, and `search` is the part a
    vector database would claim to improve (it is ~18 ms over 200 pages, which is why
    the pilot has no vector database - tdd.md §3.2a).
    """

    encode: float = 0.0
    search: float = 0.0


def chapter_of(page: int) -> int | None:
    """The chapter containing `page`, or None for front and back matter."""
    for chapter, (first, last) in CHAPTERS.items():
        if first <= page <= last:
            return chapter
    return None


def page_url(page: int) -> str:
    """The API path serving one page scan.

    One definition because it was previously written out at two call sites in the same
    function, and a citation whose URL does not resolve is indistinguishable from a
    retrieval failure in the interface.
    """
    return f"/api/tutor/class9/physics/pages/{page}"


def make_hits(scored: list[tuple[int, float]]) -> list[Hit]:
    """Build the wire shape from (page, score) pairs, in the order given.

    Order is the ranking and is never re-sorted here: the heuristic tier's scores are
    rank placeholders, so sorting by score would be a no-op at best and would discard
    a deliberate ordering at worst.
    """
    return [
        Hit(page=page, chapter=chapter_of(page), score=round(float(score), 3), url=page_url(page))
        for page, score in scored
    ]


class Retriever(Protocol):
    """What the tutor service needs from a retrieval backend.

    Three implementations: `RemoteRetriever` (HTTP, the default), `LocalRetriever`
    (in-process torch) and `HeuristicRetriever` (keyword index, also the degraded
    path). `RETRIEVAL_MODE` selects one. See tdd.md §3.2a.
    """

    @property
    def name(self) -> str:
        """Which tier answered - `remote`, `local` or `heuristic`.

        Reported to the client on the `pages` event. A degraded answer must be
        visibly degraded: silently serving keyword matches while the interface implies
        neural retrieval is the failure mode this field exists to prevent.
        """
        ...

    def search(
        self, question: str, top_k: int = 3, chapter: int | None = None
    ) -> tuple[list[Hit], Timings]:
        """Rank textbook pages against `question`, best first.

        `chapter`, when given, is the session anchor and acts as a score PRIOR, never a
        filter. Hard-scoping to the anchored chapter makes a prerequisite question
        ("what is a mole again?") fail silently, so an out-of-chapter page still wins
        when it scores better (tdd.md §5.3f).
        """
        ...
