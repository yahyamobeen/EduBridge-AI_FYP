"""ColQwen2 retrieval service for PCTB Physics 9 (tdd.md §3.2a).

A single-purpose appliance: it answers "which textbook pages match this string" and
knows nothing about students, sessions, authentication or Gemini. Those stay in the
backend. This process exists separately for one reason - the model needs ~5 GB resident
at bfloat16 and the backend runs on a 512 MB instance.

Deliberately NOT importable from `backend/`: it is a separate deployable with its own
dependency set, and `backend/requirements.txt` must never grow a torch dependency. The
small amount of duplicated knowledge (the book is 200 pages; chapter page ranges) is the
price of that separation, and is cheaper than a shared package built for two constants.

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

BOOK_PAGES = 200

# Chapter page ranges, duplicated from the backend on purpose - see the module docstring.
# Needed here because the anchor prior must be applied BEFORE top-k selection, and the
# backend only ever sees the pages that survived it.
CHAPTERS: dict[int, tuple[int, int]] = {
    1: (5, 27),
    2: (28, 51),
    3: (52, 79),
    4: (80, 104),
    5: (105, 126),
    6: (127, 147),
    7: (148, 160),
    8: (161, 180),
    9: (181, 193),
}

EMBEDDINGS_PATH = Path(os.environ.get("PAGES_PT", "/srv/model/pages.colqwen2.pt"))
EXPECTED_CHECKPOINT = os.environ.get("EXPECTED_CHECKPOINT", "vidore/colqwen2-v1.0")
DTYPE = os.environ.get("DTYPE", "bfloat16")
SHARED_SECRET = os.environ.get("RETRIEVAL_SHARED_SECRET", "")
CACHE_SIZE = int(os.environ.get("CACHE_SIZE", "512"))

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


def chapter_of(page: int) -> int | None:
    for chapter, (first, last) in CHAPTERS.items():
        if first <= page <= last:
            return chapter
    return None


def normalise(question: str) -> str:
    """Cache key. Case and whitespace only.

    Deliberately does NOT strip punctuation or stem: "what is heat" and "what is heat
    capacity" must not collapse onto one entry, and an over-eager key would serve the
    wrong pages confidently. Lowercasing is a no-op for Urdu script, which is fine - it
    just means those queries key on themselves.
    """
    return " ".join(question.lower().split())


class Index:
    """The stacked page embeddings, the query encoder, and the query-embedding cache."""

    def __init__(self) -> None:
        self.pages: list[int] = []
        self.docs: Any = None
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

    # -- startup ---------------------------------------------------------------

    def load(self) -> None:
        """Validate the embeddings, then load the model. Order matters.

        Every guard runs BEFORE the ~5 GB model load, so a mispaired file fails in
        seconds instead of after a two-minute load. `SystemExit` rather than a degraded
        mode: this process has exactly one job, and a process that cannot do it
        correctly must not accept traffic. The backend degrades; this does not.
        """
        import torch

        if not EMBEDDINGS_PATH.exists():
            raise SystemExit(f"embeddings not found at {EMBEDDINGS_PATH}; set PAGES_PT")

        # weights_only=False executes pickle, so this file must be one we control. It is
        # baked into the image at build time and never fetched at runtime.
        store = torch.load(EMBEDDINGS_PATH, map_location="cpu", weights_only=False)

        self.checkpoint = store.get("checkpoint", "")
        pages = store.get("pages", [])
        embeddings = store.get("embeddings", [])

        # Guard 1: the checkpoint that produced these pages must be the one we will
        # encode queries with. THIS IS THE IMPORTANT ONE. A ColQwen2 query scored
        # against ColPali pages produces confidently wrong citations and no error
        # anywhere, because both are 128-dimensional. It is the worst failure in the
        # system precisely because nothing reports it.
        if self.checkpoint != EXPECTED_CHECKPOINT:
            raise SystemExit(
                f"checkpoint mismatch: {EMBEDDINGS_PATH.name} holds "
                f"'{self.checkpoint}', expected '{EXPECTED_CHECKPOINT}'. Refusing to "
                f"start - scoring one model's query against another's pages is silent."
            )

        # Guard 2: a partial encode must not look complete. Pages exactly 1..200.
        if sorted(pages) != list(range(1, BOOK_PAGES + 1)):
            missing = sorted(set(range(1, BOOK_PAGES + 1)) - set(pages))
            raise SystemExit(
                f"{EMBEDDINGS_PATH.name} does not cover pages 1-{BOOK_PAGES}; "
                f"missing {missing[:10]}{' ...' if len(missing) > 10 else ''}"
            )

        # Guard 3: the page list indexes into the embedding list. A length mismatch
        # means every citation is off by an unknown amount.
        if len(pages) != len(embeddings):
            raise SystemExit(
                f"{EMBEDDINGS_PATH.name} has {len(pages)} pages against "
                f"{len(embeddings)} embeddings; the page mapping is broken"
            )

        if not store.get("complete", True):
            raise SystemExit(f"{EMBEDDINGS_PATH.name} is marked incomplete")

        self.pages = pages
        # Stacked once, float32, at startup - so no per-request cast and no padding
        # allocation on the hot path. ~77 MB for 200 x 755 x 128.
        self.docs = torch.stack([tensor.to(torch.float32) for tensor in embeddings])
        self.vectors_per_page = int(self.docs.shape[1])
        self.dim = int(self.docs.shape[2])
        logger.info(
            "embeddings OK: %d pages, %d vectors/page, dim %d, checkpoint %s",
            len(self.pages),
            self.vectors_per_page,
            self.dim,
            self.checkpoint,
        )

        self._load_model()

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
        self._model = (
            getattr(models, model_class)
            .from_pretrained(self.checkpoint, torch_dtype=getattr(torch, DTYPE), device_map="cpu")
            .eval()
        )
        self._processor = getattr(models, processor_class).from_pretrained(self.checkpoint)
        logger.info(
            "%s loaded in %.1fs at %s, %d torch threads",
            model_class,
            time.monotonic() - started,
            DTYPE,
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
            # keyword tier rather than an error the student sees.
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

    def search(
        self, question: str, top_k: int, chapter: int | None
    ) -> tuple[list[int], list[float], float, float, bool]:
        import torch

        embedding, encode_s, was_cached = self.encode(question)

        started = time.monotonic()
        # Late interaction: each query token takes its best-matching patch on the page,
        # then sum over query tokens. `docs` is read-only after startup, so this runs
        # outside the model lock and cache hits are fully concurrent.
        similarity = torch.einsum("qd,pnd->pqn", embedding, self.docs)
        scores = similarity.max(dim=2).values.sum(dim=1)

        if chapter is not None:
            scores = self._apply_anchor(scores, chapter)

        k = min(max(1, top_k), int(scores.numel()))
        top = torch.topk(scores, k)
        search_s = time.monotonic() - started

        pages = [self.pages[index] for index in top.indices.tolist()]
        return pages, [round(v, 4) for v in top.values.tolist()], encode_s, search_s, was_cached

    def _apply_anchor(self, scores, chapter: int):
        """A prior, never a filter. Applied BEFORE top-k, which is why it lives here
        and not in the backend - the backend only sees pages that already survived."""
        import torch

        if chapter not in CHAPTERS:
            return scores
        spread = float(scores.max() - scores.min())
        if spread <= 0.0:
            return scores
        mask = torch.tensor(
            [1.0 if chapter_of(page) == chapter else 0.0 for page in self.pages],
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
    index.search("warmup", 1, None)
    # The warmup must not pollute the cache or the hit-rate statistics it would
    # otherwise inflate.
    index._cache.clear()
    index.hits = index.misses = 0
    logger.info("warmed up in %.1fs; ready", time.monotonic() - started)
    yield


app = FastAPI(title="EduBridge retrieval (Physics 9)", lifespan=lifespan)


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)
    chapter: int | None = Field(default=None, ge=1, le=9)


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
    """Rank pages against a question.

    A sync `def` on purpose: FastAPI runs it in a threadpool, so a multi-second
    blocking forward pass does not stall the event loop. `async def` here would freeze
    every other request, including `/health`.
    """
    _check_secret(x_retrieval_secret)
    pages, scores, encode_s, search_s, was_cached = index.search(
        payload.question, payload.top_k, payload.chapter
    )
    return {
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
        "status": "ok" if index.docs is not None else "loading",
        "checkpoint": index.checkpoint,
        "pages": len(index.pages),
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
