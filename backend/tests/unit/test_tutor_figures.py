"""Figure boxes and the marker guard (tdd.md §3.2a, prd.md MM-1/MM-2).

Two things are tested here, and both exist because of a specific failure:

* `parse_box` treats the generator's box as untrusted input. Not because the model is
  expected to be malicious, but because a model that is merely WRONG hands `Image.crop`
  a one-pixel region or a 4000:1 sliver, and either reaches the student as a broken
  figure they cannot interpret.
* `MarkerGuard` holds back a trailing tail so `@@FIG` never reaches the student because
  a chunk boundary fell mid-sentinel. That split is ordinary, not exotic.
"""

from __future__ import annotations

import io
import json

import pytest

from app.tutor.figures import MARKER, MarkerGuard, crop_page, parse_box

BOOK_PAGES = 200


def box(**overrides):
    base = {"page": 155, "box": [0.1, 0.2, 0.9, 0.7], "caption": "Fig. 7.8"}
    base.update(overrides)
    return base


def test_a_good_box_is_accepted():
    parsed = parse_box(box(), book_pages=BOOK_PAGES)
    assert parsed is not None
    assert parsed.page == 155
    assert (parsed.x0, parsed.y0, parsed.x1, parsed.y1) == (0.1, 0.2, 0.9, 0.7)
    assert parsed.caption == "Fig. 7.8"


def test_slight_overshoot_is_clamped_not_discarded():
    """Models routinely return -0.02 or 1.03. Clamping keeps a usable crop; rejecting
    would throw away a figure that was essentially right."""
    parsed = parse_box(box(box=[-0.05, -0.01, 1.04, 0.72]), book_pages=BOOK_PAGES)
    assert parsed is not None
    assert parsed.x0 == 0.0
    assert parsed.y0 == 0.0
    assert parsed.x1 == 1.0


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        (box(box=[0.9, 0.2, 0.1, 0.7]), "inverted horizontally"),
        (box(box=[0.1, 0.7, 0.9, 0.2]), "inverted vertically"),
        (box(box=[0.5, 0.5, 0.5, 0.5]), "zero area"),
        (box(box=[0.5, 0.5, 0.51, 0.9]), "too narrow to be a figure"),
        (box(box=[0.1, 0.5, 0.9, 0.51]), "too short to be a figure"),
        (box(box=[0.0, 0.45, 1.0, 0.5]), "aspect ratio is a sliver"),
        (box(page=0), "page below the book"),
        (box(page=201), "page past the book"),
        (box(page="155"), "page is a string"),
        (box(page=True), "page is a bool"),
        (box(box=[0.1, 0.2, 0.9]), "only three coordinates"),
        (box(box="0.1,0.2,0.9,0.7"), "box is a string"),
        (box(box=[0.1, 0.2, 0.9, "x"]), "a coordinate is not a number"),
        ("not an object", "not an object at all"),
        (None, "nothing"),
    ],
)
def test_a_box_that_cannot_be_trusted_yields_no_figure(bad, why):
    """None rather than an exception, every time.

    A bad box means no figure, which is a perfectly good answer. It must never mean no
    ANSWER - the prose is already streaming by the time this runs.
    """
    assert parse_box(bad, book_pages=BOOK_PAGES) is None, why


def test_an_inverted_box_would_otherwise_reach_pillow():
    """Pillow ACCEPTS an inverted box and returns an empty image, which arrives as a
    broken picture rather than an error. That is why the check is here and not there."""
    assert parse_box(box(box=[0.9, 0.7, 0.1, 0.2]), book_pages=BOOK_PAGES) is None


def test_a_caption_is_bounded_and_a_non_string_is_dropped():
    assert parse_box(box(caption="x" * 500), book_pages=BOOK_PAGES).caption == "x" * 200
    assert parse_box(box(caption=None), book_pages=BOOK_PAGES).caption == ""
    assert parse_box(box(caption={"a": 1}), book_pages=BOOK_PAGES).caption == ""


