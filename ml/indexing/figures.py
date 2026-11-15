"""Figure boxes for every book, from Docling's layout model (prd.md MM-1, step 1).

Two commands, on two machines:

    python figures.py detect --input DATA --out out    # the GPU machine, after encode_books run
    python figures.py build --out out                  # the owner's laptop, CPU, no Docling

`detect` runs Docling's layout model only (no OCR, no table structure) and keeps its RAW
output, `docling.json`, per book. `build` turns that into `figures.json` plus a review page.
The split is deliberate: the filters below need tuning by eye, and every tuning round must
happen on the owner's machine, never as another request to the person with the GPU.

Docling is used for LOCATING figures only. Its text output silently drops lines beside
floated figures (tutor-rag-handoff.md 4.5), so no text from it is used except a caption,
and the caption is a label, never a source.
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

import argparse
import html
import json
import re
import sys
import tempfile
import time
import traceback
import unicodedata
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import encode_books as eb  # noqa: E402 - the path insert above must come first

# Pinned like the ColQwen2 revisions: Docling's default is the moving `main`.
LAYOUT_REPO = "docling-project/docling-layout-heron"
LAYOUT_REVISION = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"  # 2026-02-09, "Update config.json"

# Mirrors backend/app/tutor/figures.py:38-40, so every stored box is one the backend's own
# validation would accept.
MIN_SIDE = 0.04
MAX_ASPECT = 12.0
MAX_AREA = 0.90  # a "figure" this large is the whole scan detected as one picture
REPEAT_IOU = 0.9
REPEAT_FRACTION = 0.2  # the same box on this share of pages is a logo, header or ornament
CAPTION_MAX_GAP = 0.08  # of the page height, between figure and a caption found by search
CAPTION_MIN_OVERLAP = 0.3  # horizontal overlap, as a share of the narrower box
CAPTION_MAX_CHARS = 160  # longer is a paragraph that happens to start "Figure 7.6 shows..."

# "Fig. 7.1", "Figure 7.6", "Fig. 7.3 (a)", "Fig. 7,3(a)", "Table 3.2", and the Urdu words
# for figure and table (shakl, jadwal), written as escapes so this file stays ASCII.
CAPTION_RE = re.compile(
    r"^\s*(Fig(?:ure)?|Table|\u0634\u06a9\u0644|\u062c\u062f\u0648\u0644)\s*\.?\s*(?:No\.?\s*)?"
    # a sub-figure letter only as "(a)", "-a" or attached ("7.3a"), never the next word
    r"(\d+(?:[.,]\d+)*)(?:\s*\(\s*([a-zA-Z])\s*\)|\s*-\s*([a-zA-Z])(?![a-zA-Z])|([a-zA-Z])(?![a-zA-Z]))?",
    re.IGNORECASE,
)


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in text)


def parse_caption(text: str) -> tuple[str, str] | None:
    """(kind, number) from a caption's start, e.g. ('picture', '7.3(a)'), or None."""
    match = CAPTION_RE.match(text or "")
    if not match:
        return None
    word = match.group(1).lower()
    kind = "table" if word in ("table", "\u062c\u062f\u0648\u0644") else "picture"
    # the PDF's OCR text layer sometimes reads the decimal point as a comma ("7,3(a)")
    number = _ascii_digits(match.group(2)).replace(",", ".")
    letter = match.group(3) or match.group(4) or match.group(5)
    if letter:
        number += f"({letter.lower()})"
    return kind, number


# -- detect (GPU machine) ----------------------------------------------------------------


def make_converter(device: str):
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    options.do_ocr = False  # captions come from the PDF's own text layer, at no cost
    options.do_table_structure = False  # table REGIONS are still detected; cells are not
    options.generate_page_images = False
    options.generate_picture_images = False
    spec = options.layout_options.model_spec
    if spec.repo_id != LAYOUT_REPO:
        raise eb.ToolError(f"Docling's layout model is {spec.repo_id}, expected {LAYOUT_REPO}")
    options.layout_options.model_spec = spec.model_copy(update={"revision": LAYOUT_REVISION})
    accel = AcceleratorDevice.CUDA if device.startswith("cuda") else AcceleratorDevice.CPU
    options.accelerator_options = AcceleratorOptions(device=accel)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def warm_up(device: str) -> float:
    """Convert a one-page synthetic PDF: downloads the layout model if it is missing and
    proves the pipeline runs on this device, before the long run depends on it."""
    import pymupdf

    started = time.time()
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "warmup.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=504, height=666)
        page.draw_rect(pymupdf.Rect(100, 120, 400, 380), color=(0, 0, 0), fill=(0.6, 0.7, 0.9))
        page.insert_text((100, 400), "Fig. 1.1 Warm-up figure", fontsize=11)
        page.insert_text((60, 450), "Body text under the figure for the layout model.", fontsize=11)
        doc.save(pdf)
        doc.close()
        result = make_converter(device).convert(pdf)
        if result.document is None:
            raise eb.ToolError(f"Docling returned no document ({result.status})")
    return time.time() - started


