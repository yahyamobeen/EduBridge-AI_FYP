"""Self-test for the retrieval service, with no model and no spare RAM required.

Exercises the parts that are easy to get wrong and hard to notice: the startup guards
for every book, discovering books under INDEX_DIR, the single-file mode the Docker image
uses, book resolution, anchor bounds, the cache key and the secret comparison. `torch`
is stubbed, so this runs anywhere - including a machine that cannot hold ColQwen2.

⚠️ It does NOT test the forward pass or the MaxSim arithmetic. Those need the real
model; `measure.py` on the deployment target is what covers them.

    python selftest.py
"""

from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


# -- stub torch before importing the service ----------------------------------
# The service imports torch lazily inside functions, so a stub installed here satisfies
# every path the guards take. `load` is replaced per test and keyed on the file path.


class _FakeTensor:
    def __init__(self, shape):
        self.shape = shape

    def to(self, _dtype):
        return self


class _FakeStacked:
    """Just enough shape for `load()` to record vectors_per_page and dim."""

    def __init__(self, tensors):
        shapes = {t.shape for t in tensors}
        if len(shapes) > 1:
            raise RuntimeError("stack expects each tensor to be equal size")
        vectors, dim = tensors[0].shape if tensors else (0, 0)
        self.shape = (len(tensors), vectors, dim)

    def __getitem__(self, _order):
        return self


_stub = types.ModuleType("torch")
_stub.float32 = "float32"
_stub.bfloat16 = "bfloat16"
_STORES: dict[str, dict] = {}
_stub.load = lambda path, **k: _STORES[Path(path).name]
_stub.stack = lambda tensors: _FakeStacked(tensors)
_stub.get_num_threads = lambda: 2
_stub.set_num_threads = lambda n: None
_stub.set_num_interop_threads = lambda n: None
sys.modules.setdefault("torch", _stub)

import app  # noqa: E402  (must follow the torch stub)


def store(checkpoint="vidore/colqwen2-v1.0", pages=200, embeddings=None, complete=True, **extra):
    page_list = list(range(1, pages + 1)) if isinstance(pages, int) else pages
    if embeddings is None:
        embeddings = [_FakeTensor((755, 128)) for _ in page_list]
    return {
        "checkpoint": checkpoint,
        "pages": page_list,
        "embeddings": embeddings,
        "complete": complete,
        "dim": 128,
        **extra,
    }


def load_single(fake_store, path_exists=True):
    """Index.load() in single-file mode (PAGES_PT). Returns the SystemExit text, or None."""
    _STORES.clear()
    _STORES["fake-pages.pt"] = fake_store
    app.INDEX_DIR = ""
    app.EMBEDDINGS_PATH = Path("fake-pages.pt") if path_exists else Path("does-not-exist.pt")
    original_exists = Path.exists
    Path.exists = lambda self: path_exists  # type: ignore[method-assign]
    index = app.Index()
    index._load_model = lambda: None  # the guards are the subject, not the model
    try:
        index.load()
        return None, index
    except SystemExit as exc:
        return str(exc), index
    finally:
        Path.exists = original_exists  # type: ignore[method-assign]


def load_dir(books: dict[str, dict], allow: list[str] | None = None, extra_files=()):
    """Index.load() over a real temporary INDEX_DIR of empty files and fake stores."""
    _STORES.clear()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for book_id, fake in books.items():
            folder = root / book_id
            folder.mkdir()
            (folder / f"{book_id}.colqwen2.pt").write_bytes(b"")
            _STORES[f"{book_id}.colqwen2.pt"] = fake
        for name in extra_files:
            (root / name).mkdir()
        app.INDEX_DIR = str(root)
        app.BOOKS = allow or []
        index = app.Index()
        index._load_model = lambda: None
        try:
            index.load()
            return None, index
        except SystemExit as exc:
            return str(exc), index
        finally:
            app.INDEX_DIR = ""
            app.BOOKS = []


print("single-file guards (each must REFUSE, before the model loads)")

