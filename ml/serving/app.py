"""ColQwen2 retrieval service for the textbook tutor (tdd.md §3.2a).

A single-purpose appliance: it answers "which pages of THIS book match this string" and
knows nothing about students, sessions, authentication or Gemini. Those stay in the
backend. This process exists separately for one reason - the model needs ~5 GB resident
at bfloat16 and the backend runs on a 512 MB instance.

One instance serves every book (tdd.md §3.2a "Many books"): one model, one query cache,
and every book's page index. A question's embedding does not depend on the book, so only
the final MaxSim step is per book. Two ways to load books:

- `INDEX_DIR` - a folder of book folders `<book_id>/<book_id>.colqwen2.pt`, the layout
  `ml/indexing` writes. Optionally narrowed by `BOOKS` (comma-separated ids).
- `PAGES_PT` - one file, served as book `PAGES_BOOK` (default `Punjab_9_Physics`). This is
  the original single-book deployment and what the Docker image bakes in.

Deliberately NOT importable from `backend/`: it is a separate deployable with its own
dependency set, and `backend/requirements.txt` must never grow a torch dependency. It
holds no chapter tables: the backend turns a chapter into the page range it sends as
`anchor`.

Run with ONE worker. Each worker loads its own copy of the model.

    uvicorn app:app --host 127.0.0.1 --port 8100 --workers 1
"""

from __future__ import annotations

import contextlib
import hmac
import logging
import os
import sys
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# Windows consoles default to cp1252 and die on Urdu inside the error handler, which
# surfaces as an unrelated failure. Harmless on Linux, where this actually deploys.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("retrieval")

INDEX_DIR = os.environ.get("INDEX_DIR", "")
BOOKS = [b.strip() for b in os.environ.get("BOOKS", "").split(",") if b.strip()]
EMBEDDINGS_PATH = Path(os.environ.get("PAGES_PT", "/srv/model/pages.colqwen2.pt"))
PAGES_BOOK = os.environ.get("PAGES_BOOK", "Punjab_9_Physics")
EXPECTED_CHECKPOINT = os.environ.get("EXPECTED_CHECKPOINT", "vidore/colqwen2-v1.0")
DTYPE = os.environ.get("DTYPE", "bfloat16")
SHARED_SECRET = os.environ.get("RETRIEVAL_SHARED_SECRET", "")
CACHE_SIZE = int(os.environ.get("CACHE_SIZE", "512"))

# The query model is pinned to the revisions `ml/indexing` encodes pages with, so pages
# and questions come from the same weights. `revision=` together with the hub id raises
# RevisionNotFoundError (transformers swaps the id for the base and reuses the revision),
# so the adapter is fetched at its revision first and the base revision is handed to
# from_pretrained, which only fetches the files the model needs.
PINNED_REVISIONS = {
    "vidore/colqwen2-v1.0": (
        "2b6ac8fb37f46a49e4841e599583d00ae8a20117",  # adapter
        "9fe8a713422a7cb4ef79ca77a09b381ee2243101",  # vidore/colqwen2-base
    ),
}

# How long a request will wait for the model before giving up. ⚠️ MUST stay below the
# backend's own read timeout (20 s in `remote.py`), or the backend abandons the request
# first and the 503 this produces never reaches anyone - the caller sees a transport
# error instead of a clean "busy", and degrades for the wrong reason. One model answers
# one query at a time, so at ~6 s per encode this allows a queue of about two.
MAX_WAIT_S = float(os.environ.get("MAX_WAIT_S", "15"))

# Matches `ANCHOR_PRIOR` in the backend's `local.py`, and for the same reason: a fraction
# of the score spread rather than an absolute bonus, because MaxSim's scale differs
# between models. Enough to win a near-tie, never enough to overturn a clear winner.
ANCHOR_PRIOR = float(os.environ.get("ANCHOR_PRIOR", "0.05"))