def cmd_detect(args) -> int:
    import torch

    eb.keep_awake()
    input_dir, out_dir = Path(args.input), Path(args.out)
    found = eb.discover(input_dir)
    if found.errors:
        print("Fix these first (preflight lists them too):")
        for error in found.errors:
            print(f"  - {error}")
        return 1
    books = eb.order_books(eb.select_books(found.books, args.books))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and not args.allow_cpu:
        print("no CUDA GPU; pass --allow-cpu to run Docling on the CPU (slow)")
        return 1
    from docling_core.types.doc import ImageRefMode

    converter = make_converter(device)
    results: dict[str, str] = {}
    for number, book in enumerate(books, 1):
        book_dir = out_dir / book.book_id
        meta_path = book_dir / "docling.meta.json"
        print(f"\n[{number}/{len(books)}] {book.book_id}")
        try:
            if meta_path.exists() and not args.force:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if (
                    meta.get("source_sha256") == book.sha256
                    and (book_dir / "docling.json").exists()
                ):
                    results[book.book_id] = "skipped (already detected)"
                    print(f"  {results[book.book_id]}")
                    continue
            started = time.time()
            result = converter.convert(book.pdf)
            if result.document is None:
                raise eb.ToolError(f"no document returned ({result.status})")
            book_dir.mkdir(parents=True, exist_ok=True)
            tmp = book_dir / "docling.json.tmp"
            result.document.save_as_json(tmp, image_mode=ImageRefMode.PLACEHOLDER)
            eb.replace_with_retry(tmp, book_dir / "docling.json")
            seconds = time.time() - started
            pages = len(result.document.pages)
            eb.write_json_atomic(
                meta_path,
                {
                    "book_id": book.book_id,
                    "source_sha256": book.sha256,
                    "status": str(result.status),
                    "pages": pages,
                    "pictures": len(result.document.pictures),
                    "tables": len(result.document.tables),
                    "seconds": round(seconds, 1),
                    "device": device,
                    "docling": metadata.version("docling"),
                    "layout_repo": LAYOUT_REPO,
                    "layout_revision": LAYOUT_REVISION,
                    "created_utc": eb.now_utc(),
                },
            )
            results[book.book_id] = (
                f"done: {pages} pages, {len(result.document.pictures)} pictures, "
                f"{len(result.document.tables)} tables in {seconds / 60:.1f} min "
                f"({seconds / max(1, pages):.2f} s/page)"
            )
        except KeyboardInterrupt:
            print("\nInterrupted. Re-run the same command to resume.")
            return 130
        except Exception as exc:  # noqa: BLE001 - one bad book must not stop the rest
            results[book.book_id] = f"FAILED: {type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stdout)
        print(f"  {results[book.book_id]}")
    print("\n== summary")
    for book_id, status in results.items():
        print(f"  {book_id:<32} {status}")
    failed = [b for b, s in results.items() if s.startswith("FAILED")]
    print(f"\nDETECT: {len(results) - len(failed)} ok, {len(failed)} failed")
    return 1 if failed else 0


# -- build (owner's laptop) --------------------------------------------------------------


def top_left_box(bbox: dict, page_height: float) -> tuple[float, float, float, float]:
    """Docling bbox -> (x0, y0, x1, y1) in points with the origin at the top left."""
    left, right = float(bbox["l"]), float(bbox["r"])
    top, bottom = float(bbox["t"]), float(bbox["b"])
    if str(bbox.get("coord_origin", "BOTTOMLEFT")).upper().endswith("BOTTOMLEFT"):
        top, bottom = page_height - top, page_height - bottom
    x0, x1 = sorted((left, right))
    y0, y1 = sorted((top, bottom))
    return x0, y0, x1, y1


def union(a, b):
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / area if area > 0 else 0.0


def to_canvas_fraction(box_pt, placement: dict) -> tuple[float, float, float, float]:
    """Points on the PDF page -> fractions of the served 1049x1387 image (top-left origin),
    through the page's recorded placement (identity-like for copied or stretched pages,
    offset plus scale for letterboxed ones)."""
    w, h = eb.CANVAS
    sx, sy = placement["scale_x"], placement["scale_y"]
    ox, oy = placement["offset_x"], placement["offset_y"]
    x0, y0, x1, y1 = box_pt
    fx = [(ox + x * sx) / w for x in (x0, x1)]
    fy = [(oy + y * sy) / h for y in (y0, y1)]
    return (
        min(1.0, max(0.0, fx[0])),
        min(1.0, max(0.0, fy[0])),
        min(1.0, max(0.0, fx[1])),
        min(1.0, max(0.0, fy[1])),
    )


