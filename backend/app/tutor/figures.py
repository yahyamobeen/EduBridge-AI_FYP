"""Figure crops from the generator's bounding box (tdd.md §3.2a, prd.md MM-1).

`prd.md` MM-1's visual ladder begins "retrieve the indexed textbook figure" - and there
is no `textbook_figure` index, because the whole knowledge-base layer is deferred. But
the generator is already looking at the page image, so it can say where the figure is.
The backend crops the scan from that box.

⚠️ THE BOX IS UNTRUSTED MODEL OUTPUT, and every rule in `parse_box` exists because of
that. `tdd.md` §4.6 requires model-adjacent content be handled as data, and MM-2 says the
same of model-written visual code. A box is smaller than code but it still reaches
`Image.crop`, so it is clamped, bounded and sanity-checked before it reaches Pillow -
never because the model is expected to be malicious, but because a model that is merely
WRONG produces a one-pixel crop or a 4000:1 sliver, and either renders as a broken
figure the student cannot interpret.

⚠️ The crop MUST be served same-origin. The frontend CSP is `img-src 'self' data:` with no
`images.remotePatterns`, so an external URL in an `<img>` is blocked by the browser - this
is also why the classroom feature opens private files in a new tab instead.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("edubridge.tutor.figures")

# The sentinel the generator wraps its box in. Deliberately not valid prose and not
# markdown: it must be impossible to produce by accident while explaining physics, and
# recognisable from its first two characters so the stream guard can hold back a partial.
MARKER = "@@FIGURE"

# Below this fraction of the page in either dimension the crop is not a figure, it is a
# misfire - and a 2%-tall strip rendered as "the diagram" is worse than no diagram.
MIN_SIDE = 0.04
# A figure can be wide (a table) or tall (an apparatus diagram), but not a sliver.
MAX_ASPECT = 12.0


@dataclass(frozen=True)
class FigureBox:
    """A validated crop region, in fractions of the page."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    caption: str

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Fractions to pixels, rounded outward so a thin label is not clipped off."""
        left = max(0, int(self.x0 * width))
        top = max(0, int(self.y0 * height))
        right = min(width, int(self.x1 * width) + 1)
        bottom = min(height, int(self.y1 * height) + 1)
        return left, top, right, bottom


def parse_box(raw: object, *, book_pages: int) -> FigureBox | None:
    """A validated `FigureBox`, or None if the model's box cannot be trusted.

    Returns None rather than raising: a bad box means no figure, which is a perfectly
    good answer. It must never mean no ANSWER - the prose is already streaming by the
    time this runs.
    """
    if not isinstance(raw, dict):
        return None

    page = raw.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= book_pages:
        return None

    box = raw.get("box")
    if not isinstance(box, list) or len(box) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in box)
    except (TypeError, ValueError):
        return None

    # Clamp before comparing, so a model that overshoots slightly (0 -> -0.02, or
    # 1 -> 1.03, both common) still yields a usable crop instead of being discarded.
    x0, y0, x1, y1 = (min(1.0, max(0.0, v)) for v in (x0, y0, x1, y1))

    if x1 <= x0 or y1 <= y0:
        # Inverted or zero-area. Pillow would accept an inverted box and return an
        # empty image, which reaches the student as a broken picture rather than an
        # error - so this is caught here.
        return None

    width, height = x1 - x0, y1 - y0
    if width < MIN_SIDE or height < MIN_SIDE:
        return None
    if max(width / height, height / width) > MAX_ASPECT:
        return None

    caption = raw.get("caption")
    caption = caption.strip()[:200] if isinstance(caption, str) else ""

    return FigureBox(page=page, x0=x0, y0=y0, x1=x1, y1=y1, caption=caption)


def crop_page(pages_dir: Path, box: FigureBox) -> bytes | None:
    """The cropped region as JPEG bytes, or None if the page scan is unavailable."""
    path = pages_dir / f"p{box.page:03}.jpeg"
    if not path.exists():
        logger.warning("page scan missing for figure crop: %s", path.name)
        return None

    from PIL import Image

    try:
        with Image.open(path) as image:
            cropped = image.crop(box.pixels(image.width, image.height))
            out = io.BytesIO()
            # The source is a 150 DPI scan already compressed once; 88 keeps the
            # second generation from visibly softening small subscripts.
            cropped.save(out, format="JPEG", quality=88)
            return out.getvalue()
    except Exception as exc:
        logger.warning("could not crop %s: %s", path.name, type(exc).__name__)
        return None


class MarkerGuard:
    """Strips the figure marker out of a token stream before the student sees it.

    ⚠️ THE HELD-BACK TAIL IS THE WHOLE POINT. The marker arrives split across chunks
    whenever the network or the model decides to split it - `@@FIG` in one token and
    `URE {...}` in the next is ordinary. Emitting each chunk as it arrives therefore
    leaks `@@FIG` into the answer, visibly, and only sometimes. So the last
    `len(MARKER) - 1` characters are held back until they are known not to be the start
    of one.

    The marker is instructed to be the LAST thing in the response, so once it is seen
    nothing further is emitted - the remaining text is the JSON block.
    """

    def __init__(self, marker: str = MARKER) -> None:
        self._marker = marker
        self._buffer = ""
        self._emitted = 0
        self._found = False

    def feed(self, chunk: str) -> str:
        """Text that is safe to send now. May be empty."""
        self._buffer += chunk
        if self._found:
            return ""

        index = self._buffer.find(self._marker)
        if index != -1:
            self._found = True
            safe = self._buffer[self._emitted : index]
            self._emitted = len(self._buffer)
            return safe

        # Hold back anything that could still turn out to be a marker prefix.
        limit = len(self._buffer) - (len(self._marker) - 1)
        if limit <= self._emitted:
            return ""
        safe = self._buffer[self._emitted : limit]
        self._emitted = limit
        return safe

    def finish(self) -> tuple[str, object | None]:
        """Remaining safe text, and the raw figure object if one was found.

        Parsing failures return `None` for the figure and still return the text: a
        malformed box must cost the figure, never the answer.
        """
        tail = "" if self._found else self._buffer[self._emitted :]
        self._emitted = len(self._buffer)

        if not self._found:
            return tail, None

        block = self._buffer[self._buffer.find(self._marker) + len(self._marker) :].strip()
        # Tolerate a fenced block, which models add unprompted.
        if block.startswith("```"):
            block = block.strip("`").lstrip("json").strip()
        try:
            return tail, json.loads(block)
        except ValueError:
            logger.info("figure marker present but its payload did not parse")
            return tail, None