def normalise(question: str) -> str:
    """Cache key. Case and whitespace only.

    Deliberately does NOT strip punctuation or stem: "what is heat" and "what is heat
    capacity" must not collapse onto one entry, and an over-eager key would serve the
    wrong pages confidently. Lowercasing is a no-op for Urdu script, which is fine - it
    just means those queries key on themselves. The key has no book in it on purpose:
    the embedding of a question is the same whichever book is searched.
    """
    return " ".join(question.lower().split())


@dataclass
class Book:
    """One book's pages, held in bfloat16 (lossless: the model computes in bfloat16)."""

    book_id: str
    pages: list[int]
    docs: Any  # (pages, vectors, dim) bfloat16 tensor


def discover(index_dir: Path, allow: list[str]) -> list[tuple[str, Path]]:
    """(book_id, path) for every `<id>/<id>.colqwen2.pt` under index_dir, sorted."""
    found = []
    for folder in sorted(p for p in index_dir.iterdir() if p.is_dir()):
        path = folder / f"{folder.name}.colqwen2.pt"
        if path.is_file() and (not allow or folder.name in allow):
            found.append((folder.name, path))
    missing = sorted(set(allow) - {book_id for book_id, _ in found})
    if missing:
        raise SystemExit(f"BOOKS names books not found under {index_dir}: {missing}")
    return found