def find_caption(fig_box, texts_on_page, page_height):
    """The nearest short caption-like text just above or below the figure that overlaps it
    horizontally. Items Docling labelled `caption` win over plain text."""
    best = None
    for item in texts_on_page:
        text = (item["text"] or "").strip()
        if len(text) > CAPTION_MAX_CHARS or not parse_caption(text):
            continue
        box = item["box"]
        overlap = min(fig_box[2], box[2]) - max(fig_box[0], box[0])
        narrower = min(fig_box[2] - fig_box[0], box[2] - box[0])
        if narrower <= 0 or overlap / narrower < CAPTION_MIN_OVERLAP:
            continue
        gap = box[1] - fig_box[3] if box[1] >= fig_box[1] else fig_box[1] - box[3]
        if gap > CAPTION_MAX_GAP * page_height:
            continue
        rank = (item["label"] != "caption", max(gap, 0.0))
        if best is None or rank < best[0]:
            best = (rank, item)
    return best[1] if best else None


def build_book(doc: dict, manifest: dict) -> tuple[list[dict], list[str]]:
    """figures.json rows for one book, plus warnings. Pure: no files, testable."""
    book_id = manifest["book_id"]
    placements = {p["page"]: p for p in manifest.get("placements", [])}
    pages = {int(k): v for k, v in (doc.get("pages") or {}).items()}
    warnings: list[str] = []
    texts_by_ref: dict[str, dict] = {}
    texts_by_page: dict[int, list[dict]] = {}
    for item in doc.get("texts", []):
        for prov in item.get("prov", [])[:1]:
            page_no = int(prov["page_no"])
            height = float(pages.get(page_no, {}).get("size", {}).get("height", 0) or 0)
            entry = {
                "label": item.get("label", ""),
                "text": item.get("text", ""),
                "box": top_left_box(prov["bbox"], height),
                "page": page_no,
            }
            texts_by_ref[item.get("self_ref", "")] = entry
            texts_by_page.setdefault(page_no, []).append(entry)

    skipped_pages: set[int] = set()
    candidates: list[dict] = []
    for collection, kind in (("pictures", "picture"), ("tables", "table")):
        for item in doc.get(collection, []):
            for prov in item.get("prov", [])[:1]:
                page_no = int(prov["page_no"])
                size = pages.get(page_no, {}).get("size", {})
                width, height = float(size.get("width", 0)), float(size.get("height", 0))
                placement = placements.get(page_no)
                if placement is None or not width or not height:
                    skipped_pages.add(page_no)
                    continue
                if (
                    abs(width / placement["page_width_pt"] - 1) > 0.01
                    or abs(height / placement["page_height_pt"] - 1) > 0.01
                ):
                    if page_no not in skipped_pages:
                        warnings.append(
                            f"p{page_no}: Docling page {width:.0f}x{height:.0f} pt vs "
                            f"rendered {placement['page_width_pt']:.0f}x"
                            f"{placement['page_height_pt']:.0f} pt; skipped"
                        )
                    skipped_pages.add(page_no)
                    continue
                box = top_left_box(prov["bbox"], height)
                caption = None
                for ref in item.get("captions", []):
                    linked = texts_by_ref.get(ref.get("$ref", ""))
                    if linked and linked["page"] == page_no:
                        caption = linked
                        break
                if caption is None:
                    caption = find_caption(box, texts_by_page.get(page_no, []), height)
                caption_text = (caption["text"] or "").strip() if caption else ""
                parsed = parse_caption(caption_text)
                if caption:
                    box = union(box, caption["box"])
                candidates.append(
                    {
                        "page": page_no,
                        "kind": parsed[0] if parsed else kind,
                        "box": to_canvas_fraction(box, placement),
                        "caption": caption_text[:200],
                        "figure_number": parsed[1] if parsed else "",
                    }
                )

    kept = []
    for fig in candidates:
        x0, y0, x1, y1 = fig["box"]
        w, h = x1 - x0, y1 - y0
        if w < MIN_SIDE or h < MIN_SIDE or max(w / h, h / w) > MAX_ASPECT:
            continue
        if w * h > MAX_AREA:
            continue
        kept.append(fig)

    total_pages = max(len(placements), 1)
    threshold = max(3, REPEAT_FRACTION * total_pages)
    repeated: set[int] = set()
    for i, fig in enumerate(kept):
        if i in repeated:
            continue
        twins = [j for j, other in enumerate(kept) if iou(fig["box"], other["box"]) > REPEAT_IOU]
        if len({kept[j]["page"] for j in twins}) >= threshold:
            repeated.update(twins)
    if repeated:
        warnings.append(f"{len(repeated)} repeated box(es) dropped as decoration")
    kept = [fig for i, fig in enumerate(kept) if i not in repeated]

    rows = []
    for page_no in sorted({f["page"] for f in kept}):
        on_page = sorted(
            (f for f in kept if f["page"] == page_no), key=lambda f: (f["box"][1], f["box"][0])
        )
        for k, fig in enumerate(on_page, 1):
            rows.append(
                {
                    "id": f"{book_id}:p{page_no}:f{k}",
                    "page": page_no,
                    "kind": fig["kind"],
                    "box": [round(v, 4) for v in fig["box"]],
                    "caption": fig["caption"],
                    "figure_number": fig["figure_number"],
                }
            )
    if skipped_pages:
        warnings.append(f"{len(skipped_pages)} page(s) skipped: {sorted(skipped_pages)[:10]}")
    return rows, warnings