msg, _ = load_single(store(checkpoint="vidore/colpali-v1.3"))
check("checkpoint mismatch refuses", msg is not None and "checkpoint mismatch" in msg, str(msg))
check(
    "the message names both checkpoints",
    msg is not None and "colpali-v1.3" in msg and "colqwen2-v1.0" in msg,
    str(msg),
)
msg, _ = load_single(store(pages=list(range(1, 200)), expected_pages=200))
check(
    "a missing page refuses",
    msg is not None and "does not cover pages 1-200" in msg and "200" in msg,
    str(msg),
)
msg, _ = load_single(store(pages=list(range(1, 201)) + [202]))
check("an out-of-range page refuses", msg is not None, str(msg))
msg, _ = load_single(store(pages=[5] * 200))
check("duplicate pages refuse", msg is not None, str(msg))
msg, _ = load_single(store(embeddings=[_FakeTensor((755, 128))] * 199))
check("length mismatch refuses", msg is not None and "page mapping is broken" in msg, str(msg))
msg, _ = load_single(store(complete=False))
check("an incomplete file refuses", msg is not None and "incomplete" in msg, str(msg))
mixed = [_FakeTensor((755, 128))] * 199 + [_FakeTensor((754, 128))]
msg, _ = load_single(store(embeddings=mixed))
check("pages of different shapes refuse cleanly", msg is not None and "shapes" in msg, str(msg))
msg, _ = load_single(store(), path_exists=False)
check("a missing file refuses with a usable hint", msg is not None and "PAGES_PT" in msg, str(msg))
msg, idx = load_single(store())
check("the original Physics file (no book_id) is ACCEPTED", msg is None, str(msg))
check("... and served as PAGES_BOOK", list(idx.books) == ["Punjab_9_Physics"], str(list(idx.books)))
msg, _ = load_single(store(book_id="Sindh_10_Maths"))
check("a single file holding another book refuses", msg is not None and "Sindh_10_Maths" in msg)

print("\nINDEX_DIR: every book, one model")
books = {
    "Punjab_9_Physics": store(pages=200, book_id="Punjab_9_Physics", expected_pages=200),
    "Sindh_10_Maths": store(pages=317, book_id="Sindh_10_Maths", expected_pages=317),
    "Punjab_11_Biology": store(pages=156, book_id="Punjab_11_Biology", expected_pages=156),
}
msg, idx = load_dir(books, extra_files=["logs"])
check("three books load", msg is None and len(idx.books) == 3, str(msg))
check("total pages add up", idx.total_pages == 200 + 317 + 156, str(idx.total_pages))
check("each book keeps its own page count", len(idx.books["Sindh_10_Maths"].pages) == 317)
check("a folder without an index is ignored", "logs" not in idx.books)
msg, idx = load_dir(books, allow=["Sindh_10_Maths"])
check("BOOKS narrows the set", msg is None and list(idx.books) == ["Sindh_10_Maths"], str(msg))
msg, _ = load_dir(books, allow=["Sindh_12_Urdu"])
check("BOOKS naming a missing book refuses", msg is not None and "Sindh_12_Urdu" in msg, str(msg))
bad = dict(books, Sindh_10_Maths=store(pages=317, book_id="Punjab_9_Physics"))
msg, _ = load_dir(bad)
check("a file holding the wrong book refuses", msg is not None and "holds book" in msg, str(msg))
bad = dict(books, Sindh_10_Maths=store(pages=list(range(1, 317)), expected_pages=317))
msg, _ = load_dir(bad)
check("one incomplete book refuses the whole start", msg is not None and "1-317" in msg, str(msg))
bad = dict(books, Sindh_10_Maths=store(checkpoint="vidore/colpali-v1.3"))
msg, _ = load_dir(bad)
check("one book from another model refuses", msg is not None and "checkpoint" in msg, str(msg))
other_dim = [_FakeTensor((1031, 128)) for _ in range(317)]
bad = dict(books, Sindh_10_Maths=store(pages=317, embeddings=other_dim))
msg, _ = load_dir(bad)
check("books with different vector counts refuse", msg is not None and "per page" in msg, str(msg))
msg, _ = load_dir({})
check("an empty INDEX_DIR refuses", msg is not None and "no <book>" in msg, str(msg))