class Index:
    """Every book's page embeddings, the query encoder, and the query-embedding cache."""

    def __init__(self) -> None:
        self.books: dict[str, Book] = {}
        self.checkpoint = ""
        self.vectors_per_page = 0
        self.dim = 0
        # Guards the model's forward pass. One model, one pass at a time.
        self._model_lock = Lock()
        # Separate and short-lived: held for microseconds around a dict operation, so a
        # cache hit never queues behind a 6-second forward pass.
        self._cache_lock = Lock()
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self._model = None
        self._processor = None

    @property
    def total_pages(self) -> int:
        return sum(len(book.pages) for book in self.books.values())

    # -- startup ---------------------------------------------------------------

    def sources(self) -> list[tuple[str, Path]]:
        if INDEX_DIR:
            index_dir = Path(INDEX_DIR)
            if not index_dir.is_dir():
                raise SystemExit(f"INDEX_DIR {index_dir} is not a folder")
            found = discover(index_dir, BOOKS)
            if not found:
                raise SystemExit(f"no <book>/<book>.colqwen2.pt under INDEX_DIR {index_dir}")
            return found
        if not EMBEDDINGS_PATH.exists():
            raise SystemExit(
                f"embeddings not found at {EMBEDDINGS_PATH}; set PAGES_PT or INDEX_DIR"
            )
        return [(PAGES_BOOK, EMBEDDINGS_PATH)]

    def load(self) -> None:
        """Validate every book, then load the model. Order matters.

        Every guard runs BEFORE the ~5 GB model load, so a mispaired file fails in
        seconds instead of after a two-minute load. `SystemExit` rather than a degraded
        mode: this process has exactly one job, and a process that cannot do it
        correctly must not accept traffic. The backend degrades; this does not. One bad
        book therefore refuses the whole start - narrow `BOOKS` to leave it out.
        """
        started = time.monotonic()
        for book_id, path in self.sources():
            self.books[book_id] = self._load_book(book_id, path)
        logger.info(
            "embeddings OK: %d book(s), %d pages, %d vectors/page, dim %d, checkpoint %s, %.1fs",
            len(self.books),
            self.total_pages,
            self.vectors_per_page,
            self.dim,
            self.checkpoint,
            time.monotonic() - started,
        )
        self._load_model()

    def _load_book(self, book_id: str, path: Path) -> Book:
        import torch

        # weights_only=True refuses pickled code; the files are plain dicts of tensors,
        # lists and strings (ml/indexing guarantees it, and the original Physics file
        # loads the same way). mmap keeps the load peak near one book, not two copies.
        store = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
        name = path.name
        checkpoint = store.get("checkpoint", "")
        pages = store.get("pages", [])
        embeddings = store.get("embeddings", [])

        # Guard 1: the checkpoint that produced these pages must be the one we will
        # encode queries with. THIS IS THE IMPORTANT ONE. A ColQwen2 query scored
        # against ColPali pages produces confidently wrong citations and no error
        # anywhere, because both are 128-dimensional. It is the worst failure in the
        # system precisely because nothing reports it.
        if checkpoint != EXPECTED_CHECKPOINT:
            raise SystemExit(
                f"checkpoint mismatch: {name} holds '{checkpoint}', expected "
                f"'{EXPECTED_CHECKPOINT}'. Refusing to start - scoring one model's query "
                f"against another's pages is silent."
            )
        self.checkpoint = checkpoint

        # Guard 2: the file is the book it claims to be. The original single-book file
        # predates the field, which is why a missing book_id is accepted.
        stored_id = store.get("book_id")
        if stored_id is not None and stored_id != book_id:
            raise SystemExit(f"{name} holds book '{stored_id}' but is loaded as '{book_id}'")

        # Guard 3: a partial encode must not look complete. Pages exactly 1..N.
        expected = store.get("expected_pages") or len(pages)
        if sorted(pages) != list(range(1, expected + 1)):
            missing = sorted(set(range(1, expected + 1)) - set(pages))
            raise SystemExit(
                f"{name} does not cover pages 1-{expected}; "
                f"missing {missing[:10]}{' ...' if len(missing) > 10 else ''}"
            )

        # Guard 4: the page list indexes into the embedding list. A length mismatch
        # means every citation is off by an unknown amount.
        if len(pages) != len(embeddings):
            raise SystemExit(
                f"{name} has {len(pages)} pages against {len(embeddings)} embeddings; "
                f"the page mapping is broken"
            )

        if not store.get("complete", True):
            raise SystemExit(f"{name} is marked incomplete")

        # Stacked once, at startup. Every page must have the same shape; a mismatch is a
        # broken file, reported as one rather than as a bare RuntimeError.
        try:
            docs = torch.stack([tensor.to(torch.bfloat16) for tensor in embeddings])
        except RuntimeError as exc:
            raise SystemExit(f"{name}: pages have different shapes ({exc})") from exc
        vectors, dim = int(docs.shape[1]), int(docs.shape[2])
        if self.books and (vectors, dim) != (self.vectors_per_page, self.dim):
            raise SystemExit(
                f"{name}: {vectors}x{dim} per page, but other books are "
                f"{self.vectors_per_page}x{self.dim}"
            )
        self.vectors_per_page, self.dim = vectors, dim
        order = sorted(range(len(pages)), key=lambda i: pages[i])
        return Book(book_id, [int(pages[i]) for i in order], docs[order])

    def _load_model(self) -> None:
        import colpali_engine.models as models
        import torch

        is_qwen = "qwen" in self.checkpoint.lower()
        model_class = "ColQwen2" if is_qwen else "ColPali"
        processor_class = "ColQwen2Processor" if is_qwen else "ColPaliProcessor"

        # Threads: one per PHYSICAL core, and interop set to 1. Oversubscribing with
        # hyperthreads makes a GEMM-bound workload slower, not faster, and both calls
        # must happen before any parallel work begins or torch ignores them.
        if (threads := os.environ.get("TORCH_THREADS")) is not None:
            torch.set_num_threads(int(threads))
        # Already initialised is harmless, and only possible if something touched
        # torch's parallel machinery before us.
        with contextlib.suppress(RuntimeError):
            torch.set_num_interop_threads(1)

        started = time.monotonic()
        dtype = getattr(torch, DTYPE)
        pinned = PINNED_REVISIONS.get(self.checkpoint)
        if pinned:
            from huggingface_hub import snapshot_download

            adapter = snapshot_download(self.checkpoint, revision=pinned[0])
            self._model = (
                getattr(models, model_class)
                .from_pretrained(adapter, revision=pinned[1], dtype=dtype, device_map="cpu")
                .eval()
            )
            self._processor = getattr(models, processor_class).from_pretrained(adapter)
        else:
            self._model = (
                getattr(models, model_class)
                .from_pretrained(self.checkpoint, dtype=dtype, device_map="cpu")
                .eval()
            )
            self._processor = getattr(models, processor_class).from_pretrained(self.checkpoint)
        logger.info(
            "%s loaded in %.1fs at %s (%s), %d torch threads",
            model_class,
            time.monotonic() - started,
            DTYPE,
            f"pinned {pinned[0][:8]}/{pinned[1][:8]}" if pinned else "unpinned",
            torch.get_num_threads(),
        )

    # -- query path ------------------------------------------------------------

    def _cached(self, key: str):
        with self._cache_lock:
            embedding = self._cache.get(key)
            if embedding is not None:
                self._cache.move_to_end(key)
                self.hits += 1
                return embedding
            self.misses += 1
            return None

    def _store(self, key: str, embedding) -> None:
        with self._cache_lock:
            self._cache[key] = embedding
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)

    def encode(self, question: str) -> tuple[Any, float, bool]:
        """The query embedding, its cost in seconds, and whether it was cached.

        A cache hit returns WITHOUT touching the model lock. That is the whole point:
        with one serialised model, a repeated question must not queue behind a novel
        one. In a classroom the same questions repeat constantly, which is why
        `tdd.md:759` makes the cache the mechanism that satisfies NFR-1 rather than the
        model's raw speed.
        """
        import torch

        key = normalise(question)
        if (cached := self._cached(key)) is not None:
            return cached, 0.0, True

        acquired = self._model_lock.acquire(timeout=MAX_WAIT_S)
        if not acquired:
            # Busy, not broken. The backend turns this into a degraded answer from its
            # keyword tier (Physics 9) or a "not available right now" (other books).
            raise HTTPException(
                status_code=503,
                detail=f"model busy; waited {MAX_WAIT_S:.0f}s",
            )
        try:
            # Re-check: another thread may have encoded this exact query while we
            # queued. Without this, a burst of identical questions - which is what a
            # classroom produces - each pays full price.
            if (cached := self._cached(key)) is not None:
                return cached, 0.0, True

            started = time.monotonic()
            inputs = self._processor.process_queries([question]).to("cpu")
            with torch.no_grad():
                embedding = self._model(**inputs)[0].to(torch.float32)
            elapsed = time.monotonic() - started
        finally:
            self._model_lock.release()

        self._store(key, embedding)
        return embedding, elapsed, False

    def book(self, book_id: str) -> Book:
        book = self.books.get(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail=f"book '{book_id}' is not loaded")
        return book

    def search(
        self, book_id: str, question: str, top_k: int, anchor: tuple[int, int] | None
    ) -> tuple[list[int], list[float], float, float, bool]:
        import torch

        book = self.book(book_id)
        if anchor is not None and not 1 <= anchor[0] <= anchor[1] <= len(book.pages):
            raise HTTPException(
                status_code=400,
                detail=f"anchor {list(anchor)} is outside pages 1-{len(book.pages)}",
            )
        embedding, encode_s, was_cached = self.encode(question)

        started = time.monotonic()
        # Late interaction: each query token takes its best-matching patch on the page,
        # then sum over query tokens. Only the requested book is cast to float32 - at
        # most ~170 MB for a 440-page book, tens of milliseconds against a 6 s encode -
        # so every book stays resident in bfloat16 and nothing else is allocated. The
        # page tensors are read-only after startup, so this runs outside the model lock
        # and cache hits are fully concurrent.
        docs = book.docs.to(torch.float32)
        similarity = torch.einsum("qd,pnd->pqn", embedding, docs)
        scores = similarity.max(dim=2).values.sum(dim=1)

        if anchor is not None:
            scores = self._apply_anchor(scores, book, anchor)

        k = min(max(1, top_k), int(scores.numel()))
        top = torch.topk(scores, k)
        search_s = time.monotonic() - started

        pages = [book.pages[index] for index in top.indices.tolist()]
        return pages, [round(v, 4) for v in top.values.tolist()], encode_s, search_s, was_cached

    def _apply_anchor(self, scores, book: Book, anchor: tuple[int, int]):
        """A prior, never a filter. Applied BEFORE top-k, which is why it lives here
        and not in the backend - the backend only sees pages that already survived."""
        import torch

        spread = float(scores.max() - scores.min())
        if spread <= 0.0:
            return scores
        first, last = anchor
        mask = torch.tensor(
            [1.0 if first <= page <= last else 0.0 for page in book.pages],
            dtype=scores.dtype,
        )
        return scores + mask * (ANCHOR_PRIOR * spread)


