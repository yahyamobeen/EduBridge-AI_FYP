"""Measure query-encode latency for the retrieval service (tdd.md §3.2a).

This produces the number the tutor work has been waiting on: how long ColQwen2 takes to
encode one query on the hardware it will actually run on. Everything else about the
approach is settled; this decides whether it ships on CPU or needs a GPU.

Run it on the deployment target, not on a laptop:

    python measure.py

Then run it again with the ISA capped, to see whether AMX is doing the work:

    ONEDNN_MAX_CPU_ISA=AVX512_CORE_BF16 python measure.py

!! The A/B must be two separate processes. oneDNN reads ONEDNN_MAX_CPU_ISA once, when it
initialises, so setting it from inside a running process does nothing.

What to record in the contract:
  * median CACHED encode   -> NFR-1's "under 3 s for cached curriculum queries"
  * median UNCACHED encode -> a measurement; the contract sets no budget for it
  * whether AMX engaged    -> the entire argument for the m7i instance family
"""

from __future__ import annotations

import os
import statistics
import sys
import time

# Importing the service gives us the same Index, the same guards and the same load
# path - so this measures what actually serves, not a reimplementation of it.
from app import DTYPE, EMBEDDINGS_PATH, index

# Real questions, at realistic lengths and in all three languages. Latency scales with
# token count, so measuring on "test" would flatter the result. Taken from the labelled
# evaluation set; the Urdu-script entry is last so a console that cannot encode it fails
# after the numbers are already printed.
QUESTIONS = [
    ("en", "how does a thermocouple thermometer work"),
    ("en", "convert celsius to fahrenheit formula"),
    ("en", "what is absolute zero"),
    ("en", "kinetic molecular theory of matter"),
    ("en", "what is plasma the fourth state of matter"),
    ("en", "labelled diagram of a laboratory thermometer"),
    ("en", "comparison of the three temperature scales"),
    ("en", "what are the basic thermometric properties"),
    ("en", "what is internal energy of a body"),
    ("en", "define heat as energy in transit"),
    ("en", "law of conservation of momentum"),
    ("en", "what is moment of force or torque"),
    ("en", "applications of hookes law"),
    ("en", "uses of electromagnets in telephone and cranes"),
    ("en", "labelled parts of vernier callipers"),
    ("ur-Latn", "thermocouple thermometer kaise kaam karta hai"),
    ("ur-Latn", "celsius ko fahrenheit mein convert karne ka formula"),
    ("ur-Latn", "plasma kya hai aur ye fourth state kyun kehlata hai"),
    ("ur-Latn", "vernier callipers ke parts"),
    (
        "ur",
        "\u062b\u0631\u0645\u0648\u06a9\u067e\u0644 \u062a\u06be\u0631\u0645\u0627\u0645\u06cc\u0679\u0631 \u06a9\u06cc\u0633\u06d2 \u06a9\u0627\u0645 \u06a9\u0631\u062a\u0627 \u06c1\u06d2",
    ),
]