def test_pixels_round_outward():
    """A thin caption at the edge of the box must not be clipped off by rounding."""
    parsed = parse_box(box(box=[0.0, 0.0, 0.5, 0.5]), book_pages=BOOK_PAGES)
    assert parsed.pixels(1000, 1000) == (0, 0, 501, 501)


# -- the marker guard -------------------------------------------------------


def drain(guard: MarkerGuard, chunks: list[str]) -> tuple[str, object | None]:
    visible = "".join(guard.feed(chunk) for chunk in chunks)
    tail, raw = guard.finish()
    return visible + tail, raw


def test_plain_prose_passes_through_unchanged():
    text, raw = drain(MarkerGuard(), ["Heat ", "is ", "energy ", "in transit."])
    assert text == "Heat is energy in transit."
    assert raw is None


def test_the_marker_is_stripped_and_parsed():
    payload = json.dumps(box())
    text, raw = drain(MarkerGuard(), [f"Heat is energy.\n\n{MARKER} {payload}"])
    assert text == "Heat is energy.\n\n"
    assert raw == box()


def test_the_marker_split_across_chunks_never_leaks():
    """⚠️ THE CASE THIS CLASS EXISTS FOR.

    `@@FIG` in one token and `URE {...}` in the next is ordinary - the model and the
    network both split wherever they like. Emitting each chunk as it arrives leaks
    `@@FIG` into the answer, visibly, and only sometimes.
    """
    payload = json.dumps(box())
    chunks = ["Heat is energy.", "\n\n@@", "FIG", "URE ", payload[:20], payload[20:]]
    text, raw = drain(MarkerGuard(), chunks)
    assert text == "Heat is energy.\n\n"
    assert "@@" not in text
    assert "FIG" not in text
    assert raw == box()


@pytest.mark.parametrize("split_at", range(1, len(MARKER)))
def test_no_split_point_leaks_the_marker(split_at):
    """Every possible split of the sentinel, not just a convenient one."""
    payload = json.dumps(box())
    chunks = ["Answer. ", MARKER[:split_at], MARKER[split_at:], " ", payload]
    text, raw = drain(MarkerGuard(), chunks)
    assert text == "Answer. "
    assert raw == box()


def test_a_fenced_payload_is_tolerated():
    """Models add ``` unprompted, however the prompt is worded."""
    payload = json.dumps(box())
    text, raw = drain(MarkerGuard(), [f"Answer.\n{MARKER}\n```json\n{payload}\n```"])
    assert text.startswith("Answer.")
    assert raw == box()


def test_a_malformed_payload_costs_the_figure_not_the_answer():
    text, raw = drain(MarkerGuard(), [f"Heat is energy.\n{MARKER} {{not json"])
    assert text == "Heat is energy.\n"
    assert raw is None


def test_text_that_merely_resembles_the_marker_is_still_delivered():
    """A held-back tail must be flushed, not swallowed, when no marker arrives."""
    text, raw = drain(MarkerGuard(), ["The email is a@@b.com"])
    assert text == "The email is a@@b.com"
    assert raw is None


# -- cropping ---------------------------------------------------------------


def test_cropping_produces_a_jpeg_of_the_requested_region(tmp_path):
    from PIL import Image

    Image.new("RGB", (1000, 1400), (255, 255, 255)).save(tmp_path / "p155.jpeg")

    parsed = parse_box(box(box=[0.0, 0.0, 0.5, 0.25]), book_pages=BOOK_PAGES)
    data = crop_page(tmp_path, parsed)

    assert data is not None
    with Image.open(io.BytesIO(data)) as cropped:
        assert cropped.format == "JPEG"
        # Half the width, a quarter of the height, plus the outward rounding.
        assert cropped.width == 501
        assert cropped.height == 351


def test_a_missing_page_scan_yields_no_crop(tmp_path):
    parsed = parse_box(box(), book_pages=BOOK_PAGES)
    assert crop_page(tmp_path, parsed) is None
