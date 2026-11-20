"""Build ColQwen2 page indexes for every Punjab and Sindh textbook (tdd.md section 3.2a).

One self-contained tool for a CUDA machine. For each book PDF named
`<Board>_<Class>_<Subject>.pdf` it renders every page to the canvas the retrieval service
expects, encodes the pages with ColQwen2 at pinned revisions, and writes
`<book_id>.colqwen2.pt` - a file `ml/serving/app.py` and the backend's `local.py` load
without changes. Page images and a manifest are written next to it.

Commands, in the order they are run (README.md is the full runbook):

    python encode_books.py calibrate                 # environment + model vs reference
    python encode_books.py preflight --input DATA    # names, PDFs, coverage, estimates
    python encode_books.py run --input DATA --out out [--books GLOB ...]
    python encode_books.py verify --out out [--input DATA]
    python encode_books.py compare A.pt B.pt
    python encode_books.py make-reference --index pages.colqwen2.pt   # owner only

All console output is ASCII, so a cp1252 Windows console can never crash on it.
"""

from __future__ import annotations

import os

# Must be set before huggingface_hub is imported anywhere: it reads it once at import.
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

import argparse
import contextlib
import ctypes
import fnmatch
import gc
import hashlib
import io
import json
import platform
import re
import shutil
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import torch

# Windows consoles default to cp1252 and die on Urdu (outline titles, file names) inside an
# error handler, which surfaces as an unrelated failure. line_buffering makes progress
# appear as it happens even when the output is piped to a file. Same pattern as
# ml/serving/app.py.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# -- the contract ------------------------------------------------------------------------
# Changing anything in this block changes the vector space or the file format. It must
# move together with tdd.md section 3.2a, ml/serving/app.py's guards and
# backend/app/retrieval/physics9/local.py (Claude/DOC-SYNC-MAP.md).

ENCODER_VERSION = "1.0.0"
SCHEMA_VERSION = 2
CHECKPOINT = "vidore/colqwen2-v1.0"
# Pinned to the snapshots the query side runs. Passing revision= together with the hub id
# raises RevisionNotFoundError (transformers swaps the id for the base and reuses the
# revision), so the adapter is downloaded at its revision first and the base revision is
# given to from_pretrained, which only fetches the files the model needs.
ADAPTER_REVISION = "2b6ac8fb37f46a49e4841e599583d00ae8a20117"
BASE_REPO = "vidore/colqwen2-base"
BASE_REVISION = "9fe8a713422a7cb4ef79ca77a09b381ee2243101"
LORA_TENSORS = 394  # counted on the pinned adapter; fewer means the LoRA did not attach

CANVAS = (1049, 1387)  # every page of every book; a 62x48 patch grid -> 744 + 11 = 755
VECTORS_PER_PAGE = 755
DIM = 128
JPEG_QUALITY = 95  # PyMuPDF's default; reproduces the served Physics 9 p187 byte for byte
RENDER_RULE = "copy-jpeg-if-nothing-drawn-over|stretch-within-1pct|letterbox-white/v2"
ASPECT_TOLERANCE = 0.01
# When the embedded JPEG may be copied instead of rendered (see _copyable_jpeg).
COPY_EDGE_TOLERANCE_PT = 1.0  # the scan may sit this far from each page edge
COPY_COARSE_SIZE = (131, 173)  # one eighth of the canvas, for the flip/colour check
COPY_COARSE_MAX_MEAN = 2.0
COPY_COARSE_MAX_PIXEL = 48
STORE_DTYPE = torch.bfloat16  # lossless: the model outputs bfloat16 values
NORM_TOLERANCE = 0.01

# Measured 2026-11-15 on the owner's laptop with this exact stack: a page re-encoded on a
# different machine scored 0.982-0.989 mean token cosine against the old GPU index, while
# two DIFFERENT pages of the old index score 0.16 on average and at most 0.36. 0.95 sits
# between the two with a wide margin either side.
SAME_PAGE_MIN_COSINE = 0.95
BATCH_MATCH_MIN_COSINE = 0.999  # batch of 3 vs one at a time measured identical to 5 dp

PHYSICS_BOOK = "Punjab_9_Physics"
EDITION_MATCH_FRACTION = 0.95
REFERENCE_DIR = HERE / "reference"
REFERENCE_INDEX = REFERENCE_DIR / "pages.colqwen2.bf16.pt"
REFERENCE_HASHES = REFERENCE_DIR / "physics9-pages.sha256"
REFERENCE_PAGES = (10, 150, 187)
SERVED_SCANS = REPO / "backend" / "app" / "retrieval" / "physics9" / "pages"

EST_SECONDS_PER_PAGE = (1.8, 2.4)  # RTX 5060 estimate (RUN-ON-GPU.md), not measured
EST_PT_BYTES_PER_PAGE = VECTORS_PER_PAGE * DIM * 2
EST_IMAGE_BYTES_PER_PAGE = 210_000  # the 200 served scans average about 205 KB

BOARDS = {"punjab": "Punjab", "sindh": "Sindh"}
CLASSES = (9, 10, 11, 12)
SUBJECT_ALIASES = {
    "English": ["english", "eng"],
    "Urdu": ["urdu"],
    "Islamiat": ["islamiat", "islamiyat", "islamiyaat", "islamicstudies", "islamic"],
    "PakStudies": ["pakstudies", "pakistanstudies", "pakstudy", "pakistanstudy", "pst"],
    "Maths": ["maths", "math", "mathematics"],
    "TarjumaTulQuran": [
        "tarjumatulquran",
        "tarjumaquran",
        "tarjumatulquranmajeed",
        "tarjumaulquran",
        "translationofquran",
        "quran",
    ],
    "Physics": ["physics", "phy"],
    "Chemistry": ["chemistry", "chem"],
    "Biology": ["biology", "bio"],
    "ComputerScience": ["computerscience", "computer", "cs", "computerstudies"],
}
_ALIAS = {alias: canon for canon, aliases in SUBJECT_ALIASES.items() for alias in aliases}
# Owner's subject list (2026-11-15): Islamiat in 9 and 11, Pakistan Studies in 10 and 12,
# everything else in all four classes. 9 books a class, 36 a board, 72 in all.
_ALWAYS = [s for s in SUBJECT_ALIASES if s not in ("Islamiat", "PakStudies")]
EXPECTED_SUBJECTS = {
    9: [*_ALWAYS, "Islamiat"],
    10: [*_ALWAYS, "PakStudies"],
    11: [*_ALWAYS, "Islamiat"],
    12: [*_ALWAYS, "PakStudies"],
}
EXPECTED_BOOKS = [
    f"{board}_{cls}_{subject}"
    for board in BOARDS.values()
    for cls, subjects in EXPECTED_SUBJECTS.items()
    for subject in sorted(subjects)
]


class ToolError(Exception):
    """A failure with a message meant for the person running the tool."""


class GateFailedError(ToolError):
    """The Physics 9 end-to-end check failed. Stops the whole run."""


class CudaFatalError(ToolError):
    """A CUDA error other than out-of-memory. The GPU context is unusable afterwards."""