def review_html(book_id: str, rows: list[dict]) -> str:
    """Thumbnails with the boxes drawn on, so a person can check a book in minutes."""
    by_page: dict[int, list[dict]] = {}
    for row in rows:
        by_page.setdefault(row["page"], []).append(row)
    cards = []
    for page_no, figs in sorted(by_page.items()):
        boxes = "".join(
            '<div class="box" style="left:{:.2f}%;top:{:.2f}%;width:{:.2f}%;height:{:.2f}%">'
            "<span>{}</span></div>".format(
                f["box"][0] * 100,
                f["box"][1] * 100,
                (f["box"][2] - f["box"][0]) * 100,
                (f["box"][3] - f["box"][1]) * 100,
                html.escape(f["figure_number"] or f["kind"]),
            )
            for f in figs
        )
        captions = "".join(
            f"<li><b>{html.escape(f['figure_number'] or '-')}</b> "
            f"{html.escape(f['caption'] or '(no caption)')}</li>"
            for f in figs
        )
        cards.append(
            f'<figure><div class="page"><img loading="lazy" src="pages/p{page_no:03}.jpeg" '
            f'alt="page {page_no}">{boxes}</div><figcaption>p{page_no}<ul>{captions}</ul>'
            "</figcaption></figure>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(book_id)} figures</title><style>"
        "body{font:14px system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}"
        "figure{margin:0;background:#fff;border:1px solid #ddd;padding:8px}"
        ".page{position:relative}.page img{width:100%;display:block}"
        ".box{position:absolute;border:2px solid #e4572e;background:rgba(228,87,46,.08)}"
        ".box span{position:absolute;top:-1.4em;left:0;background:#e4572e;color:#fff;"
        "font-size:11px;padding:0 4px}"
        "figcaption ul{margin:4px 0 0;padding-left:18px}</style></head><body>"
        f"<h1>{html.escape(book_id)}</h1><p>{len(rows)} figure(s) on {len(by_page)} page(s). "
        "Check that every box holds one whole figure with its caption.</p>"
        f"<main>{''.join(cards)}</main></body></html>\n"
    )


def cmd_build(args) -> int:
    out_dir = Path(args.out)
    book_dirs = sorted(d for d in out_dir.iterdir() if d.is_dir() and (d / "docling.json").exists())
    if args.books:
        book_dirs = [
            d for d in book_dirs if any(re.fullmatch(_glob(p), d.name, re.I) for p in args.books)
        ]
    if not book_dirs:
        print(f"no book folders with docling.json under {out_dir}")
        return 1
    problems = 0
    for book_dir in book_dirs:
        manifest_path = book_dir / "manifest.json"
        if not manifest_path.exists():
            print(f"  {book_dir.name}: manifest.json missing (run encode_books first); skipped")
            problems += 1
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        doc = json.loads((book_dir / "docling.json").read_text(encoding="utf-8"))
        rows, warnings = build_book(doc, manifest)
        eb.write_json_atomic(book_dir / "figures.json", rows)
        eb.write_text_atomic(book_dir / "figures-review.html", review_html(book_dir.name, rows))
        numbered = sum(1 for r in rows if r["figure_number"])
        print(f"  {book_dir.name:<32} {len(rows):>4} figures ({numbered} with a figure number)")
        for warning in warnings:
            print(f"      note: {warning}")
    return 1 if problems else 0


def _glob(pattern: str) -> str:
    return re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("detect", help="GPU machine: run Docling's layout model on every book")
    p.add_argument("--input", required=True)
    p.add_argument("--out", default="out")
    p.add_argument("--books", nargs="+")
    p.add_argument("--force", action="store_true")
    p.add_argument("--allow-cpu", action="store_true")
    p = sub.add_parser("build", help="owner: docling.json -> figures.json + review page")
    p.add_argument("--out", default="out")
    p.add_argument("--books", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "detect":
        eb.start_log(Path(args.out) / "logs", "detect")
    try:
        return cmd_detect(args) if args.command == "detect" else cmd_build(args)
    except eb.ToolError as exc:
        print(f"\nERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