index = Index()


@asynccontextmanager
async def lifespan(_: FastAPI):
    index.load()
    # Warm up, so the first real query is not the one that pays for lazy kernel
    # initialisation - otherwise the first measurement of the day is an outlier and the
    # first student of the day waits for it.
    started = time.monotonic()
    index.search(next(iter(index.books)), "warmup", 1, None)
    # The warmup must not pollute the cache or the hit-rate statistics it would
    # otherwise inflate.
    index._cache.clear()
    index.hits = index.misses = 0
    logger.info("warmed up in %.1fs; ready", time.monotonic() - started)
    yield


app = FastAPI(title="EduBridge retrieval (textbook pages)", lifespan=lifespan)


class RetrieveRequest(BaseModel):
    # Optional so an older backend, which sends no book, still gets the single book it
    # was written for. Extra fields from that backend (`chapter`) are ignored.
    book: str | None = Field(default=None, min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)
    anchor: tuple[int, int] | None = None


def resolve_book_id(requested: str | None) -> str:
    if requested is not None:
        return requested
    if len(index.books) == 1:
        return next(iter(index.books))
    return PAGES_BOOK


def _check_secret(provided: str | None) -> None:
    """Constant-time comparison. An empty configured secret disables the check, which
    is only acceptable because the service also binds to 127.0.0.1 behind its tunnel."""
    if not SHARED_SECRET:
        return
    if not provided or not hmac.compare_digest(provided, SHARED_SECRET):
        raise HTTPException(status_code=401, detail="bad or missing retrieval secret")


