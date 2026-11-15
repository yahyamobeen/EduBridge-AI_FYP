# Book indexing: ColQwen2 page embeddings + figure boxes

This folder turns the Punjab and Sindh textbook PDFs (Classes 9-12, 72 books) into the files
the EduBridge tutor searches. For each book it writes:

- `<book>.colqwen2.pt`: the ColQwen2 page index. It loads unchanged in `ml/serving/app.py`
  and `backend/app/retrieval/physics9/local.py`.
- `pages/`: the exact page images that were encoded, all 1049 x 1387.
- `manifest.json`: what was made, from which PDF, with which model and library versions.
- `docling.json`: Docling's raw layout output. `figures.py build` turns it into figure boxes.

It runs on a machine with an **NVIDIA GPU**, at about 2 s per page. On a CPU it takes about
10 minutes per page, which is only good enough for testing.

> **Running it?** Read **[GUIDE.md](GUIDE.md)**. It covers the naming convention with all 72
> file names, every step with the output you should see, what the finished `out` folder looks
> like, and troubleshooting.

## The naming convention, in one line

One PDF per book, all in one folder, named `<Board>_<Class>_<Subject>.pdf`:
- Board: `Punjab` or `Sindh`.
- Class: 9-12.
- Subject: `English`, `Urdu`, `Islamiat` (9 and 11), `PakStudies` (10 and 12), `Maths`,
  `TarjumaTulQuran`, `Physics`, `Chemistry`, `Biology` or `ComputerScience`.

For example `Punjab_9_Physics.pdf` or `Sindh_10_Maths.pdf`. Common alternative spellings are
accepted (see GUIDE.md section 2).

## The commands, in order

`py` means `.venv\Scripts\python.exe` on Windows, `.venv/bin/python` on Linux.

| # | Command | Must end with |
|---|---|---|
| 1 | `setup.bat` (Linux: `bash setup.sh`), once | `CUDA available: True` |
| 2 | `py encode_books.py calibrate` | `CALIBRATE: PASS` |
| 3 | `py encode_books.py preflight --input D:\books`, then send `preflight-report.txt` to the owner | `PREFLIGHT: OK` |
| 4 | `py encode_books.py run --input D:\books --out out --books Punjab_9_Physics` | `RUN: 1 ok, 0 failed` |
| 5 | `py encode_books.py run --input D:\books --out out` (resumable) | `RUN: 72 ok, 0 failed` |
| 6 | `py figures.py detect --input D:\books --out out` (resumable) | `DETECT: 72 ok, 0 failed` |
| 7 | `py encode_books.py verify --out out --input D:\books` | `VERIFY: PASS` |
| 8 | Upload `out` (with `out\logs`), `preflight-report.txt` and `logs` | - |

**At the end:** 72 book folders, about 7.5-8 GB and roughly 18,300 files for about 18,000
pages. GUIDE.md has the full layout.

---

## For the owner

### Before handing it over

```
.venv\Scripts\python.exe encode_books.py make-reference --index <path to the served pages.colqwen2.pt>
.venv\Scripts\python.exe selftest.py
```

- **`make-reference`** builds `reference/` from the served Physics 9 index and the scans in
  `backend/app/retrieval/physics9/pages/`:
  - the index in bfloat16 (exact);
  - three reference page images;
  - `physics9-pages.sha256`.
- **Only the hash list is committed.** The rest goes into the hand-over zip.
- **Zip this folder without `.venv`, `logs` or `__pycache__`.**

### On receipt

```
.venv\Scripts\python.exe encode_books.py verify --out received --input <the same PDFs>
.venv\Scripts\python.exe encode_books.py compare received\Punjab_9_Physics\Punjab_9_Physics.colqwen2.pt <served pages.colqwen2.pt>
.venv\Scripts\python.exe figures.py build --out received
```

- **If any `.pt` arrives as `.pt.zip`, rename it. Never extract it.** A PyTorch file is a
  zip inside, which is why some transfers add the extension.
- **`compare`:** expect a mean cosine of about 0.98 against the served Physics index. The
  served file was made with older, unrecorded package versions.
  - Whether the new file *replaces* it is decided by the bench evalset ranking check, not by
    cosine.
- **`figures.py build`:** writes `figures.json` and `figures-review.html` into each book
  folder. Boxes without a `figure_number` are lower confidence. Docling also boxes coloured
  sidebars such as "Point to Ponder!".

---

## What the files contain

The `.pt` is a dict of plain values only, so it loads with `torch.load(weights_only=True)`.

**Read by the service:**
- `checkpoint`;
- `pages`: 1..N;
- `embeddings`: N bfloat16 tensors of shape 755 x 128;
- `complete`;
- `dim`.

**Provenance:**
- `book_id`, `board`, `class_level` and `subject`;
- `source_sha256`;
- the pinned `adapter_revision` and `base_revision`;
- library versions, the GPU, and timing.

**bfloat16 loses nothing.** The model computes in bfloat16, and every reader casts back to
float32.

**Every page is exactly 1049 x 1387:**
- **Copied:** a scan already that size is copied byte for byte when nothing is drawn over it
  (an invisible OCR text layer is fine) and it is placed upright.
- **Stretched:** a page within 1% of that shape is scaled to it.
- **Letterboxed:** anything else is fitted inside it with white margins.

One size means 755 vectors on every page of every book. The service needs that, and it keeps
MaxSim from favouring bigger pages. Each page's placement is recorded in `manifest.json`, so
figure boxes map onto the image.

`figures.json` rows are `{id, page, kind, box, caption, figure_number}`. `box` is
`[x0, y0, x1, y1]` in fractions of the page image, top-left origin: the same format as the
tutor's `@@FIGURE` line and `FigureBox` in `backend/app/tutor/figures.py`.

## Checks

```
ruff check . && ruff format --check .
.venv\Scripts\python.exe selftest.py
```

The self-test needs no model and no GPU. It covers:
- naming;
- the three rendering paths, including overlays and upside-down scans;
- every refusal in the store check;
- resume;
- the Physics 9 gate;
- `verify`;
- the figure-box arithmetic.