# -- small utilities ---------------------------------------------------------------------


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_with_retry(src: Path, dst: Path, attempts: int = 10) -> None:
    """os.replace, retried: Defender, the search indexer and OneDrive briefly lock new
    files on Windows, and a failed rename here would lose a finished book."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    replace_with_retry(tmp, path)


def write_json_atomic(path: Path, data: object) -> None:
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=True) + "\n")


def keep_awake() -> None:
    """Stop Windows idle-sleeping mid-run. Released automatically when the process exits;
    no system setting is changed. Does not stop lid-close or a manual sleep."""
    if sys.platform == "win32":
        es_continuous, es_system_required = 0x80000000, 0x00000001
        with contextlib.suppress(Exception):
            ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)


def fmt_hours(seconds: float) -> str:
    return f"{seconds / 3600:.1f} h"


def fmt_gb(nbytes: float) -> str:
    return f"{nbytes / 1024**3:.1f} GB"


class Tee:
    """Copy stdout to a log file, so a crash at hour six still leaves a full record."""

    def __init__(self, stream, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = stream
        self.fh = path.open("a", encoding="utf-8")

    def write(self, text: str) -> int:
        self.stream.write(text)
        self.fh.write(text)
        self.fh.flush()
        return len(text)

    def flush(self) -> None:
        self.stream.flush()
        self.fh.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start_log(log_dir: Path, command: str) -> Path:
    path = log_dir / f"{command}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    sys.stdout = Tee(sys.stdout, path)
    print(f"[log] {path}")
    return path


# -- naming ------------------------------------------------------------------------------


@dataclass(frozen=True)
class BookName:
    board: str
    class_level: int
    subject: str

    @property
    def book_id(self) -> str:
        return f"{self.board}_{self.class_level}_{self.subject}"


def parse_book_name(stem: str) -> BookName:
    """`Board_Class_Subject` (case-insensitive) -> BookName, or ToolError saying why not."""
    parts = [p for p in stem.strip().split("_") if p.strip()]
    if len(parts) < 3:
        raise ToolError(f"'{stem}': expected Board_Class_Subject, e.g. Punjab_9_Physics")
    board = BOARDS.get(parts[0].strip().lower())
    if board is None:
        raise ToolError(f"'{stem}': board must be Punjab or Sindh, not '{parts[0]}'")
    try:
        class_level = int(parts[1])
    except ValueError:
        raise ToolError(f"'{stem}': class must be 9, 10, 11 or 12, not '{parts[1]}'") from None
    if class_level not in CLASSES:
        raise ToolError(f"'{stem}': class must be 9, 10, 11 or 12, not '{parts[1]}'")
    key = re.sub(r"[^a-z0-9]", "", "".join(parts[2:]).lower())
    subject = _ALIAS.get(key)
    if subject is None:
        known = ", ".join(SUBJECT_ALIASES)
        raise ToolError(f"'{stem}': unknown subject '{'_'.join(parts[2:])}' (known: {known})")
    return BookName(board, class_level, subject)


@dataclass
class Book:
    name: BookName
    pdf: Path
    sha256: str = ""
    pages: int = 0

    @property
    def book_id(self) -> str:
        return self.name.book_id


@dataclass
class Discovery:
    books: list[Book] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def discover(input_dir: Path, *, hash_files: bool = True) -> Discovery:
    """Every `*.pdf` directly in input_dir is one book. Folders are errors (one PDF per
    book), as are unparseable names, two files with one book_id, and one file under two
    book_ids (the same sha256)."""
    found = Discovery()
    if not input_dir.is_dir():
        found.errors.append(f"input folder not found: {input_dir}")
        return found
    by_id: dict[str, Book] = {}
    for entry in sorted(input_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            found.errors.append(f"'{entry.name}' is a folder; each book must be one PDF file")
            continue
        if entry.suffix.lower() != ".pdf":
            if not entry.name.startswith("."):
                found.warnings.append(f"ignored (not a PDF): {entry.name}")
            continue
        try:
            name = parse_book_name(entry.stem)
        except ToolError as exc:
            found.errors.append(str(exc))
            continue
        if name.book_id in by_id:
            found.errors.append(
                f"two files map to {name.book_id}: {by_id[name.book_id].pdf.name} and {entry.name}"
            )
            continue
        book = Book(name=name, pdf=entry)
        by_id[name.book_id] = book
        found.books.append(book)
    if hash_files:
        by_sha: dict[str, Book] = {}
        for book in found.books:
            book.sha256 = sha256_file(book.pdf)
            if book.sha256 in by_sha:
                found.errors.append(
                    f"the same file is used for two books: {by_sha[book.sha256].pdf.name} and "
                    f"{book.pdf.name} (identical sha256)"
                )
            else:
                by_sha[book.sha256] = book
    return found


def order_books(books: list[Book]) -> list[Book]:
    """Physics 9 first (it is the end-to-end check), then sorted by book_id."""
    return sorted(books, key=lambda b: (b.book_id != PHYSICS_BOOK, b.book_id))


def select_books(books: list[Book], patterns: list[str] | None) -> list[Book]:
    if not patterns:
        return books
    lowered = [p.lower() for p in patterns]
    return [b for b in books if any(fnmatch.fnmatch(b.book_id.lower(), p) for p in lowered)]


# -- rendering ---------------------------------------------------------------------------


@dataclass
class Placement:
    """Where the PDF page landed on the canvas. figures.py maps boxes through this."""

    page: int
    path: str  # "copied" | "stretched" | "letterboxed"
    page_width_pt: float
    page_height_pt: float
    scale_x: float
    scale_y: float
    offset_x: float
    offset_y: float
    sha256: str = ""

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "path": self.path,
            "page_width_pt": round(self.page_width_pt, 3),
            "page_height_pt": round(self.page_height_pt, 3),
            "scale_x": round(self.scale_x, 6),
            "scale_y": round(self.scale_y, 6),
            "offset_x": round(self.offset_x, 3),
            "offset_y": round(self.offset_y, 3),
            "sha256": self.sha256,
        }


def _pixmap_to_image(pix):
    from PIL import Image

    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _copyable_jpeg(doc, page) -> bytes | None:
    """The page's embedded JPEG bytes if copying them shows exactly what the page shows.

    Copying preserves the scan with no second JPEG generation, and reproduces the served
    Physics 9 scans byte for byte. A pixel-exact render comparison does NOT work for this:
    on real scans the image sits a fraction of a point short of the page edge (0.28 pt in
    Physics 9), so rendering resamples it - mean difference about 0.3, single pixels off by
    up to 85 at text edges. Instead, anything that could draw ON TOP of the scan is checked
    directly, the placement matrix must be upright, and a coarse downscaled comparison
    catches Decode arrays and colour-space surprises (both Physics editions: mean 0.11,
    max 10).
    """
    import numpy as np
    import pymupdf
    from PIL import Image

    images = page.get_images(full=True)
    if len(images) != 1 or page.rotation:
        return None
    xref = images[0][0]
    info = doc.extract_image(xref)
    if info.get("ext") not in ("jpeg", "jpg") or (info.get("width"), info.get("height")) != CANVAS:
        return None
    if info.get("colorspace") != 3 or info.get("smask"):
        return None
    rect = page.rect
    placed = page.get_image_rects(xref)
    if len(placed) != 1:
        return None
    box = placed[0]
    # Upright and unflipped means a placement matrix of (+w, 0, 0, +h, x, y).
    transforms = [i["transform"] for i in page.get_image_info(xrefs=True) if i.get("xref") == xref]
    if len(transforms) != 1:
        return None
    a, b, c, d = transforms[0][:4]
    if a <= 0 or d <= 0 or abs(b) > 1e-3 * a or abs(c) > 1e-3 * d:
        return None
    edges = (box.x0 - rect.x0, box.y0 - rect.y0, rect.x1 - box.x1, rect.y1 - box.y1)
    if any(abs(edge) > COPY_EDGE_TOLERANCE_PT for edge in edges):
        return None
    # Anything drawn over the scan would be lost by copying it.
    if page.get_drawings() or page.first_annot is not None or page.first_widget is not None:
        return None
    if any(span["type"] != 3 and span.get("opacity", 1) > 0 for span in page.get_texttrace()):
        return None  # type 3 is invisible text: the OCR layer every Physics 9 page carries
    pix = page.get_pixmap(matrix=pymupdf.Matrix(CANVAS[0] / rect.width, CANVAS[1] / rect.height))
    if (pix.width, pix.height) != CANVAS or pix.n != 3:
        return None
    with Image.open(io.BytesIO(info["image"])) as decoded:
        if decoded.mode != "RGB":
            return None
        a = np.asarray(decoded.resize(COPY_COARSE_SIZE, Image.BOX), dtype=np.int16)
    b = np.asarray(_pixmap_to_image(pix).resize(COPY_COARSE_SIZE, Image.BOX), dtype=np.int16)
    diff = np.abs(a - b)
    if float(diff.mean()) > COPY_COARSE_MAX_MEAN or int(diff.max()) > COPY_COARSE_MAX_PIXEL:
        return None
    return info["image"]


def render_page(doc, index: int, dest: Path) -> Placement:
    """Render page `index` (0-based) to exactly CANVAS as RGB JPEG at `dest`, atomically."""
    import pymupdf
    from PIL import Image

    page = doc[index]
    width, height = page.rect.width, page.rect.height
    tmp = dest.with_name(dest.name + ".tmp")
    target_w, target_h = CANVAS
    aspect_off = abs((width / height) / (target_w / target_h) - 1.0)

    data = _copyable_jpeg(doc, page)
    if data is not None:
        tmp.write_bytes(data)
        placement = Placement(
            index + 1, "copied", width, height, target_w / width, target_h / height, 0.0, 0.0
        )
    elif aspect_off <= ASPECT_TOLERANCE:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(target_w / width, target_h / height))
        if (pix.width, pix.height) != CANVAS:
            raise ToolError(f"page {index + 1}: stretch gave {pix.width}x{pix.height}")
        pix.save(str(tmp), output="jpeg", jpg_quality=JPEG_QUALITY)
        placement = Placement(
            index + 1, "stretched", width, height, target_w / width, target_h / height, 0.0, 0.0
        )
    else:
        scale = min(target_w / width, target_h / height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        img = _pixmap_to_image(pix)
        if img.width > target_w or img.height > target_h:  # a rounding pixel, never more
            img = img.resize((min(img.width, target_w), min(img.height, target_h)))
        canvas = Image.new("RGB", CANVAS, (255, 255, 255))
        off_x, off_y = (target_w - img.width) // 2, (target_h - img.height) // 2
        canvas.paste(img, (off_x, off_y))
        canvas.save(tmp, format="JPEG", quality=JPEG_QUALITY)
        placement = Placement(
            index + 1,
            "letterboxed",
            width,
            height,
            img.width / width,
            img.height / height,
            float(off_x),
            float(off_y),
        )

    with Image.open(tmp) as check:
        if check.size != CANVAS or check.mode != "RGB":
            raise ToolError(f"page {index + 1}: wrote {check.size} {check.mode}, not {CANVAS} RGB")
    replace_with_retry(tmp, dest)
    placement.sha256 = sha256_file(dest)
    return placement


def page_path(pages_dir: Path, page: int) -> Path:
    return pages_dir / f"p{page:03}.jpeg"


def render_book(pdf: Path, pages_dir: Path, *, progress: bool = True) -> list[Placement]:
    import pymupdf

    pages_dir.mkdir(parents=True, exist_ok=True)
    placements: list[Placement] = []
    with pymupdf.open(pdf) as doc:
        count = len(doc)
        for index in range(count):
            placements.append(render_page(doc, index, page_path(pages_dir, index + 1)))
            if progress and ((index + 1) % 50 == 0 or index + 1 == count):
                print(f"    rendered {index + 1}/{count}")
    # A re-render of a shorter file must not leave the old tail behind.
    for stale in pages_dir.glob("p*.jpeg"):
        number = stale.stem[1:]
        if not number.isdigit() or int(number) > count:
            stale.unlink()
    return placements


# -- the store ---------------------------------------------------------------------------

_PLAIN = (str, int, float, bool, type(None))


def plain_problems(value, where: str = "store") -> list[str]:
    """Values torch.load(weights_only=True) refuses. Checked by exact type, because
    `torch.__version__` is a str SUBCLASS (TorchVersion) and is refused on load."""
    if isinstance(value, torch.Tensor):
        return []
    if type(value) in _PLAIN:
        return []
    if type(value) is list:
        return [p for i, v in enumerate(value) for p in plain_problems(v, f"{where}[{i}]")]
    if type(value) is dict:
        problems = []
        for k, v in value.items():
            if type(k) is not str:
                problems.append(f"{where}: key {k!r} is not a plain str")
            problems += plain_problems(v, f"{where}.{k}")
        return problems
    return [f"{where}: {type(value).__name__} is not a plain type"]


def token_cosine(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    return torch.nn.functional.cosine_similarity(a.float(), b.float(), dim=-1)


def check_store(store, *, expect_pages: int | None = None, allow_incomplete: bool = False):
    """Everything ml/serving/app.py checks (with N pages, not 200) and more. Returns a list
    of problems; empty means the file is safe to serve."""
    if type(store) is not dict:
        return ["not a dict"]
    problems: list[str] = []
    if store.get("checkpoint") != CHECKPOINT:
        problems.append(f"checkpoint is {store.get('checkpoint')!r}, expected {CHECKPOINT!r}")
    pages = store.get("pages")
    embeddings = store.get("embeddings")
    if type(pages) is not list or not all(type(p) is int for p in pages):
        problems.append("pages is not a list of plain ints")
        return problems
    if type(embeddings) is not list:
        problems.append("embeddings is not a list")
        return problems
    if pages != list(range(1, len(pages) + 1)):
        missing = sorted(set(range(1, max(pages, default=0) + 1)) - set(pages))
        problems.append(f"pages are not exactly 1..{len(pages)} in order; missing {missing[:10]}")
    if expect_pages is not None and len(pages) != expect_pages:
        problems.append(f"{len(pages)} pages, expected {expect_pages}")
    if len(pages) != len(embeddings):
        problems.append(f"{len(pages)} pages against {len(embeddings)} embeddings")
    if not allow_incomplete and store.get("complete") is not True:
        problems.append("not marked complete")
    if store.get("dim") != DIM:
        problems.append(f"dim is {store.get('dim')!r}, expected {DIM}")
    for i, tensor in enumerate(embeddings):
        label = f"page {pages[i] if i < len(pages) else '?'}"
        if not isinstance(tensor, torch.Tensor):
            problems.append(f"{label}: not a tensor")
            continue
        if tuple(tensor.shape) != (VECTORS_PER_PAGE, DIM):
            problems.append(f"{label}: shape {tuple(tensor.shape)}, expected (755, 128)")
            continue
        if tensor.dtype not in (torch.bfloat16, torch.float32):
            problems.append(f"{label}: dtype {tensor.dtype}")
            continue
        values = tensor.float()
        if not torch.isfinite(values).all():
            problems.append(f"{label}: contains NaN or infinity")
            continue
        norms = values.norm(dim=-1)
        if (norms - 1.0).abs().max().item() > NORM_TOLERANCE:
            problems.append(
                f"{label}: row norms {norms.min().item():.4f}-{norms.max().item():.4f}, "
                f"expected 1 +- {NORM_TOLERANCE}"
            )
        if len(problems) > 20:
            problems.append("... (stopped after 20 problems)")
            return problems
    problems += plain_problems({k: v for k, v in store.items() if k != "embeddings"})
    if not problems:
        try:
            torch.stack([t.float() for t in embeddings])  # exactly what the service does
        except RuntimeError as exc:
            problems.append(f"torch.stack failed: {exc}")
    return problems


def load_store(path: Path):
    """weights_only=True refuses any pickled code. These files come from another machine,
    and ml/serving/app.py:135 still loads with weights_only=False."""
    return torch.load(path, map_location="cpu", weights_only=True)


def library_versions() -> dict:
    versions = {"python": platform.python_version(), "torch": str(torch.__version__)}
    for package in (
        "torchvision",
        "transformers",
        "colpali-engine",
        "peft",
        "accelerate",
        "huggingface_hub",
        "tokenizers",
        "pymupdf",
        "pillow",
        "numpy",
        "docling",
    ):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not installed"
    versions["cuda"] = str(torch.version.cuda) if torch.version.cuda else "none"
    return versions


def fingerprint(source_sha256: str) -> dict:
    """What a finished book must match to be skipped. The encoder version is recorded but
    deliberately NOT part of it: a fix to logging or the runbook mid-run must not re-encode
    finished books. Anything that changes the vectors or the images is here."""
    return {
        "source_sha256": source_sha256,
        "canvas": list(CANVAS),
        "jpeg_quality": JPEG_QUALITY,
        "render_rule": RENDER_RULE,
        "checkpoint": CHECKPOINT,
        "adapter_revision": ADAPTER_REVISION,
        "base_revision": BASE_REVISION,
        "store_dtype": str(STORE_DTYPE).replace("torch.", ""),
        "schema_version": SCHEMA_VERSION,
    }


def is_done(book_dir: Path, book_id: str, source_sha256: str) -> bool:
    manifest_path = book_dir / "manifest.json"
    if not (book_dir / f"{book_id}.colqwen2.pt").exists() or not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return manifest.get("fingerprint") == fingerprint(source_sha256) and manifest.get("complete")


# -- the model ---------------------------------------------------------------------------


def is_oom(exc: BaseException) -> bool:
    """CUDA OOM arrives as OutOfMemoryError, but some kernels raise a plain RuntimeError
    whose message is the only clue (encode_gpu.py:47-52)."""
    if isinstance(exc, torch.cuda.OutOfMemoryError):
        return True
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


def is_cuda_fatal(exc: BaseException) -> bool:
    if is_oom(exc):
        return False
    text = str(exc)
    markers = ("CUDA error", "CUBLAS_STATUS", "cuDNN error", "device-side assert")
    return type(exc).__name__ == "AcceleratorError" or any(m in text for m in markers)


def vram_gb() -> float:
    if not torch.cuda.is_available():
        return 0.0
    return torch.cuda.get_device_properties(0).total_memory / 1024**3


def plan_batch(vram: float) -> int | None:
    """Batch size from the headroom left after the bf16 weights (encode_gpu.py:123-140,
    without its 8-bit branch: 8-bit shifts the vector space and is refused here)."""
    usable = vram - 0.8  # Windows reserves VRAM for the display
    weights = 2.2 * 2  # 2.2 B parameters at 2 bytes
    if usable < weights + 1.0:
        return None
    headroom = usable - weights
    return 2 if headroom >= 1.8 else 1


def gpu_problems() -> list[str]:
    """Empty if CUDA works for real. RTX 50-series (sm_120) needs a cu128+ build; an older
    wheel imports fine, reports cuda.is_available() True, then dies at the first kernel
    launch with 'no kernel image is available' - which reads like a model bug."""
    if not torch.cuda.is_available():
        return [
            "no CUDA GPU visible to torch "
            f"(torch {torch.__version__}). A plain 'pip install torch' is CPU-only; "
            "run setup.bat again."
        ]
    major, minor = torch.cuda.get_device_capability(0)
    arch = f"sm_{major}{minor}"
    problems = []
    if not any(a.startswith(arch) for a in torch.cuda.get_arch_list()):
        problems.append(
            f"this torch build has no kernels for {arch} ({torch.cuda.get_device_name(0)}); "
            f"built for {', '.join(torch.cuda.get_arch_list())}"
        )
    try:
        x = torch.randn(64, 64, device="cuda:0", dtype=torch.bfloat16)
        _ = (x @ x).float().sum().item()
    except Exception as exc:  # noqa: BLE001 - any failure here is the answer
        problems.append(f"a bfloat16 matmul on the GPU failed: {exc}")
    return problems


def _retry(action, what: str, attempts: int = 4):
    delays = (10, 30, 60)
    for attempt in range(attempts):
        try:
            return action()
        except Exception as exc:
            if is_oom(exc) or attempt == attempts - 1:
                raise
            wait = delays[min(attempt, len(delays) - 1)]
            print(f"    {what} failed ({type(exc).__name__}: {str(exc)[:160]}); retry in {wait}s")
            time.sleep(wait)
    raise AssertionError("unreachable")


def load_model(device: str):
    """ColQwen2 at the pinned adapter and base revisions, bfloat16, checkpoint-default
    processor (no kwargs). Raises ToolError if the LoRA did not attach."""
    from colpali_engine.models import ColQwen2, ColQwen2Processor
    from huggingface_hub import snapshot_download

    started = time.time()
    adapter = _retry(
        lambda: snapshot_download(CHECKPOINT, revision=ADAPTER_REVISION), "adapter download"
    )
    model = _retry(
        lambda: ColQwen2.from_pretrained(
            adapter, revision=BASE_REVISION, dtype=torch.bfloat16, device_map=device
        ),
        "model load",
    ).eval()
    processor = ColQwen2Processor.from_pretrained(adapter)
    lora = sum(1 for name, _ in model.named_parameters() if "lora" in name.lower())
    if lora != LORA_TENSORS:
        raise ToolError(f"model has {lora} LoRA tensors, expected {LORA_TENSORS}: wrong adapter")
    print(f"    model ready on {device} in {time.time() - started:.0f}s ({lora} LoRA tensors)")
    return model, processor


@dataclass
class Encoder:
    model: object
    processor: object
    device: str
    batch: int

    def encode(self, paths: list[Path], *, label: str = "") -> list[torch.Tensor]:
        """One (755, 128) bfloat16 CPU tensor per image path, in order."""
        from PIL import Image

        out: list[torch.Tensor] = []
        started = time.time()
        next_report = 0
        i = 0
        while i < len(paths):
            chunk = paths[i : i + self.batch]
            images = inputs = result = None
            try:
                images = []
                for path in chunk:
                    with Image.open(path) as img:
                        images.append(img.convert("RGB"))
                inputs = self.processor.process_images(images).to(self.device)
                with torch.no_grad():
                    result = self.model(**inputs)
            except Exception as exc:
                if not is_oom(exc):
                    if is_cuda_fatal(exc):
                        raise CudaFatalError(f"CUDA error: {exc}") from exc
                    raise
                # Drop every reference first: empty_cache only frees blocks nothing still
                # points at, and skipping this cascades the retry straight down to 1.
                del images, inputs, result
                gc.collect()
                if self.device.startswith("cuda"):
                    torch.cuda.empty_cache()
                if self.batch == 1:
                    raise ToolError(
                        "out of memory at batch 1: this GPU cannot run ColQwen2"
                    ) from exc
                self.batch = max(1, self.batch // 2)
                print(f"    out of memory; retrying at batch {self.batch}")
                continue
            mask = inputs["attention_mask"]
            if not bool(mask.all()):
                raise ToolError("padding in a batch: pages are not all the canvas size")
            if tuple(result.shape) != (len(chunk), VECTORS_PER_PAGE, DIM):
                raise ToolError(f"model returned {tuple(result.shape)}, expected (B, 755, 128)")
            if not torch.isfinite(result).all():
                raise ToolError("model returned NaN or infinity")
            out.extend(result[j].to(STORE_DTYPE).cpu().clone() for j in range(len(chunk)))
            i += len(chunk)
            del images, inputs, result
            if i >= next_report or i == len(paths):
                rate = (time.time() - started) / i
                left = rate * (len(paths) - i)
                print(
                    f"    {label}{i}/{len(paths)}  {rate:.2f} s/page  book eta {left / 60:.1f} min"
                )
                next_report = i + 25
        return out


def make_encoder(allow_cpu: bool, batch_override: int | None = None) -> Encoder:
    if torch.cuda.is_available():
        problems = gpu_problems()
        if problems:
            raise ToolError("GPU not usable:\n  " + "\n  ".join(problems))
        batch = plan_batch(vram_gb())
        if batch is None:
            raise ToolError(f"{vram_gb():.1f} GB VRAM cannot hold ColQwen2 in bfloat16")
        device = "cuda:0"
    elif allow_cpu:
        print("    CPU mode (--allow-cpu): minutes per page; for testing only")
        batch, device = 1, "cpu"
    else:
        raise ToolError("no CUDA GPU (pass --allow-cpu only to test on a few pages)")
    model, processor = load_model(device)
    return Encoder(model, processor, device, batch_override or batch)


# -- calibrate ---------------------------------------------------------------------------


def free_space(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def compare_pages(new: dict[int, torch.Tensor], ref: dict[int, torch.Tensor]) -> dict[int, dict]:
    stats = {}
    for page, tensor in new.items():
        if page not in ref:
            continue
        cos = token_cosine(tensor, ref[page])
        stats[page] = {
            "mean": cos.mean().item(),
            "p01": cos.quantile(0.01).item(),
            "min": cos.min().item(),
        }
    return stats


def load_reference_index() -> dict[int, torch.Tensor]:
    if not REFERENCE_INDEX.exists():
        raise ToolError(f"reference index missing: {REFERENCE_INDEX} (the package is incomplete)")
    store = load_store(REFERENCE_INDEX)
    return dict(zip(store["pages"], store["embeddings"], strict=True))


def cmd_calibrate(args) -> int:
    keep_awake()
    print("== environment")
    versions = library_versions()
    for key, value in versions.items():
        print(f"    {key:<16} {value}")
    ok = True
    if not platform.python_version().startswith("3.12."):
        print(f"    WARN Python {platform.python_version()}; 3.12 is the tested version")
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        major, minor = torch.cuda.get_device_capability(0)
        print(f"    GPU              {name}, {vram_gb():.1f} GB, sm_{major}{minor}")
        for problem in gpu_problems():
            print(f"    FAIL {problem}")
            ok = False
        batch = plan_batch(vram_gb())
        print(f"    batch plan       {batch if batch else 'WILL NOT FIT in bfloat16'}")
        ok = ok and batch is not None
    elif not args.allow_cpu:
        print("    FAIL no CUDA GPU visible to torch; run setup.bat again")
        ok = False
    from huggingface_hub import constants

    cache = Path(constants.HF_HUB_CACHE)
    print(f"    HF cache         {cache} ({fmt_gb(free_space(cache))} free)")
    print(f"    this folder      {HERE} ({fmt_gb(free_space(HERE))} free)")
    if free_space(cache) < 10 * 1024**3:
        print("    WARN under 10 GB free for the model cache (it needs about 9 GB)")
    if not ok:
        print("\nCALIBRATE: FAIL (environment). Fix the lines marked FAIL, then run it again.")
        return 1

    if not args.skip_figures:
        print("== figure detector (Docling) warm-up")
        try:
            sys.path.insert(0, str(HERE))
            import figures

            seconds = figures.warm_up("cuda" if torch.cuda.is_available() else "cpu")
            print(f"    Docling ready ({seconds:.0f}s; models downloaded if they were missing)")
            # Release Docling's GPU memory before ColQwen2 loads: on an 8 GB card the
            # allocator's cached blocks would otherwise shrink the batch that fits.
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as exc:  # noqa: BLE001 - report and carry on to the main check
            print(f"    FAIL Docling could not run: {type(exc).__name__}: {exc}")
            ok = False

    print("== model")
    encoder = make_encoder(args.allow_cpu)
    reference = load_reference_index()
    pages = REFERENCE_PAGES[:1] if args.quick else REFERENCE_PAGES
    paths = [REFERENCE_DIR / f"p{p:03}.jpeg" for p in pages]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise ToolError(f"reference images missing: {missing}")

    print("== one page at a time, against the reference index")
    singles: dict[int, torch.Tensor] = {}
    timings = []
    for page, path in zip(pages, paths, strict=True):
        started = time.time()
        singles[page] = encoder.encode([path], label=f"p{page:03} ")[0]
        timings.append(time.time() - started)
    stats = compare_pages(singles, reference)
    for page in pages:
        s = stats[page]
        verdict = "ok" if s["mean"] >= SAME_PAGE_MIN_COSINE else "FAIL"
        print(
            f"    p{page:03}  mean {s['mean']:.4f}  (p01 {s['p01']:.3f}, min {s['min']:.3f})  "
            f"{verdict}"
        )
        ok = ok and s["mean"] >= SAME_PAGE_MIN_COSINE
    steady = timings[1:] or timings
    note = "first page excluded as warm-up" if len(timings) > 1 else "one page, includes warm-up"
    print(f"    speed {sum(steady) / len(steady):.2f} s/page ({note})")

    if len(pages) > 1:
        print("== the same pages as one batch, against the single-page results above")
        try:
            saved, encoder.batch = encoder.batch, len(pages)
            batched = encoder.encode(paths, label="batch ")
            encoder.batch = saved
            for page, tensor in zip(pages, batched, strict=True):
                mean = token_cosine(tensor, singles[page]).mean().item()
                verdict = "ok" if mean >= BATCH_MATCH_MIN_COSINE else "FAIL"
                print(f"    p{page:03}  batch vs single {mean:.5f}  {verdict}")
                ok = ok and mean >= BATCH_MATCH_MIN_COSINE
        except ToolError as exc:
            print(f"    skipped: {exc}")

    print(f"\nCALIBRATE: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("Do not start the long run. Send the log file above to the owner.")
    return 0 if ok else 1


# -- preflight ---------------------------------------------------------------------------


def inspect_pdf(book: Book, scratch: Path) -> tuple[list[str], list[str], dict]:
    """(errors, warnings, facts) for one PDF, including a trial render of three pages."""
    import pymupdf

    errors: list[str] = []
    warnings: list[str] = []
    facts: dict = {}
    try:
        doc = pymupdf.open(book.pdf)
    except Exception as exc:  # noqa: BLE001 - any open failure is the finding
        return [f"{book.pdf.name}: cannot be opened ({exc})"], warnings, facts
    with doc:
        if doc.needs_pass:
            return [f"{book.pdf.name}: needs a password"], warnings, facts
        count = len(doc)
        book.pages = count
        facts["pages"] = count
        if count == 0:
            return [f"{book.pdf.name}: has no pages"], warnings, facts
        sizes: dict[str, int] = {}
        landscape = 0
        for page in doc:
            w, h = page.rect.width, page.rect.height
            sizes[f"{w:.0f}x{h:.0f}"] = sizes.get(f"{w:.0f}x{h:.0f}", 0) + 1
            landscape += w > h
        facts["page_sizes_pt"] = dict(sorted(sizes.items(), key=lambda kv: -kv[1]))
        if len(sizes) > 1:
            warnings.append(f"{book.book_id}: {len(sizes)} different page sizes")
        if landscape:
            warnings.append(f"{book.book_id}: {landscape} landscape page(s) (letterboxed)")
        trial = sorted({0, count // 2, count - 1})
        paths = []
        for index in trial:
            try:
                placement = render_page(doc, index, scratch / f"{book.book_id}-{index + 1}.jpeg")
                paths.append(f"p{index + 1}:{placement.path}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{book.book_id}: page {index + 1} failed to render ({exc})")
        facts["trial_render"] = paths
    return errors, warnings, facts


def cmd_preflight(args) -> int:
    input_dir = Path(args.input)
    print(f"== scanning {input_dir}")
    found = discover(input_dir)
    errors, warnings = list(found.errors), list(found.warnings)
    facts: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as scratch:
        for book in order_books(found.books):
            e, w, f = inspect_pdf(book, Path(scratch))
            errors += e
            warnings += w
            facts[book.book_id] = {"file": book.pdf.name, "sha256": book.sha256, **f}
            print(f"    {book.book_id:<32} {f.get('pages', '?'):>4} pages  {book.pdf.name}")

    present = {b.book_id for b in found.books}
    missing = [b for b in EXPECTED_BOOKS if b not in present]
    extra = sorted(present - set(EXPECTED_BOOKS))
    total_pages = sum(b.pages for b in found.books)
    est_bytes = total_pages * (EST_PT_BYTES_PER_PAGE + EST_IMAGE_BYTES_PER_PAGE)
    out_dir = Path(args.out)
    free = free_space(out_dir)

    lines = [
        f"EduBridge book indexing - preflight report ({now_utc()})",
        f"input: {input_dir.resolve()}",
        "",
        f"books found: {len(found.books)} of {len(EXPECTED_BOOKS)} expected",
        f"pages: {total_pages}",
        f"estimated GPU time: {fmt_hours(total_pages * EST_SECONDS_PER_PAGE[0])} - "
        f"{fmt_hours(total_pages * EST_SECONDS_PER_PAGE[1])} (estimate; calibrate measures it)",
        f"estimated output: {fmt_gb(est_bytes)}; free on {out_dir}: {fmt_gb(free)}",
        "",
        "COVERAGE (x = present, . = missing, - = not expected)",
    ]
    for board in BOARDS.values():
        lines.append(f"  {board}")
        lines.append("    " + "subject".ljust(18) + "".join(f"{c:>4}" for c in CLASSES))
        for subject in SUBJECT_ALIASES:
            cells = []
            for cls in CLASSES:
                book_id = f"{board}_{cls}_{subject}"
                if book_id in present:
                    cells.append("x")
                elif subject in EXPECTED_SUBJECTS[cls]:
                    cells.append(".")
                else:
                    cells.append("-")
            lines.append("    " + subject.ljust(18) + "".join(f"{c:>4}" for c in cells))
    if est_bytes * 1.2 > free:
        errors.append(f"not enough free space on {out_dir}: need about {fmt_gb(est_bytes * 1.2)}")
    lines += ["", f"ERRORS ({len(errors)}) - must be fixed before 'run'"]
    lines += [f"  - {e}" for e in errors] or ["  none"]
    lines += ["", f"MISSING ({len(missing)})"] + ([f"  - {m}" for m in missing] or ["  none"])
    lines += ["", f"NOT IN THE EXPECTED LIST ({len(extra)}) - will still be encoded"]
    lines += [f"  - {x}" for x in extra] or ["  none"]
    lines += ["", f"WARNINGS ({len(warnings)})"] + ([f"  - {w}" for w in warnings] or ["  none"])
    lines += ["", "PER BOOK"]
    for book_id, info in facts.items():
        sizes = ", ".join(
            f"{k} pt x{v}" for k, v in list(info.get("page_sizes_pt", {}).items())[:3]
        )
        lines.append(f"  {book_id}: {info.get('pages', '?')} pages; {sizes}; {info['file']}")
    text = "\n".join(lines) + "\n"
    report = Path(args.report)
    write_text_atomic(report, text)
    write_json_atomic(
        report.with_suffix(".json"),
        {
            "created_utc": now_utc(),
            "errors": errors,
            "warnings": warnings,
            "missing": missing,
            "extra": extra,
            "books": facts,
            "total_pages": total_pages,
        },
    )
    print("\n" + text)
    print(f"report written: {report.resolve()}")
    print(f"\nPREFLIGHT: {'FAIL' if errors else 'OK'}")
    return 1 if errors else 0


# -- run ---------------------------------------------------------------------------------


@dataclass
class GateResult:
    applies: bool
    identical_pages: list[int]
    differing_pages: list[int]
    failures: list[str]
    note: str


def read_reference_hashes() -> list[str]:
    if not REFERENCE_HASHES.exists():
        raise ToolError(f"missing {REFERENCE_HASHES}")
    hashes = []
    for line in REFERENCE_HASHES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            hashes.append(line.split()[0])
    return hashes


def physics_gate(
    rendered: list[str],
    reference_hashes: list[str],
    encoded: dict[int, torch.Tensor],
    reference: dict[int, torch.Tensor],
) -> GateResult:
    """Decide the edition from the page images, then demand the embeddings match on every
    page whose image is byte-identical to the served scan. A page off by one scores at most
    0.36 against its neighbour, so an ordering or batching bug cannot pass."""
    if len(rendered) != len(reference_hashes):
        return GateResult(
            False,
            [],
            [],
            [],
            f"{len(rendered)} pages, not {len(reference_hashes)}: another edition",
        )
    identical = [
        i + 1 for i, (a, b) in enumerate(zip(rendered, reference_hashes, strict=True)) if a == b
    ]
    differing = [p for p in range(1, len(rendered) + 1) if p not in set(identical)]
    if len(identical) < EDITION_MATCH_FRACTION * len(rendered):
        return GateResult(
            False,
            identical,
            differing,
            [],
            f"only {len(identical)} identical pages: another edition",
        )
    failures = []
    for page in identical:
        if page not in encoded:
            continue
        mean = token_cosine(encoded[page], reference[page]).mean().item()
        if mean < SAME_PAGE_MIN_COSINE:
            failures.append(f"p{page:03} mean cosine {mean:.3f} < {SAME_PAGE_MIN_COSINE}")
    return GateResult(True, identical, differing, failures, "same edition as the served index")


def build_store(book: Book, embeddings: list[torch.Tensor], *, complete: bool, extra: dict) -> dict:
    return {
        # the contract, read by ml/serving/app.py and backend local.py
        "checkpoint": CHECKPOINT,
        "pages": list(range(1, len(embeddings) + 1)),
        "embeddings": embeddings,
        "complete": complete,
        "dim": DIM,
        # legacy keys, as encode_gpu.py wrote them
        "model": "colqwen2",
        "quantized": False,
        "expected_pages": book.pages,
        # provenance, ignored by today's readers
        "schema_version": SCHEMA_VERSION,
        "book_id": book.book_id,
        "board": book.name.board,
        "class_level": book.name.class_level,
        "subject": book.name.subject,
        "vectors_per_page": VECTORS_PER_PAGE,
        "source_file": book.pdf.name,
        "source_sha256": book.sha256,
        "adapter_revision": ADAPTER_REVISION,
        "base_revision": BASE_REVISION,
        "encoder_version": ENCODER_VERSION,
        "created_utc": now_utc(),
        **extra,
    }


def save_store(store: dict, dest: Path, *, allow_incomplete: bool) -> None:
    """Write to a temporary file, reload it the way a reader will, check it, then rename.
    A file that exists under its final name has always passed check_store."""
    problems = plain_problems({k: v for k, v in store.items() if k != "embeddings"})
    if problems:
        raise ToolError("store has values weights_only loading refuses: " + "; ".join(problems))
    tmp = dest.with_name(dest.name + ".tmp")
    torch.save(store, tmp)
    reloaded = load_store(tmp)
    problems = check_store(reloaded, allow_incomplete=allow_incomplete)
    if problems:
        raise ToolError(f"{dest.name} failed its own check: " + "; ".join(problems[:5]))
    replace_with_retry(tmp, dest)


def process_book(book: Book, out_dir: Path, args, state: dict) -> str:
    """Render, encode, check and save one book. Returns a one-line status."""
    import pymupdf

    smoke = bool(args.limit)
    book_dir = out_dir / ("_smoke" if smoke else "") / book.book_id
    if not smoke and not args.force and is_done(book_dir, book.book_id, book.sha256):
        return "skipped (already done, fingerprint matches)"
    started = time.time()
    with pymupdf.open(book.pdf) as doc:
        book.pages = len(doc)
        outline = [[int(lvl), str(title), int(page)] for lvl, title, page, *_ in doc.get_toc()]
    print(f"  rendering {book.pages} pages")
    placements = render_book(book.pdf, book_dir / "pages")
    paths = [page_path(book_dir / "pages", p.page) for p in placements]
    counts: dict[str, int] = {}
    for p in placements:
        counts[p.path] = counts.get(p.path, 0) + 1
    print(f"    {counts}")

    gate = None
    if book.book_id == PHYSICS_BOOK:
        gate = physics_gate([p.sha256 for p in placements], read_reference_hashes(), {}, {})
        print(f"  physics gate: {gate.note}; {len(gate.identical_pages)} identical page images")
        if gate.differing_pages:
            print(f"    differing pages: {gate.differing_pages[:20]}")

    if smoke:
        paths = paths[: args.limit]
    encoder = state.get("encoder") or make_encoder(args.allow_cpu, args.batch)
    state["encoder"] = encoder
    print(f"  encoding {len(paths)} pages at batch {encoder.batch}")
    embeddings = encoder.encode(paths)

    if gate is not None and gate.applies:
        encoded = dict(zip(range(1, len(embeddings) + 1), embeddings, strict=True))
        gate = physics_gate(
            [p.sha256 for p in placements], read_reference_hashes(), encoded, state["reference"]
        )
        checked = [p for p in gate.identical_pages if p in encoded]
        means = [token_cosine(encoded[p], state["reference"][p]).mean().item() for p in checked]
        if means:
            print(
                f"  physics gate: {len(checked)} pages compared, mean cosine "
                f"{sum(means) / len(means):.4f}, lowest {min(means):.4f}"
            )
        if gate.failures:
            raise GateFailedError(
                "Physics 9 gate FAILED:\n    " + "\n    ".join(gate.failures[:20])
            )

    seconds = time.time() - started
    extra = {
        "versions": library_versions(),
        "device": torch.cuda.get_device_name(0) if encoder.device.startswith("cuda") else "cpu",
        "batch": encoder.batch,
        "seconds": round(seconds, 1),
    }
    store = build_store(book, embeddings, complete=not smoke, extra=extra)
    dest = book_dir / f"{book.book_id}.colqwen2.pt"
    save_store(store, dest, allow_incomplete=smoke)
    manifest = {
        "book_id": book.book_id,
        "board": book.name.board,
        "class_level": book.name.class_level,
        "subject": book.name.subject,
        "source_file": book.pdf.name,
        "source_sha256": book.sha256,
        "pages": book.pages,
        "encoded_pages": len(embeddings),
        "complete": not smoke,
        "fingerprint": fingerprint(book.sha256),
        "encoder_version": ENCODER_VERSION,
        "pt_file": dest.name,
        "pt_sha256": sha256_file(dest),
        "created_utc": now_utc(),
        **extra,
        "render_counts": counts,
        "physics_gate": None
        if gate is None
        else {
            "applies": gate.applies,
            "note": gate.note,
            "identical_pages": len(gate.identical_pages),
            "differing_pages": gate.differing_pages,
        },
        "outline": outline,
        "placements": [p.as_dict() for p in placements],
    }
    write_json_atomic(book_dir / "manifest.json", manifest)
    rate = seconds / max(1, len(embeddings))
    return (
        f"done: {len(embeddings)} pages in {seconds / 60:.1f} min ({rate:.2f} s/page incl. render)"
    )


def cmd_run(args) -> int:
    keep_awake()
    input_dir, out_dir = Path(args.input), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    found = discover(input_dir)
    for warning in found.warnings:
        print(f"  WARN {warning}")
    if found.errors:
        print("Fix these first (preflight lists them too):")
        for error in found.errors:
            print(f"  - {error}")
        return 1
    books = order_books(select_books(found.books, args.books))
    if not books:
        print("no books selected")
        return 1
    state: dict = {}
    if any(b.book_id == PHYSICS_BOOK for b in books):
        state["reference"] = load_reference_index()
    else:
        print(f"  NOTE {PHYSICS_BOOK} is not selected, so the end-to-end check does not run")
    smoke = f" (smoke test, --limit {args.limit})" if args.limit else ""
    print(f"== {len(books)} book(s){smoke}")
    results: dict[str, str] = {}
    run_started = time.time()
    for number, book in enumerate(books, 1):
        print(f"\n[{number}/{len(books)}] {book.book_id}  ({book.pdf.name})")
        try:
            results[book.book_id] = process_book(book, out_dir, args, state)
        except (GateFailedError, CudaFatalError) as exc:
            results[book.book_id] = f"FAILED: {exc}"
            print(f"  {exc}")
            print(
                "\nSTOPPED. "
                + (
                    "Send the log to the owner."
                    if isinstance(exc, GateFailedError)
                    else "Re-run the same command to resume."
                )
            )
            break
        except KeyboardInterrupt:
            print("\nInterrupted. Finished books are kept; re-run the same command to resume.")
            return 130
        except Exception as exc:  # noqa: BLE001 - one bad book must not stop the other 71
            results[book.book_id] = f"FAILED: {type(exc).__name__}: {exc}"
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stdout)
        print(f"  {results[book.book_id]}")
        print(f"  run time so far {(time.time() - run_started) / 3600:.2f} h")
    print("\n== summary")
    for book_id, status in results.items():
        print(f"  {book_id:<32} {status}")
    failed = [b for b, s in results.items() if s.startswith("FAILED")]
    print(f"\nRUN: {len(results) - len(failed)} ok, {len(failed)} failed")
    return 1 if failed or len(results) < len(books) else 0


# -- verify ------------------------------------------------------------------------------


def verify_book(book_dir: Path, pdf_pages: int | None) -> list[str]:
    book_id = book_dir.name
    pt = book_dir / f"{book_id}.colqwen2.pt"
    if not pt.exists():
        return [f"{pt.name} missing"]
    try:
        store = load_store(pt)
    except Exception as exc:  # noqa: BLE001 - refusing to load is the finding
        return [f"{pt.name} does not load with weights_only=True: {exc}"]
    problems = check_store(store, expect_pages=pdf_pages)
    if store.get("book_id") != book_id:
        problems.append(f"book_id inside is {store.get('book_id')!r}")
    manifest_path = book_dir / "manifest.json"
    if not manifest_path.exists():
        return [*problems, "manifest.json missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("pt_sha256") != sha256_file(pt):
        problems.append("the .pt does not match the sha256 in manifest.json")
    count = len(store.get("pages", []))
    images = sorted((book_dir / "pages").glob("p*.jpeg"))
    if len(images) != count:
        problems.append(f"{len(images)} page images for {count} pages")
    expected = {f"p{p['page']:03}.jpeg": p["sha256"] for p in manifest.get("placements", [])}
    bad = [img.name for img in images if expected.get(img.name) != sha256_file(img)]
    if bad:
        problems.append(f"{len(bad)} page image(s) differ from the manifest, e.g. {bad[:3]}")
    return problems


def cmd_verify(args) -> int:
    out_dir = Path(args.out)
    pdf_pages: dict[str, int] = {}
    if args.input:
        import pymupdf

        for book in discover(Path(args.input), hash_files=False).books:
            with pymupdf.open(book.pdf) as doc:
                pdf_pages[book.book_id] = len(doc)
    lines = [
        f"EduBridge book indexing - verify report ({now_utc()})",
        f"out: {out_dir.resolve()}",
        "",
    ]
    failures = 0
    zipped = sorted(out_dir.rglob("*.pt.zip"))
    for path in zipped:
        lines.append(f"FAIL {path}: a .pt with .zip added - rename it, never extract it")
        failures += 1
    book_dirs = sorted(
        d
        for d in out_dir.iterdir()
        if d.is_dir() and not d.name.startswith(("_", ".")) and d.name != "logs"
    )
    for book_dir in book_dirs:
        problems = verify_book(book_dir, pdf_pages.get(book_dir.name))
        if problems:
            failures += 1
            lines.append(f"FAIL {book_dir.name}")
            lines += [f"       - {p}" for p in problems[:10]]
        else:
            lines.append(f"PASS {book_dir.name}")
    present = {d.name for d in book_dirs}
    if args.input:
        for book_id in sorted(set(pdf_pages) - present):
            lines.append(f"MISSING {book_id} (in the input folder, not in out)")
            failures += 1
    lines += ["", f"{len(book_dirs)} book folder(s), {failures} problem(s)"]
    text = "\n".join(lines) + "\n"
    write_text_atomic(out_dir / "verify-report.txt", text)
    sums = []
    for path in sorted(out_dir.rglob("*")):
        rel = path.relative_to(out_dir).as_posix()
        if (
            path.is_file()
            and not rel.startswith(("logs/", "_smoke/"))
            and rel
            not in (
                "SHA256SUMS.txt",
                "verify-report.txt",
            )
        ):
            sums.append(f"{sha256_file(path)}  {rel}")
    write_text_atomic(out_dir / "SHA256SUMS.txt", "\n".join(sums) + "\n")
    print(text)
    verdict = "PASS" if failures == 0 else "FAIL"
    print(f"VERIFY: {verdict}  (SHA256SUMS.txt written, {len(sums)} files)")
    return 0 if failures == 0 else 1


# -- compare and make-reference ----------------------------------------------------------


def cmd_compare(args) -> int:
    a, b = load_store(Path(args.a)), load_store(Path(args.b))
    pa = dict(zip(a["pages"], a["embeddings"], strict=True))
    pb = dict(zip(b["pages"], b["embeddings"], strict=True))
    stats = compare_pages(pa, pb)
    if not stats:
        print("no pages in common")
        return 1
    means = {p: s["mean"] for p, s in stats.items()}
    worst = sorted(means.items(), key=lambda kv: kv[1])[:5]
    below = [p for p, m in means.items() if m < SAME_PAGE_MIN_COSINE]
    print(f"pages compared: {len(means)} (A has {len(pa)}, B has {len(pb)})")
    print(f"mean token cosine: average {sum(means.values()) / len(means):.4f}")
    print("lowest pages: " + ", ".join(f"p{p:03} {m:.4f}" for p, m in worst))
    print(f"pages below {SAME_PAGE_MIN_COSINE}: {len(below)} {below[:20]}")
    return 0 if not below else 1


def cmd_make_reference(args) -> int:
    """Owner only: build reference/ from the existing index and the served scans."""
    source = Path(args.index)
    store = load_store(source)
    problems = check_store(store, expect_pages=200)
    if problems:
        raise ToolError(f"{source} is not a valid 200-page index: {problems[:3]}")
    exact = all(torch.equal(t.to(torch.bfloat16).float(), t.float()) for t in store["embeddings"])
    if not exact:
        raise ToolError("the index is not exactly representable in bfloat16; refusing to round")
    scans = Path(args.scans)
    images = [page_path(scans, p) for p in range(1, 201)]
    missing = [i.name for i in images if not i.exists()]
    if missing:
        raise ToolError(f"served scans missing: {missing[:5]}")
    REFERENCE_DIR.mkdir(exist_ok=True)
    reference = {
        "checkpoint": store["checkpoint"],
        "pages": list(store["pages"]),
        "embeddings": [t.to(torch.bfloat16).clone() for t in store["embeddings"]],
        "complete": True,
        "dim": DIM,
        "source_sha256": sha256_file(source),
        "note": "Punjab Class 9 Physics index as served, stored in bfloat16 (exact)",
        "created_utc": now_utc(),
    }
    save_store(reference, REFERENCE_INDEX, allow_incomplete=False)
    for page in REFERENCE_PAGES:
        shutil.copyfile(page_path(scans, page), REFERENCE_DIR / f"p{page:03}.jpeg")
    lines = [f"{sha256_file(img)}  {img.name}" for img in images]
    write_text_atomic(REFERENCE_HASHES, "\n".join(lines) + "\n")
    size = REFERENCE_INDEX.stat().st_size / 1024**2
    print(f"reference index: {REFERENCE_INDEX} ({size:.1f} MB, bfloat16, exact)")
    print(f"reference images: {', '.join(f'p{p:03}.jpeg' for p in REFERENCE_PAGES)}")
    print(f"scan hashes: {REFERENCE_HASHES} (200 lines)")
    return 0


# -- entry point -------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("calibrate", help="environment checks + the model against the reference")
    p.add_argument("--allow-cpu", action="store_true", help="testing only: minutes per page")
    p.add_argument("--quick", action="store_true", help="one reference page, no batch check")
    p.add_argument("--skip-figures", action="store_true", help="do not warm up Docling")

    p = sub.add_parser("preflight", help="check names, PDFs and coverage; no model needed")
    p.add_argument("--input", required=True, help="folder holding the book PDFs")
    p.add_argument("--out", default="out", help="where run will write (for the space check)")
    p.add_argument("--report", default="preflight-report.txt")

    p = sub.add_parser("run", help="render, encode and save every book (resumable)")
    p.add_argument("--input", required=True)
    p.add_argument("--out", default="out")
    p.add_argument("--books", nargs="+", help="book_id glob(s), e.g. Punjab_9_Physics 'Sindh_*'")
    p.add_argument("--limit", type=int, default=0, help="smoke test: encode the first N pages")
    p.add_argument("--force", action="store_true", help="re-encode selected books even if done")
    p.add_argument("--batch", type=int, default=None, help="override the planned batch size")
    p.add_argument("--allow-cpu", action="store_true", help="testing only: minutes per page")

    p = sub.add_parser("verify", help="check finished books the way the service loads them")
    p.add_argument("--out", default="out")
    p.add_argument("--input", default=None, help="also compare page counts with the PDFs")

    p = sub.add_parser("compare", help="per-page cosine between two indexes")
    p.add_argument("a")
    p.add_argument("b")

    p = sub.add_parser("make-reference", help="owner only: build reference/ from the served index")
    p.add_argument("--index", required=True, help="the served pages.colqwen2.pt")
    p.add_argument("--scans", default=str(SERVED_SCANS), help="the 200 served page scans")

    args = parser.parse_args(argv)
    if args.command in ("calibrate", "run", "preflight"):
        log_dir = (
            Path(getattr(args, "out", "") or ".") / "logs"
            if args.command == "run"
            else HERE / "logs"
        )
        start_log(log_dir, args.command)
    handlers = {
        "calibrate": cmd_calibrate,
        "preflight": cmd_preflight,
        "run": cmd_run,
        "verify": cmd_verify,
        "compare": cmd_compare,
        "make-reference": cmd_make_reference,
    }
    try:
        return handlers[args.command](args)
    except ToolError as exc:
        print(f"\nERROR: {exc}")
        return 1
    except Exception:
        traceback.print_exc(file=sys.stdout)
        return 1


if __name__ == "__main__":
    sys.exit(main())
