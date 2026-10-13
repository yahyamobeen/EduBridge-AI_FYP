"""Self-test for the retrieval service, with no model and no spare RAM required.

Exercises the parts that are easy to get wrong and hard to notice: the three startup
guards, the cache key, the anchor prior and the secret comparison. `torch` is stubbed,
so this runs anywhere - including a machine that cannot hold ColQwen2.

⚠️ It does NOT test the forward pass or the MaxSim arithmetic. Those need the real
model; `measure.py` on the deployment target is what covers them.

    python selftest.py
"""

from __future__ import annotations

import sys
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
# every path the guards take. `load` is replaced per-test.

_stub = types.ModuleType("torch")
_stub.float32 = "float32"
_stub.load = lambda *a, **k: {}
_stub.stack = lambda tensors: _FakeStacked(tensors)
_stub.get_num_threads = lambda: 2
_stub.set_num_threads = lambda n: None
_stub.set_num_interop_threads = lambda n: None
sys.modules.setdefault("torch", _stub)


class _FakeTensor:
    def __init__(self, shape):
        self.shape = shape

    def to(self, _dtype):
        return self


class _FakeStacked:
    """Just enough shape for `load()` to record vectors_per_page and dim."""

    def __init__(self, tensors):
        count = len(tensors)
        vectors, dim = tensors[0].shape if tensors else (0, 0)
        self.shape = (count, vectors, dim)


import app  # noqa: E402  (must follow the torch stub)


def store(checkpoint="vidore/colqwen2-v1.0", pages=None, embeddings=None, complete=True):
    pages = list(range(1, 201)) if pages is None else pages
    if embeddings is None:
        embeddings = [_FakeTensor((755, 128)) for _ in pages]
    return {
        "checkpoint": checkpoint,
        "pages": pages,
        "embeddings": embeddings,
        "complete": complete,
        "dim": 128,
    }


def load_with(fake_store, path_exists=True):
    """Run `Index.load()` against a fake store. Returns the SystemExit message, or None."""
    _stub.load = lambda *a, **k: fake_store
    app.EMBEDDINGS_PATH = Path("fake-pages.pt") if path_exists else Path("does-not-exist.pt")
    original_exists = Path.exists
    Path.exists = lambda self: path_exists  # type: ignore[method-assign]
    index = app.Index()
    index._load_model = lambda: None  # the guards are the subject, not the model
    try:
        index.load()
        return None
    except SystemExit as exc:
        return str(exc)
    finally:
        Path.exists = original_exists  # type: ignore[method-assign]


print("guards (each must REFUSE, before the model loads)")

msg = load_with(store(checkpoint="vidore/colpali-v1.3"))
check(
    "guard 1: checkpoint mismatch refuses",
    msg is not None and "checkpoint mismatch" in msg,
    str(msg),
)
check(
    "guard 1: message names both checkpoints",
    msg is not None and "colpali-v1.3" in msg and "colqwen2-v1.0" in msg,
    str(msg),
)

msg = load_with(store(pages=list(range(1, 200))))
check(
    "guard 2: 199 pages refuses",
    msg is not None and "does not cover pages 1-200" in msg,
    str(msg),
)
check("guard 2: message names a missing page", msg is not None and "200" in msg, str(msg))

msg = load_with(store(pages=list(range(1, 201)) + [201]))
check("guard 2: an out-of-range page refuses", msg is not None, str(msg))

msg = load_with(store(pages=[5] * 200))
check("guard 2: duplicate pages refuse", msg is not None, str(msg))

msg = load_with(store(embeddings=[_FakeTensor((755, 128))] * 199))
check(
    "guard 3: length mismatch refuses",
    msg is not None and "page mapping is broken" in msg,
    str(msg),
)

msg = load_with(store(complete=False))
check("guard 4: incomplete file refuses", msg is not None and "incomplete" in msg, str(msg))

msg = load_with(store(), path_exists=False)
check("missing file refuses with a usable hint", msg is not None and "PAGES_PT" in msg, str(msg))

msg = load_with(store())
check("a correct file is ACCEPTED", msg is None, str(msg))

print("\ncache key")
check("case is ignored", app.normalise("Thermocouple") == app.normalise("thermocouple"))
check("whitespace is collapsed", app.normalise("  a   b  ") == "a b")
check(
    "distinct questions stay distinct",
    app.normalise("what is heat") != app.normalise("what is heat capacity"),
)
check("urdu script keys on itself", app.normalise("ثرموکپل") == "ثرموکپل")

print("\nchapter mapping")
check("front matter has no chapter", app.chapter_of(1) is None)
check("p5 is chapter 1", app.chapter_of(5) == 1)
check("p148 is chapter 7", app.chapter_of(148) == 7)
check("p155 is chapter 7", app.chapter_of(155) == 7)
check("p195 is back matter", app.chapter_of(195) is None)
check(
    "every chapter range is non-empty and ordered",
    all(lo <= hi for lo, hi in app.CHAPTERS.values()),
)
check(
    "chapter ranges do not overlap",
    all(app.CHAPTERS[i][1] < app.CHAPTERS[i + 1][0] for i in range(1, 9)),
)

print("\nsecret comparison")
app.SHARED_SECRET = "s3cret"
try:
    app._check_secret("s3cret")
    check("the right secret passes", True)
except Exception as exc:
    check("the right secret passes", False, repr(exc))

for bad, label in ((None, "missing"), ("", "empty"), ("wrong", "wrong"), ("s3cre", "truncated")):
    try:
        app._check_secret(bad)
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
check("chapter defaults to None", ok.chapter is None)
for payload, label in (
    ({"question": ""}, "empty question"),
    ({"question": "x" * 2001}, "over-long question"),
    ({"question": "x", "top_k": 0}, "top_k 0"),
    ({"question": "x", "top_k": 11}, "top_k 11"),
    ({"question": "x", "chapter": 0}, "chapter 0"),
    ({"question": "x", "chapter": 10}, "chapter 10"),
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
check("BOOK_PAGES matches the backend", app.BOOK_PAGES == 200)

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED:
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