def cpu_flags() -> set[str]:
    """CPU feature flags, on Linux. Empty elsewhere."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("flags") or line.startswith("Features"):
                    return set(line.split(":", 1)[1].split())
    except OSError:
        pass
    return set()


def peak_rss_mb() -> float | None:
    """Peak resident set size in MB, on Linux. None elsewhere.

    Worth recording next to the latency: the instance has to hold this, and the whole
    reason the model is not in the backend process is that 512 MB cannot.
    """
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


def report_hardware() -> None:
    import torch

    flags = cpu_flags()
    isa_cap = os.environ.get("ONEDNN_MAX_CPU_ISA", "(uncapped)")

    print("hardware")
    print(f"  torch              {torch.__version__}")
    print(f"  threads            {torch.get_num_threads()}")
    print(f"  dtype              {DTYPE}")
    print(f"  ONEDNN_MAX_CPU_ISA {isa_cap}")

    if not flags:
        print("  cpu flags          unavailable (not Linux) - run this on the target")
        return

    amx = "amx_bf16" in flags
    avx512_bf16 = "avx512_bf16" in flags
    print(f"  amx_bf16           {'YES' if amx else 'no'}")
    print(f"  avx512_bf16        {'yes' if avx512_bf16 else 'no'}")

    if amx and isa_cap == "(uncapped)":
        print("  -> AMX is available and uncapped: bfloat16 should be the FAST path.")
    elif amx:
        print(f"  -> AMX present but capped to {isa_cap}: this is the A/B baseline.")
    elif avx512_bf16:
        print("  -> No AMX. AVX512-BF16 only; expect well short of the AMX projection.")
    else:
        print(
            "  -> Neither AMX nor AVX512-BF16. bfloat16 here is a FIT decision, not a\n"
            "     speed one: torch materialises an fp32 temporary per matmul, which is\n"
            "     SLOWER than float32. This is the laptop case, and it is why 6.1 s was\n"
            "     measured there. Do not read this run as the deployment number."
        )


def run(label: str) -> list[float]:
    """One pass over every question. Returns per-question encode seconds."""
    timings: list[float] = []
    for lang, question in QUESTIONS:
        started = time.monotonic()
        pages, _scores, encode_s, search_s, cached = index.search(question, 3, None)
        total = time.monotonic() - started
        timings.append(encode_s)
        print(
            f"  {label:8} {lang:8} encode {encode_s * 1000:8.1f}ms  "
            f"search {search_s * 1000:6.1f}ms  total {total * 1000:8.1f}ms  "
            f"{'HIT ' if cached else 'miss'}  top={pages[:3]}"
        )
    return timings


def summarise(name: str, timings: list[float]) -> float:
    median = statistics.median(timings)
    print(
        f"  {name:10} median {median * 1000:8.1f}ms   "
        f"min {min(timings) * 1000:7.1f}ms   max {max(timings) * 1000:8.1f}ms"
    )
    return median


def main() -> None:
    print(f"embeddings: {EMBEDDINGS_PATH}")
    load_started = time.monotonic()
    index.load()
    load_s = time.monotonic() - load_started
    print(f"loaded in {load_s:.1f}s\n")

    report_hardware()
    print()

    print(f"pass 1 - cold cache, {len(QUESTIONS)} distinct questions")
    uncached = run("cold")
    print()

    print("pass 2 - same questions, cache warm")
    cached = run("warm")
    print()

    print("results")
    uncached_median = summarise("uncached", uncached)
    cached_median = summarise("cached", cached)
    total = index.hits + index.misses
    print(f"  cache      {index.hits} hits / {total} ({index.hits / total:.0%})")
    print(f"  model load {load_s:.1f}s")
    if (rss := peak_rss_mb()) is not None:
        print(f"  peak RSS   {rss:.0f} MB")
    print()

    # NFR-1 is scoped to CACHED curriculum queries (prd.md:835). The uncached figure is
    # recorded as a measurement, not a pass/fail - the contract sets no budget for it.
    budget = 3.0
    verdict = "WITHIN" if cached_median < budget else "OVER"
    print(f"NFR-1 (cached, under {budget:.0f}s): {verdict} - {cached_median * 1000:.1f}ms")
    print(f"uncached, for the record:            {uncached_median * 1000:.1f}ms")
    if uncached_median >= budget:
        print(
            "\n!! Uncached encoding exceeds 3 s. That does not breach NFR-1, which is\n"
            "  scoped to cached queries, but it does mean a NOVEL question is slow and\n"
            "  the cache is carrying the requirement. Record the cache hit rate\n"
            "  alongside this number or the NFR-1 claim is unevidenced."
        )


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        # The startup guards raise SystemExit with a reason. Surface it plainly rather
        # than as a traceback - a checkpoint mismatch is a configuration answer.
        print(f"\nrefused to start: {exc}", file=sys.stderr)
        raise
