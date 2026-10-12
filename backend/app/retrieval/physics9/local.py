"""In-process ColQwen2 retrieval (tdd.md §3.2a).

For a GPU box or a development machine. **Not** for the backend on Render: the model
needs ~5 GB resident at bfloat16 against a 512 MB instance, which is why `torch` and
`colpali-engine` live in the `[retrieval]` optional extra and not in
`requirements.txt`. `RETRIEVAL_MODE=remote` is the default for that reason.

Imports of `torch` are deliberately inside functions. At module scope they would make
this file unimportable wherever the extra is not installed - which is everywhere the
backend actually runs - and `service.py` needs to be able to try this tier and move on.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Lock

from app.retrieval.physics9.base import (
    BOOK_PAGES,
    CHAPTERS,
    Hit,
    RetrievalUnavailableError,
    Timings,
    chapter_of,
    make_hits,
)

logger = logging.getLogger("edubridge.retrieval.physics9.local")

# How strongly a session's anchored chapter is preferred, as a FRACTION of the score
# spread across the candidate pages - not an absolute number. MaxSim sums per-query-token
# maxima, so its scale differs between models and an absolute bonus tuned on ColQwen2
# would mean something else entirely on ColPali. Expressed relatively, the prior is
# scale-free: enough to win a near-tie, never enough to overturn a clear winner, which is
# what makes it a prior rather than a filter.
#
# ⚠️ Not yet validated against the evaluation set. Phase 9's full run is what sets it.
ANCHOR_PRIOR = 0.05


class LocalRetriever:
    """`RETRIEVAL_MODE=local`. Loads the embeddings and the query encoder in-process.

    Raises `RetrievalUnavailableError` from `__init__` when it cannot honestly serve as the
    local tier - a missing extra, a missing file, or a file that fails a guard. The
    caller degrades and reports `heuristic`, so a query is never scored by one model
    against another model's pages while the interface claims otherwise.
    """

    def __init__(
        self,
        embeddings_path: str | Path | None = None,
        pages_dir: str | Path | None = None,
        dtype: str = "bfloat16",
    ) -> None:
        self._lock = Lock()
        self._dtype_name = dtype
        self.emb_path = _resolve_embeddings_path(embeddings_path)
        self.pages_dir = _resolve_pages_dir(pages_dir)

        if self.emb_path is None:
            raise RetrievalUnavailableError("no embeddings file found; set PHYSICS_EMBEDDINGS_PATH")

        self.pages, self.docs, self.checkpoint, self.dim = _load_embeddings(self.emb_path)
        self.vectors_per_page = int(self.docs.shape[1])
        self._model, self._processor = _load_encoder(self.checkpoint, dtype)
        logger.info(
            "local retriever ready: %d pages, %d vectors/page, dim %d, %s, %s",
            len(self.pages),
            self.vectors_per_page,
            self.dim,
            self.checkpoint,
            dtype,
        )

    @property
    def name(self) -> str:
        return "local"

    def search(
        self, question: str, top_k: int = 3, chapter: int | None = None
    ) -> tuple[list[Hit], Timings]:
        import torch

        started = time.monotonic()
        # One model, one lock. The forward pass is the hot path and holds ~5 GB; two
        # concurrent passes would double neither throughput nor memory headroom, so
        # requests serialise here by design (tdd.md §3.2a, "Single instance").
        with self._lock:
            inputs = self._processor.process_queries([question]).to("cpu")
            with torch.no_grad():
                query = self._model(**inputs)[0].to(torch.float32)
            encode_s = time.monotonic() - started

            search_started = time.monotonic()
            # Late interaction: for each query token take its best-matching patch on the
            # page, then sum over query tokens. `docs` is stacked once at startup, so no
            # padding is allocated per request.
            similarity = torch.einsum("qd,pnd->pqn", query, self.docs)
            scores = similarity.max(dim=2).values.sum(dim=1)
            search_s = time.monotonic() - search_started

        if chapter is not None:
            scores = _apply_anchor(scores, self.pages, chapter)

        k = min(max(1, top_k), int(scores.numel()))
        top = torch.topk(scores, k)
        scored = [
            (self.pages[index], value)
            for value, index in zip(top.values.tolist(), top.indices.tolist(), strict=True)
        ]
        return make_hits(scored), Timings(encode=encode_s, search=search_s)


def _apply_anchor(scores, pages: list[int], chapter: int):
    """Add a relative bonus to pages in the anchored chapter. See `ANCHOR_PRIOR`."""
    if chapter not in CHAPTERS:
        return scores
    spread = float(scores.max() - scores.min())
    if spread <= 0.0:
        return scores
    bonus = ANCHOR_PRIOR * spread
    import torch

    mask = torch.tensor(
        [1.0 if chapter_of(page) == chapter else 0.0 for page in pages],
        dtype=scores.dtype,
    )
    return scores + mask * bonus


def _resolve_embeddings_path(override: str | Path | None) -> Path | None:
    """Find `pages.colqwen2.pt`, or None.

    ⚠️ The previous revision also searched a sibling directory named
    `edubridge-chatbot-SEND-THIS` - one contributor's local folder, which exists on no
    other machine and certainly not on a deployment host. Path guessing that works on
    exactly one laptop is worse than no path guessing, because it fails differently for
    everyone else. `PHYSICS_EMBEDDINGS_PATH` is the supported answer.
    """
    if override:
        candidate = Path(override)
        if candidate.exists():
            return candidate
        logger.warning("PHYSICS_EMBEDDINGS_PATH is set but does not exist: %s", candidate)
        return None

    backend_dir = Path(__file__).resolve().parents[3]
    for name in ("pages.colqwen2.pt", "pages.colpali.pt"):
        candidate = backend_dir / "data" / "physics9" / name
        if candidate.exists():
            return candidate
    return None


def _resolve_pages_dir(override: str | Path | None) -> Path | None:
    """Find the 200 page scans, or None. Generation needs them; search does not."""
    if override:
        candidate = Path(override)
        if candidate.exists() and candidate.is_dir():
            return candidate

    this_dir = Path(__file__).resolve().parent
    backend_dir = Path(__file__).resolve().parents[3]
    for candidate in (this_dir / "pages", backend_dir / "data" / "physics9" / "pages"):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _load_embeddings(path: Path):
    """Load and validate the page embeddings. Raises `RetrievalUnavailableError` on any doubt.

    Three guards, all before anything is served. They exist because the worst failure in
    this system is silent: scoring a ColQwen2 query against ColPali pages produces
    confidently wrong citations with no error anywhere, since both are 128-dimensional.
    The previous revision logged a warning and carried on into keyword mode while
    `/info` still reported the checkpoint - refusing is the point.
    """
    try:
        import torch
    except ImportError as exc:
        # Expected wherever the `[retrieval]` extra is not installed, which is every
        # deployment host. Not a misconfiguration; `service.py` logs it at info.
        raise RetrievalUnavailableError("torch is not installed ([retrieval] extra)") from exc

    try:
        store = torch.load(path, map_location="cpu", weights_only=False)
    except Exception as exc:
        raise RetrievalUnavailableError(
            f"could not read {path.name}: {type(exc).__name__}"
        ) from exc

    pages = store.get("pages", [])
    embeddings = store.get("embeddings", [])
    checkpoint = store.get("checkpoint", "")

    if sorted(pages) != list(range(1, BOOK_PAGES + 1)):
        missing = sorted(set(range(1, BOOK_PAGES + 1)) - set(pages))
        raise RetrievalUnavailableError(
            f"{path.name} does not cover pages 1-{BOOK_PAGES} (missing {missing[:5]})"
        )
    if len(pages) != len(embeddings):
        raise RetrievalUnavailableError(
            f"{path.name} has {len(pages)} pages against {len(embeddings)} embeddings"
        )
    if not store.get("complete", True):
        raise RetrievalUnavailableError(f"{path.name} is marked incomplete")

    # Stacked once, in float32, so no per-request cast or padding allocation. 200 x 755 x
    # 128 float32 is ~77 MB - the reason this tier is not viable on a 512 MB instance even
    # before the model loads.
    docs = torch.stack([tensor.to(torch.float32) for tensor in embeddings])
    return pages, docs, checkpoint, int(store.get("dim", 128))


def _load_encoder(checkpoint: str, dtype: str):
    """Load the query encoder matching `checkpoint`.

    The model class is chosen from the checkpoint name, not configured separately: a
    `colqwen2` checkpoint loaded through `ColPali` is the same silent cross-model failure
    the embedding guards exist to prevent, one level up.
    """
    try:
        import colpali_engine.models as models
        import torch
    except ImportError as exc:
        raise RetrievalUnavailableError(
            "colpali-engine is not installed ([retrieval] extra)"
        ) from exc

    is_qwen = "qwen" in checkpoint.lower()
    model_class = "ColQwen2" if is_qwen else "ColPali"
    processor_class = "ColQwen2Processor" if is_qwen else "ColPaliProcessor"

    # bfloat16 by default. ⚠️ On a CPU without AVX512-BF16 or AMX this is a FIT decision,
    # not a speed one - PyTorch materialises an fp32 temporary per matmul, measured ~3x
    # slower than float32 on Whiskey Lake. On Sapphire Rapids (AMX) it is genuinely the
    # fast path. float32 needs ~9.4 GB and will not fit on the deployment target.
    torch_dtype = getattr(torch, dtype)

    try:
        model = (
            getattr(models, model_class)
            .from_pretrained(checkpoint, torch_dtype=torch_dtype, device_map="cpu")
            .eval()
        )
        processor = getattr(models, processor_class).from_pretrained(checkpoint)
    except Exception as exc:
        raise RetrievalUnavailableError(
            f"could not load {checkpoint}: {type(exc).__name__}"
        ) from exc

    return model, processor
