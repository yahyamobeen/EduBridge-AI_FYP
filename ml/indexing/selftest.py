"""Self-test for the book-indexing tool: no model, no GPU, no dataset.

Exercises what is easy to get wrong and expensive to discover on someone else's GPU:
book naming and discovery, the three rendering paths and their recorded placement, the
store's round trip through torch.load(weights_only=True), every refusal in check_store,
the skip-finished fingerprint, the Physics 9 gate's edition decision, verify, and the
figure-box arithmetic. Uses real torch, PyMuPDF and Pillow on synthetic PDFs.

It does NOT run ColQwen2 or Docling. `encode_books.py calibrate` and the laptop smoke run
cover the model; `figures.py detect` on Physics 9 covers Docling.

    python selftest.py
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pymupdf
import torch
from PIL import Image

import encode_books as eb
import figures as fg

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


def raises(fn, exc_type=Exception) -> bool:
    try:
        fn()
    except exc_type:
        return True
    return False


def jpeg_bytes(size, color=(200, 120, 60), quality=90) -> bytes:
    img = Image.new("RGB", size, color)
    img.paste((10, 10, 10), (0, 0, size[0] // 3, size[1] // 4))  # asymmetric: flips show
    for x in range(0, size[0], 40):  # some structure, so JPEG has real content
        for y in range(0, size[1], 40):
            img.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def fake_embeddings(n: int, seed: int = 0) -> list[torch.Tensor]:
    gen = torch.Generator().manual_seed(seed)
    out = []
    for _ in range(n):
        t = torch.randn(eb.VECTORS_PER_PAGE, eb.DIM, generator=gen)
        out.append(torch.nn.functional.normalize(t, dim=-1).to(torch.bfloat16))
    return out


print("== naming")
name = eb.parse_book_name("Punjab_9_Physics")
check("Punjab_9_Physics parses", name.book_id == "Punjab_9_Physics")
check("Sindh_10_Maths parses", eb.parse_book_name("Sindh_10_Maths").book_id == "Sindh_10_Maths")
check(
    "Mathematics is an alias of Maths",
    eb.parse_book_name("sindh_10_mathematics").book_id == "Sindh_10_Maths",
)
check(
    "Computer_Science (two tokens) is ComputerScience",
    eb.parse_book_name("Punjab_11_Computer_Science").book_id == "Punjab_11_ComputerScience",
)
check(
    "Pakistan_Studies is PakStudies",
    eb.parse_book_name("Punjab_12_Pakistan_Studies").subject == "PakStudies",
)
check(
    "Tarjuma_tul_Quran is TarjumaTulQuran",
    eb.parse_book_name("Sindh_9_Tarjuma_tul_Quran").subject == "TarjumaTulQuran",
)
check("Islamiyat is Islamiat", eb.parse_book_name("Sindh_11_Islamiyat").subject == "Islamiat")
for bad in ("Punjab_13_Physics", "Lahore_9_Physics", "Punjab_9", "Punjab_9_Painting", "Foo"):
    check(f"'{bad}' is refused", raises(lambda b=bad: eb.parse_book_name(b), eb.ToolError))
check("72 expected books", len(eb.EXPECTED_BOOKS) == 72, str(len(eb.EXPECTED_BOOKS)))
check(
    "36 per board",
    sum(b.startswith("Punjab_") for b in eb.EXPECTED_BOOKS) == 36
    and sum(b.startswith("Sindh_") for b in eb.EXPECTED_BOOKS) == 36,
)
check(
    "Islamiat only in 9 and 11, PakStudies only in 10 and 12",
    "Punjab_9_Islamiat" in eb.EXPECTED_BOOKS
    and "Punjab_10_Islamiat" not in eb.EXPECTED_BOOKS
    and "Sindh_12_PakStudies" in eb.EXPECTED_BOOKS
    and "Sindh_11_PakStudies" not in eb.EXPECTED_BOOKS,
)

work = Path(tempfile.mkdtemp(prefix="indexing-selftest-"))
try:
    print("== discovery")
    data = work / "data"
    data.mkdir()

    def tiny_pdf(path: Path, text: str) -> None:
        doc = pymupdf.open()
        doc.new_page(width=300, height=400).insert_text((40, 60), text)
        doc.save(path)
        doc.close()

    tiny_pdf(data / "Punjab_9_Physics.pdf", "physics")
    tiny_pdf(data / "Sindh_10_Maths.pdf", "maths")
    found = eb.discover(data)
    check(
        "two good PDFs found, no errors",
        len(found.books) == 2 and not found.errors,
        str(found.errors),
    )
    check(
        "Physics 9 is ordered first",
        eb.order_books(found.books)[0].book_id == "Punjab_9_Physics",
    )
    check(
        "--books glob selects case-insensitively",
        [b.book_id for b in eb.select_books(found.books, ["sindh_*"])] == ["Sindh_10_Maths"],
    )
    shutil.copyfile(data / "Sindh_10_Maths.pdf", data / "Sindh_11_Maths.pdf")
    found = eb.discover(data)
    check(
        "the same file under two book_ids is an error",
        any("identical sha256" in e for e in found.errors),
    )
    (data / "Sindh_11_Maths.pdf").unlink()
    tiny_pdf(data / "sindh_10_mathematics.pdf", "maths again")
    found = eb.discover(data)
    check(
        "two files mapping to one book_id is an error",
        any("two files map" in e for e in found.errors),
    )
    (data / "sindh_10_mathematics.pdf").unlink()
    (data / "Punjab_9_Biology").mkdir()
    found = eb.discover(data)
    check("a folder is an error", any("is a folder" in e for e in found.errors))
    (data / "Punjab_9_Biology").rmdir()

    print("== rendering")
    w_pt, h_pt = eb.CANVAS[0] * 0.48, eb.CANVAS[1] * 0.48  # exact canvas aspect
    pdf = work / "render.pdf"
    doc = pymupdf.open()
    exact = jpeg_bytes(eb.CANVAS)
    page = doc.new_page(width=w_pt, height=h_pt)  # 1: one exact-size JPEG -> copied
    page.insert_image(page.rect, stream=exact)
    page = doc.new_page(width=w_pt, height=h_pt)  # 2: same JPEG plus visible text -> stretched
    page.insert_image(page.rect, stream=exact)
    page.insert_text((50, 80), "VISIBLE LABEL", fontsize=30, color=(0, 0, 1))
    page = doc.new_page(width=w_pt, height=h_pt)  # 3: a 2x image -> stretched
    page.insert_image(page.rect, stream=jpeg_bytes((eb.CANVAS[0] * 2, eb.CANVAS[1] * 2)))
    page = doc.new_page(width=595, height=842)  # 4: A4 -> letterboxed, white side bars
    page.draw_rect(page.rect, color=(0, 0, 0), fill=(0.2, 0.2, 0.2))
    page = doc.new_page(width=842, height=595)  # 5: landscape A4 -> letterboxed, top/bottom
    page.draw_rect(page.rect, color=(0, 0, 0), fill=(0.2, 0.2, 0.2))
    page = doc.new_page(width=w_pt, height=h_pt)  # 6: exact JPEG + a vector line -> stretched
    page.insert_image(page.rect, stream=exact)
    page.draw_line((40, 40), (300, 300), color=(1, 0, 0), width=4)
    page = doc.new_page(width=w_pt, height=h_pt)  # 7: exact JPEG upside down -> stretched
    page.insert_image(page.rect, stream=jpeg_bytes(eb.CANVAS, color=(30, 160, 90)), rotate=180)
    page = doc.new_page(width=w_pt, height=h_pt)  # 8: scan 0.28 pt short of an edge -> copied
    page.insert_image(pymupdf.Rect(0, 0.284, w_pt - 0.283, h_pt), stream=exact)
    page.insert_text((50, 80), "invisible OCR layer", render_mode=3)
    doc.save(pdf)
    doc.close()

    pages_dir = work / "pages"
    placements = eb.render_book(pdf, pages_dir, progress=False)
    paths = [p.path for p in placements]
    check(
        "paths: copied / visible text, 2x image, vector line, upside down -> stretched / "
        "A4, landscape -> letterboxed / short edge + invisible OCR text -> copied",
        paths
        == [
            "copied",
            "stretched",
            "stretched",
            "letterboxed",
            "letterboxed",
            "stretched",
            "stretched",
            "copied",
        ],
        str(paths),
    )
    check(
        "copied page is the embedded JPEG byte for byte",
        (pages_dir / "p001.jpeg").read_bytes() == exact,
    )
    sizes = set()
    for p in sorted(pages_dir.glob("p*.jpeg")):
        with Image.open(p) as img:
            sizes.add((img.size, img.mode))
    check("every page is exactly 1049x1387 RGB", sizes == {(eb.CANVAS, "RGB")}, str(sizes))
    a4 = placements[3]
    check("A4 is centred with side bars", a4.offset_x > 20 and a4.offset_y == 0, str(a4.as_dict()))
    land = placements[4]
    check("landscape is centred with top/bottom bars", land.offset_y > 300 and land.offset_x == 0)
    with Image.open(pages_dir / "p004.jpeg") as img:
        corner, centre = img.getpixel((3, 700)), img.getpixel((524, 700))
    check("letterbox bars are white, content is not", min(corner) > 240 and max(centre) < 100)
    check("each placement carries the image sha256", all(len(p.sha256) == 64 for p in placements))
    (pages_dir / "p009.jpeg").write_bytes(exact)
    eb.render_book(pdf, pages_dir, progress=False)
    check("a stale page beyond the book is removed", not (pages_dir / "p009.jpeg").exists())

    print("== store")
    book = eb.Book(name=eb.parse_book_name("Punjab_9_Physics"), pdf=pdf, sha256="ab" * 32, pages=3)
    store = eb.build_store(
        book, fake_embeddings(3), complete=True, extra={"versions": {"torch": "x"}}
    )
    good = work / "good.pt"
    eb.save_store(store, good, allow_incomplete=False)
    loaded = eb.load_store(good)
    check("a good store loads with weights_only=True", isinstance(loaded, dict))
    check("a good store passes check_store", eb.check_store(loaded, expect_pages=3) == [])
    check("embeddings are stored as bfloat16", loaded["embeddings"][0].dtype == torch.bfloat16)

    def broken(**change):
        s = dict(store)
        s.update(change)
        return eb.check_store(s)

    check("wrong checkpoint refused", broken(checkpoint="vidore/colpali-v1.3") != [])
    check("a missing page refused", broken(pages=[1, 2, 4]) != [])
    check("pages/embeddings length mismatch refused", broken(pages=[1, 2]) != [])
    short = fake_embeddings(3)
    short[1] = short[1][:754]
    check("a 754-row page refused", broken(embeddings=short) != [])
    nan = fake_embeddings(3)
    nan[2] = nan[2].float()
    nan[2][0, 0] = float("nan")
    check("NaN refused", broken(embeddings=nan) != [])
    unnormed = [t.float() * 2 for t in fake_embeddings(3)]
    check("unnormalised rows refused", broken(embeddings=unnormed) != [])
    check("complete=False refused", broken(complete=False) != [])
    check("bool pages refused", broken(pages=[True, 2, 3]) != [])
    tv = dict(store)
    tv["versions"] = {"torch": torch.__version__}  # TorchVersion, a str subclass
    check("a TorchVersion value is caught before saving", eb.plain_problems(tv) != [])
    check(
        "save_store refuses it rather than writing an unloadable file",
        raises(lambda: eb.save_store(tv, work / "tv.pt", allow_incomplete=False), eb.ToolError)
        and not (work / "tv.pt").exists(),
    )
    torch.save(tv, work / "tv_raw.pt")
    check(
        "and torch.load(weights_only=True) does refuse it",
        raises(lambda: eb.load_store(work / "tv_raw.pt")),
    )

    print("== fingerprint and resume")
    book_dir = work / "out" / "Punjab_9_Physics"
    book_dir.mkdir(parents=True)
    shutil.copyfile(good, book_dir / "Punjab_9_Physics.colqwen2.pt")
    manifest = {
        "fingerprint": eb.fingerprint("ab" * 32),
        "complete": True,
        "encoder_version": "0.0.1",
    }
    eb.write_json_atomic(book_dir / "manifest.json", manifest)
    check("done when the fingerprint matches", eb.is_done(book_dir, "Punjab_9_Physics", "ab" * 32))
    check(
        "an encoder-version change does NOT re-encode",
        manifest["encoder_version"] != eb.ENCODER_VERSION,
    )
    check("a new source PDF re-encodes", not eb.is_done(book_dir, "Punjab_9_Physics", "cd" * 32))
    stale = dict(manifest, fingerprint=dict(eb.fingerprint("ab" * 32), base_revision="old"))
    eb.write_json_atomic(book_dir / "manifest.json", stale)
    check(
        "a model-revision change re-encodes",
        not eb.is_done(book_dir, "Punjab_9_Physics", "ab" * 32),
    )

    print("== Physics 9 gate")
    ref = dict(zip(range(1, 11), fake_embeddings(10, seed=1), strict=True))
    hashes = [f"h{i}" for i in range(10)]
    same = eb.physics_gate(hashes, hashes, dict(ref), ref)
    check("same edition, same vectors: passes", same.applies and not same.failures)
    shifted = {p: ref[p % 10 + 1] for p in ref}  # every page holds its neighbour's vectors
    off = eb.physics_gate(hashes, hashes, shifted, ref)
    check("pages off by one: fails on every page", off.applies and len(off.failures) == 10)
    other = eb.physics_gate([f"x{i}" for i in range(10)], hashes, shifted, ref)
    check(
        "another edition: gate does not apply, no failures",
        not other.applies and not other.failures,
    )
    one_diff = eb.physics_gate(["zz", *hashes[1:]], hashes, shifted, ref)
    check("9/10 identical (< 95%): treated as another edition", not one_diff.applies)
    check(
        "a different page count: another edition",
        not eb.physics_gate(hashes[:9], hashes, {}, ref).applies,
    )

    print("== verify")
    vbook = work / "vout" / "Sindh_10_Maths"
    (vbook / "pages").mkdir(parents=True)
    vstore = eb.build_store(
        eb.Book(name=eb.parse_book_name("Sindh_10_Maths"), pdf=pdf, sha256="ef" * 32, pages=3),
        fake_embeddings(3),
        complete=True,
        extra={},
    )
    vpt = vbook / "Sindh_10_Maths.colqwen2.pt"
    eb.save_store(vstore, vpt, allow_incomplete=False)
    placements_json = []
    for i in range(1, 4):
        img = vbook / "pages" / f"p{i:03}.jpeg"
        img.write_bytes(jpeg_bytes(eb.CANVAS, color=(i * 40, 90, 90)))
        placements_json.append({"page": i, "sha256": eb.sha256_file(img)})
    eb.write_json_atomic(
        vbook / "manifest.json", {"pt_sha256": eb.sha256_file(vpt), "placements": placements_json}
    )
    check(
        "verify passes a complete book",
        eb.verify_book(vbook, 3) == [],
        str(eb.verify_book(vbook, 3)),
    )
    check("verify catches a PDF page-count mismatch", eb.verify_book(vbook, 4) != [])
    (vbook / "pages" / "p002.jpeg").write_bytes(jpeg_bytes(eb.CANVAS, color=(1, 2, 3)))
    check("verify catches a changed page image", eb.verify_book(vbook, 3) != [])
    shutil.copyfile(vpt, vbook.parent / "Sindh_10_Maths.colqwen2.pt.zip")
    rc = eb.cmd_verify(type("A", (), {"out": str(work / "vout"), "input": None})())
    check("verify fails on a .pt.zip in the output", rc == 1)

    print("== figures: captions")
    check(
        "'Fig. 7.8 Thermocouple' -> 7.8",
        fg.parse_caption("Fig. 7.8 Thermocouple") == ("picture", "7.8"),
    )
    check(
        "'Figure 7.6' -> 7.6",
        fg.parse_caption("Figure 7.6: mercury thermometer") == ("picture", "7.6"),
    )
    check(
        "'Fig. 7.3 (a)' -> 7.3(a)", fg.parse_caption("Fig. 7.3 (a) Plasma") == ("picture", "7.3(a)")
    )
    check(
        "'Fig. 7.3-b' -> 7.3(b)", fg.parse_caption("Fig. 7.3-b discharge") == ("picture", "7.3(b)")
    )
    check(
        "OCR comma 'Fig. 7,3(a) Plasma' -> 7.3(a)",
        fg.parse_caption("Fig. 7,3(a) Plasma") == ("picture", "7.3(a)"),
    )
    check(
        "'Fig. 7.3(b)(Gas discharge tube' -> 7.3(b)",
        fg.parse_caption("Fig. 7.3(b)(Gas discharge tube") == ("picture", "7.3(b)"),
    )
    check("'Table 3.2' -> table 3.2", fg.parse_caption("Table 3.2 Densities") == ("table", "3.2"))
    urdu = "\u0634\u06a9\u0644 \u06f7.\u06f8"  # shakl 7.8 in Urdu digits
    check("Urdu 'shakl' with Urdu digits -> 7.8", fg.parse_caption(urdu) == ("picture", "7.8"))
    check(
        "body text is not a caption", fg.parse_caption("Most of the properties of solids") is None
    )

    print("== figures: box arithmetic")
    page_h = 666.0
    check(
        "BOTTOMLEFT bbox flips to top-left",
        fg.top_left_box(
            {"l": 10, "t": 600, "r": 110, "b": 500, "coord_origin": "BOTTOMLEFT"}, page_h
        )
        == (10.0, 66.0, 110.0, 166.0),
    )
    check(
        "TOPLEFT bbox is unchanged",
        fg.top_left_box({"l": 10, "t": 66, "r": 110, "b": 166, "coord_origin": "TOPLEFT"}, page_h)
        == (10.0, 66.0, 110.0, 166.0),
    )
    stretch = {"scale_x": 1049 / 504, "scale_y": 1387 / 666, "offset_x": 0.0, "offset_y": 0.0}
    frac = fg.to_canvas_fraction((0, 0, 504, 666), stretch)
    check(
        "full page maps to 0..1 when stretched",
        all(abs(a - b) < 1e-6 for a, b in zip(frac, (0, 0, 1, 1), strict=True)),
    )
    scale = 1387 / 842
    letter = {
        "scale_x": scale,
        "scale_y": scale,
        "offset_x": (1049 - 595 * scale) / 2,
        "offset_y": 0.0,
    }
    frac = fg.to_canvas_fraction((0, 0, 595, 842), letter)
    check(
        "letterboxed full page sits inside the bars",
        frac[0] > 0.03 and frac[2] < 0.97 and frac[3] > 0.999,
    )

    def docling_doc(pictures, texts, pages=1, w=504.0, h=666.0):
        return {
            "pages": {
                str(i): {"size": {"width": w, "height": h}, "page_no": i}
                for i in range(1, pages + 1)
            },
            "pictures": pictures,
            "tables": [],
            "texts": texts,
        }

    def prov(page, left, top, right, bottom):
        return [
            {
                "page_no": page,
                "bbox": {"l": left, "t": top, "r": right, "b": bottom, "coord_origin": "TOPLEFT"},
            }
        ]

    def manifest_for(pages, w=504.0, h=666.0):
        return {
            "book_id": "Punjab_9_Physics",
            "placements": [
                {"page": i, "page_width_pt": w, "page_height_pt": h, **stretch}
                for i in range(1, pages + 1)
            ],
        }

    doc = docling_doc(
        [{"prov": prov(1, 100, 100, 400, 300), "captions": []}],
        [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Fig. 7.8 Thermocouple",
                "prov": prov(1, 120, 305, 380, 320),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Unrelated paragraph text here.",
                "prov": prov(1, 60, 400, 440, 420),
            },
        ],
    )
    rows, _ = fg.build_book(doc, manifest_for(1))
    check("one figure found", len(rows) == 1, str(rows))
    check("caption found by search below the figure", rows and rows[0]["figure_number"] == "7.8")
    check("box widened to include the caption", rows and rows[0]["box"][3] > 300 / 666 + 0.02)
    check("id format book:pN:fK", rows and rows[0]["id"] == "Punjab_9_Physics:p1:f1")

    doc["texts"].append(
        {
            "self_ref": "#/texts/2",
            "label": "caption",
            "text": "Fig. 7.9 Linked",
            "prov": prov(1, 120, 80, 380, 95),
        }
    )
    doc["pictures"][0]["captions"] = [{"$ref": "#/texts/2"}]
    rows, _ = fg.build_book(doc, manifest_for(1))
    check("a linked caption wins over a searched one", rows and rows[0]["figure_number"] == "7.9")

    long_para = "Figure 7.6 shows a mercury thermometer. " * 6
    doc2 = docling_doc(
        [{"prov": prov(1, 100, 100, 400, 300), "captions": []}],
        [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": long_para,
                "prov": prov(1, 100, 305, 400, 360),
            }
        ],
    )
    rows, _ = fg.build_book(doc2, manifest_for(1))
    check(
        "a long paragraph starting 'Figure 7.6 shows' is not a caption",
        rows and rows[0]["figure_number"] == "",
    )

    doc3 = docling_doc(
        [
            {"prov": prov(1, 100, 100, 105, 300), "captions": []},  # a sliver
            {"prov": prov(1, 0, 0, 504, 666), "captions": []},  # the whole scan
        ],
        [],
    )
    rows, _ = fg.build_book(doc3, manifest_for(1))
    check("slivers and whole-page boxes are dropped", rows == [], str(rows))

    logo = [{"prov": prov(p, 20, 20, 80, 80), "captions": []} for p in range(1, 11)]
    real = [{"prov": prov(3, 100, 200, 400, 450), "captions": []}]
    rows, warnings = fg.build_book(docling_doc(logo + real, [], pages=10), manifest_for(10))
    check(
        "a box repeated on every page is dropped as decoration",
        len(rows) == 1 and rows[0]["page"] == 3,
    )

    rows, warnings = fg.build_book(
        docling_doc([{"prov": prov(1, 100, 100, 400, 300), "captions": []}], [], w=595, h=842),
        manifest_for(1),
    )
    check("a page-size mismatch skips the page with a warning", rows == [] and warnings != [])

    html_text = fg.review_html(
        "Punjab_9_Physics",
        [
            {
                "page": 3,
                "kind": "picture",
                "box": [0.1, 0.2, 0.5, 0.6],
                "caption": "<b>x</b>",
                "figure_number": "1.1",
            }
        ],
    )
    check(
        "review page escapes captions and links the scan",
        "&lt;b&gt;" in html_text and "pages/p003.jpeg" in html_text,
    )
finally:
    shutil.rmtree(work, ignore_errors=True)

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)