@app.post("/retrieve")
def retrieve(
    payload: RetrieveRequest,
    x_retrieval_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Rank one book's pages against a question.

    A sync `def` on purpose: FastAPI runs it in a threadpool, so a multi-second
    blocking forward pass does not stall the event loop. `async def` here would freeze
    every other request, including `/health`.
    """
    _check_secret(x_retrieval_secret)
    book_id = resolve_book_id(payload.book)
    pages, scores, encode_s, search_s, was_cached = index.search(
        book_id, payload.question, payload.top_k, payload.anchor
    )
    return {
        "book": book_id,
        "pages": pages,
        "scores": scores,
        "encode_ms": round(encode_s * 1000, 2),
        "search_ms": round(search_s * 1000, 2),
        "cached": was_cached,
        "checkpoint": index.checkpoint,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    """Readiness and the numbers worth watching. No secret required - a health check
    that needs a credential is one the platform cannot use."""
    total = index.hits + index.misses
    return {
        "status": "ok" if index.books else "loading",
        "checkpoint": index.checkpoint,
        "books": sorted(index.books),
        "pages": index.total_pages,
        "vectors_per_page": index.vectors_per_page,
        "dim": index.dim,
        "dtype": DTYPE,
        "cache": {
            "size": len(index._cache),
            "capacity": CACHE_SIZE,
            "hits": index.hits,
            "misses": index.misses,
            "hit_rate": round(index.hits / total, 3) if total else None,
        },
    }