print("\nbook resolution and anchor bounds")
_, idx = load_dir(books)
app.index = idx
check("an explicit book is used", app.resolve_book_id("Sindh_10_Maths") == "Sindh_10_Maths")
check(
    "no book with several loaded falls back to PAGES_BOOK",
    app.resolve_book_id(None) == "Punjab_9_Physics",
)
_, single = load_single(store())
app.index = single
check("no book with one loaded uses that one", app.resolve_book_id(None) == "Punjab_9_Physics")
app.index = idx
for book_id, anchor, label in (
    ("Punjab_7_Art", None, "an unknown book is 404"),
    ("Punjab_11_Biology", (150, 157), "an anchor past the last page is 400"),
    ("Punjab_11_Biology", (10, 5), "a reversed anchor is 400"),
    ("Punjab_11_Biology", (0, 3), "an anchor before page 1 is 400"),
):
    try:
        idx.search(book_id, "x", 3, anchor)
        check(label, False, "it was accepted")
    except Exception as exc:
        want = 404 if "unknown" in label else 400
        check(label, getattr(exc, "status_code", None) == want, repr(exc))

print("\ncache key")
check("case is ignored", app.normalise("Thermocouple") == app.normalise("thermocouple"))
check("whitespace is collapsed", app.normalise("  a   b  ") == "a b")
check(
    "distinct questions stay distinct",
    app.normalise("what is heat") != app.normalise("what is heat capacity"),
)
check("urdu script keys on itself", app.normalise("ثرموکپل") == "ثرموکپل")

print("\nsecret comparison")
app.SHARED_SECRET = "s3cret"
try:
    app._check_secret("s3cret")
    check("the right secret passes", True)
except Exception as exc:
    check("the right secret passes", False, repr(exc))

for bad_secret, label in (
    (None, "missing"),
    ("", "empty"),
    ("wrong", "wrong"),
    ("s3cre", "truncated"),
):
    try:
        app._check_secret(bad_secret)
        check(f"a {label} secret is rejected", False, "it was accepted")
    except Exception as exc:
        check(f"a {label} secret is rejected", getattr(exc, "status_code", None) == 401, repr(exc))

app.SHARED_SECRET = ""
try:
    app._check_secret(None)
    check("an unset secret disables the check", True)
except Exception as exc:
    check("an unset secret disables the check", False, repr(exc))

print("\nrequest validation")
from pydantic import ValidationError  # noqa: E402

ok = app.RetrieveRequest(question="x")
check("top_k defaults to 3", ok.top_k == 3)
check("book defaults to None (an older backend sends none)", ok.book is None)
check("anchor defaults to None", ok.anchor is None)
legacy = app.RetrieveRequest(question="x", chapter=7)
check("an older backend's `chapter` field is ignored, not rejected", legacy.anchor is None)
check(
    "an anchor parses as a pair",
    app.RetrieveRequest(question="x", anchor=[148, 160]).anchor == (148, 160),
)
for payload, label in (
    ({"question": ""}, "empty question"),
    ({"question": "x" * 2001}, "over-long question"),
    ({"question": "x", "top_k": 0}, "top_k 0"),
    ({"question": "x", "top_k": 11}, "top_k 11"),
    ({"question": "x", "book": ""}, "empty book"),
    ({"question": "x", "anchor": [1, 2, 3]}, "three-number anchor"),
):
    try:
        app.RetrieveRequest(**payload)
        check(f"{label} is rejected", False, "it was accepted")
    except ValidationError:
        check(f"{label} is rejected", True)

print("\nconfiguration sanity")
check(
    "MAX_WAIT_S stays under the backend's 20s read timeout",
    app.MAX_WAIT_S < 20,
    f"MAX_WAIT_S={app.MAX_WAIT_S}",
)
check(
    "ANCHOR_PRIOR is a small fraction",
    0 < app.ANCHOR_PRIOR < 0.5,
    f"ANCHOR_PRIOR={app.ANCHOR_PRIOR}",
)
check("CACHE_SIZE is positive", app.CACHE_SIZE > 0)
check(
    "the query model is pinned to ml/indexing's revisions",
    app.PINNED_REVISIONS.get("vidore/colqwen2-v1.0")
    == ("2b6ac8fb37f46a49e4841e599583d00ae8a20117", "9fe8a713422a7cb4ef79ca77a09b381ee2243101"),
)
check("the service holds no chapter table", not hasattr(app, "CHAPTERS"))

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED:
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
