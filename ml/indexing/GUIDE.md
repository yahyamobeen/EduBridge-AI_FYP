# Step-by-step guide: encoding the Punjab and Sindh textbooks

This guide is for the person with the GPU. Follow it top to bottom. Every step says what to
type, what you should see, and what to do if you see something else.

**What you are producing:** for each of 72 textbooks, a folder holding:
- an embedding file (`.pt`) the EduBridge tutor searches;
- the page images;
- Docling's figure-layout data.

You send the whole `out` folder back to the owner at the end.

**Time:** roughly a day of the laptop running, which can be spread over several sessions.
Only steps 1-3 need you at the keyboard.

---

## Contents

1. [What you need](#1-what-you-need)
2. [The file naming convention](#2-the-file-naming-convention)
3. [Step 1: put the folder in place](#step-1-put-the-folder-in-place)
4. [Step 2: setup (once)](#step-2-setup-once)
5. [Step 3: calibrate](#step-3-calibrate)
6. [Step 4: preflight, and send the report](#step-4-preflight-and-send-the-report)
7. [Step 5: the first book (the end-to-end check)](#step-5-the-first-book-the-end-to-end-check)
8. [Step 6: all the books](#step-6-all-the-books)
9. [Step 7: figure detection](#step-7-figure-detection)
10. [Step 8: verify](#step-8-verify)
11. [Step 9: send everything back](#step-9-send-everything-back)
12. [What you should have at the end](#what-you-should-have-at-the-end)
13. [Troubleshooting](#troubleshooting)
14. [Questions](#questions)

---

## 1. What you need

| | |
|---|---|
| GPU | An NVIDIA card with at least 8 GB of VRAM. An RTX 5060 laptop is fine. |
| Driver | NVIDIA driver **R580 or newer** is best. Check with `nvidia-smi`: the version is in the top line. An older driver works too, and setup adapts. |
| Python | **3.12**, from python.org. Tick "Add python.exe to PATH" when installing. |
| Disk | **About 35 GB free**: 6 GB for the tool's environment, 9 GB for the model download, and about 8 GB of output for 72 books, plus headroom. |
| Internet | Needed for setup and the first model download (about 9 GB). After that, nothing is downloaded. |
| The PDFs | One PDF per book, named as in section 2, all in **one folder**. |

**Before a long run:**
- **Keep the laptop plugged in, with the lid open.** On battery the GPU slows right down.
  Closing the lid sleeps the machine.
- **Pause Windows Update** for a day (Settings > Windows Update > Pause), so it doesn't
  restart mid-run.
- **Don't click inside the black console window while it runs.** Windows pauses a program
  you click into ("QuickEdit"). If the output seems frozen, press `Esc`.
- The script stops Windows from going to sleep on its own while it runs.

---

## 2. The file naming convention

Every PDF must be named:

```
<Board>_<Class>_<Subject>.pdf
```

| Part | Allowed values |
|---|---|
| Board | `Punjab` or `Sindh` |
| Class | `9`, `10`, `11` or `12` |
| Subject | `English`, `Urdu`, `Islamiat`, `PakStudies`, `Maths`, `TarjumaTulQuran`, `Physics`, `Chemistry`, `Biology`, `ComputerScience` |

**Rules:**
- **One PDF per book.** If a book came as several PDFs (parts or chapters), join them into
  one PDF first, in page order. A folder in place of a PDF is refused.
- **All PDFs go directly in one folder**, not in subfolders.
- **Capital letters don't matter.** `punjab_9_physics.pdf` is fine.
- **Some other spellings are accepted** and converted automatically:

  | You may write | It becomes |
  |---|---|
  | `Mathematics`, `Math` | `Maths` |
  | `Pakistan_Studies`, `Pak_Studies`, `Pakistan Studies` | `PakStudies` |
  | `Computer_Science`, `Computer Science`, `CS`, `Computer` | `ComputerScience` |
  | `Tarjuma_tul_Quran`, `TarjumaQuran`, `Quran` | `TarjumaTulQuran` |
  | `Islamiyat`, `Islamic_Studies` | `Islamiat` |
  | `Bio`, `Chem`, `Phy`, `Eng` | `Biology`, `Chemistry`, `Physics`, `English` |

- **The same PDF must not appear under two names.** It is caught by its content, not its
  name.
- Anything that is not a PDF in the folder is ignored, and listed as a warning.

**Examples:**

| File name | Result |
|---|---|
| `Punjab_9_Physics.pdf` | OK, book `Punjab_9_Physics` |
| `Sindh_10_Mathematics.pdf` | OK, book `Sindh_10_Maths` |
| `Punjab_11_Computer_Science.pdf` | OK, book `Punjab_11_ComputerScience` |
| `Punjab_13_Physics.pdf` | Refused: no class 13 |
| `Lahore_9_Physics.pdf` | Refused: the board must be Punjab or Sindh |
| `Physics_9_Punjab.pdf` | Refused: wrong order |
| `Punjab_9_Painting.pdf` | Refused: unknown subject |
| `9th Physics Punjab.pdf` | Refused: not the convention |
| `Punjab_9_Physics\` (a folder) | Refused: one PDF per book |

### The 72 books

Islamiat is in classes 9 and 11 only, and Pakistan Studies in 10 and 12 only, so each class
has 9 books, each board has 36, and there are **72 in all**.

**Punjab** (36 books)

| Subject | Class 9 | Class 10 | Class 11 | Class 12 |
|---|---|---|---|---|
| English | `Punjab_9_English.pdf` | `Punjab_10_English.pdf` | `Punjab_11_English.pdf` | `Punjab_12_English.pdf` |
| Urdu | `Punjab_9_Urdu.pdf` | `Punjab_10_Urdu.pdf` | `Punjab_11_Urdu.pdf` | `Punjab_12_Urdu.pdf` |
| Islamiat | `Punjab_9_Islamiat.pdf` | - | `Punjab_11_Islamiat.pdf` | - |
| PakStudies | - | `Punjab_10_PakStudies.pdf` | - | `Punjab_12_PakStudies.pdf` |
| Maths | `Punjab_9_Maths.pdf` | `Punjab_10_Maths.pdf` | `Punjab_11_Maths.pdf` | `Punjab_12_Maths.pdf` |
| TarjumaTulQuran | `Punjab_9_TarjumaTulQuran.pdf` | `Punjab_10_TarjumaTulQuran.pdf` | `Punjab_11_TarjumaTulQuran.pdf` | `Punjab_12_TarjumaTulQuran.pdf` |
| Physics | `Punjab_9_Physics.pdf` | `Punjab_10_Physics.pdf` | `Punjab_11_Physics.pdf` | `Punjab_12_Physics.pdf` |
| Chemistry | `Punjab_9_Chemistry.pdf` | `Punjab_10_Chemistry.pdf` | `Punjab_11_Chemistry.pdf` | `Punjab_12_Chemistry.pdf` |
| Biology | `Punjab_9_Biology.pdf` | `Punjab_10_Biology.pdf` | `Punjab_11_Biology.pdf` | `Punjab_12_Biology.pdf` |
| ComputerScience | `Punjab_9_ComputerScience.pdf` | `Punjab_10_ComputerScience.pdf` | `Punjab_11_ComputerScience.pdf` | `Punjab_12_ComputerScience.pdf` |

**Sindh** (36 books)

| Subject | Class 9 | Class 10 | Class 11 | Class 12 |
|---|---|---|---|---|
| English | `Sindh_9_English.pdf` | `Sindh_10_English.pdf` | `Sindh_11_English.pdf` | `Sindh_12_English.pdf` |
| Urdu | `Sindh_9_Urdu.pdf` | `Sindh_10_Urdu.pdf` | `Sindh_11_Urdu.pdf` | `Sindh_12_Urdu.pdf` |
| Islamiat | `Sindh_9_Islamiat.pdf` | - | `Sindh_11_Islamiat.pdf` | - |
| PakStudies | - | `Sindh_10_PakStudies.pdf` | - | `Sindh_12_PakStudies.pdf` |
| Maths | `Sindh_9_Maths.pdf` | `Sindh_10_Maths.pdf` | `Sindh_11_Maths.pdf` | `Sindh_12_Maths.pdf` |
| TarjumaTulQuran | `Sindh_9_TarjumaTulQuran.pdf` | `Sindh_10_TarjumaTulQuran.pdf` | `Sindh_11_TarjumaTulQuran.pdf` | `Sindh_12_TarjumaTulQuran.pdf` |
| Physics | `Sindh_9_Physics.pdf` | `Sindh_10_Physics.pdf` | `Sindh_11_Physics.pdf` | `Sindh_12_Physics.pdf` |
| Chemistry | `Sindh_9_Chemistry.pdf` | `Sindh_10_Chemistry.pdf` | `Sindh_11_Chemistry.pdf` | `Sindh_12_Chemistry.pdf` |
| Biology | `Sindh_9_Biology.pdf` | `Sindh_10_Biology.pdf` | `Sindh_11_Biology.pdf` | `Sindh_12_Biology.pdf` |
| ComputerScience | `Sindh_9_ComputerScience.pdf` | `Sindh_10_ComputerScience.pdf` | `Sindh_11_ComputerScience.pdf` | `Sindh_12_ComputerScience.pdf` |

It doesn't matter if some are missing: `preflight` (step 4) lists exactly which ones are.
Books outside this list are still encoded; they are just reported.

---

## Step 1: put the folder in place

1. **Unzip `edubridge-indexing.zip` somewhere OneDrive does not sync**, for example
   `C:\edubridge-indexing`. Avoid Desktop and Documents, which OneDrive often syncs. It locks
   files mid-write.
2. **Put the PDFs in their own folder**, for example `D:\books`.
3. **Open a terminal in the tool folder.** In File Explorer, open `C:\edubridge-indexing`,
   click the address bar, type `cmd` and press Enter.

Every command below is typed in that terminal. In this guide, `py` is short for:
- **Windows:** `.venv\Scripts\python.exe`
- **Linux:** `.venv/bin/python`

Type the long form. For example, `py encode_books.py calibrate` means
`.venv\Scripts\python.exe encode_books.py calibrate`.

If you want the Hugging Face model cache on another drive, run `set HF_HOME=D:\hf` (Linux:
`export HF_HOME=/data/hf`) in the same terminal before every command.

---

## Step 2: setup (once)

**Windows:**
```
setup.bat
```
**Linux:**
```
bash setup.sh
```

**What it does:**
1. Reads your driver version.
2. Installs the matching GPU build of PyTorch: `2.13.0+cu130` for driver R580+, otherwise
   `2.11.0+cu128`.
3. Installs the exact package versions that were tested.

It takes 5 to 15 minutes, mostly downloading.

**You should see at the end:**
```
== checking
torch 2.13.0+cu130 | CUDA available: True

Setup done. Next:  .venv\Scripts\python.exe encode_books.py calibrate
```

**`CUDA available: True` is the line that matters.** If it says `False`, see
[Troubleshooting](#troubleshooting).

> **Never run a plain `pip install torch`.** That installs a CPU-only build, about 100 times
> slower. Always use `setup.bat`.

---

## Step 3: calibrate

```
py encode_books.py calibrate
```

**What it does:**
- checks your GPU really works with this PyTorch build;
- plans the batch size;
- warms up Docling;
- downloads the model the first time (about 9 GB);
- encodes three reference pages of the Physics book and compares them with the index the
  tutor already uses.

**Time:** 2-5 minutes, plus the first download.

**You should see something like this.** Your numbers will differ slightly:
```
== environment
    python           3.12.x
    torch            2.13.0+cu130
    ...
    GPU              NVIDIA GeForce RTX 5060 Laptop GPU, 7.6 GB, sm_120
    batch plan       2
    HF cache         C:\Users\you\.cache\huggingface\hub (120.0 GB free)
== figure detector (Docling) warm-up
    Docling ready (40s; models downloaded if they were missing)
== model
    model ready on cuda:0 in 60s (394 LoRA tensors)
== one page at a time, against the reference index
    p010  mean 0.98..  (p01 0.5.., min 0.2..)  ok
    p150  mean 0.98..  (p01 0.4.., min 0.0..)  ok
    p187  mean 0.98..  (p01 0.7.., min 0.0..)  ok
    speed 1.9 s/page (first page excluded as warm-up)
== the same pages as one batch, against the single-page results above
    p010  batch vs single 0.9999.  ok
    p150  batch vs single 0.9999.  ok
    p187  batch vs single 0.9999.  ok

CALIBRATE: PASS
```

**What matters:**
- **The last line must be `CALIBRATE: PASS`.**
- Each `mean` must be **0.95 or more**. About 0.98 is normal. The `p01` and `min` numbers
  are only informational; low values there are normal.
- Note the `speed` line. Multiply it by the page count from step 4 for a time estimate.

**If it says `FAIL`:** stop. Send the newest file in the `logs` folder of the tool to the
owner. Do not start step 5.

---

## Step 4: preflight, and send the report

```
py encode_books.py preflight --input D:\books
```

**What it does** (no GPU needed; a few minutes):
- checks every file name against section 2;
- opens every PDF;
- renders three pages of each, so a broken PDF shows up now and not at hour six;
- counts the pages;
- checks the free disk space.

It writes **`preflight-report.txt`** in the tool folder. Its top part looks like this:
```
books found: 72 of 72 expected
pages: 18034
estimated GPU time: 9.0 h - 12.0 h (estimate; calibrate measures it)
estimated output: 6.5 GB; free on out: 210.4 GB

COVERAGE (x = present, . = missing, - = not expected)
  Punjab
    subject              9  10  11  12
    English              x   x   x   x
    Urdu                 x   x   x   x
    Islamiat             x   -   x   -
    PakStudies           -   x   -   x
    Maths                x   x   x   x
    ...
ERRORS (0) - must be fixed before 'run'
  none
MISSING (0)
  none
```
It then lists warnings and every book's page count and page size.

**What matters:**
- **The last line on screen must be `PREFLIGHT: OK`.** If it is `FAIL`, the `ERRORS` section
  says exactly which file is wrong and why. Rename or fix those files and run preflight
  again.
- `MISSING` books are fine if they really aren't available. Just make sure it's not a
  spelling problem.

**Now send `preflight-report.txt` to the owner and wait for the go-ahead.** Fixing a name now
takes a minute; finding it after ten hours costs a re-run.

---

## Step 5: the first book (the end-to-end check)

```
py encode_books.py run --input D:\books --out out --books Punjab_9_Physics
```

**Why this book first:** the tutor already has an index for it, so the script compares your
result with it page by page. If pages came out in the wrong order or batches were mixed up,
the run stops here instead of after ten hours.

**Time:** about 8 minutes.

**You should see something like this:**
```
[1/1] Punjab_9_Physics  (Punjab_9_Physics.pdf)
  rendering 200 pages
    rendered 50/200
    ...
    rendered 200/200
    {'copied': 199, 'stretched': 1}
  physics gate: same edition as the served index; 200 identical page images
    model ready on cuda:0 in 60s (394 LoRA tensors)
  encoding 200 pages at batch 2
    2/200  2.10 s/page  book eta 7.0 min
    ...
    200/200  1.95 s/page  book eta 0.0 min
  physics gate: 200 pages compared, mean cosine 0.98.., lowest 0.9...
  done: 200 pages in 7.1 min (2.13 s/page incl. render)

RUN: 1 ok, 0 failed
```

**What matters:**

| You see | Meaning |
|---|---|
| `{'copied': 199, 'stretched': 1}` and `200 identical page images` | Same book as the tutor's. Perfect. |
| `{'copied': 200}` and `199 identical page images`, differing page `[187]` | The other print of the same book. Also fine. |
| `another edition` | A different edition. The check is skipped and the run continues. **Tell the owner**: page numbers may differ from the tutor's current book. |
| `physics gate: ... mean cosine 0.98..` | Good: anything 0.95 or more passes. |
| `Physics 9 gate FAILED` and `STOPPED` | **Stop.** Send the `out\logs` folder to the owner. |

---

## Step 6: all the books

```
py encode_books.py run --input D:\books --out out
```

It works through every book, one at a time: `Punjab_9_Physics` first (already done, so it's
skipped in a second), then the rest in alphabetical order.

**You will see for each book:**
```
[14/72] Punjab_11_Chemistry  (Punjab_11_Chemistry.pdf)
  rendering 312 pages
  ...
  encoding 312 pages at batch 2
    ...
  done: 312 pages in 10.6 min (2.04 s/page incl. render)
  run time so far 2.31 h
```

And at the very end:
```
== summary
  Punjab_10_Biology                done: 287 pages in 9.7 min (2.03 s/page incl. render)
  ...
  Punjab_9_Physics                 skipped (already done, fingerprint matches)
  ...
RUN: 72 ok, 0 failed
```

- **Time:** about 2 seconds per page, so about 9-12 hours for all 72 books.
- **You can stop at any time** with `Ctrl+C`; a crash, power cut or sleep is also safe. Run
  the **same command** again. Finished books are skipped, and only the book that was in
  progress is redone. Spreading the work over several evenings is fine.
- **If one book fails,** the others carry on, and the summary lists it as `FAILED` with the
  reason. Run the same command again later; only the failed book is retried. If it fails
  twice, send the log.
- `out of memory; retrying at batch 1` is fine: it carries on, slightly slower.

---

## Step 7: figure detection

```
py figures.py detect --input D:\books --out out
```

Runs Docling's layout model on every book to find where the figures and tables are on each
page. It writes `docling.json` into each book's folder.

**You should see for each book:**
```
[1/72] Punjab_9_Physics
  done: 200 pages, 310 pictures, 25 tables in 2.1 min (0.63 s/page)
```

- It ran at 2.6 seconds per page on a laptop CPU. On the GPU it should be faster.
- The final line is `DETECT: 72 ok, 0 failed`.
- It can also be stopped and resumed: finished books are skipped.

---

## Step 8: verify

```
py encode_books.py verify --out out --input D:\books
```

It checks every book the way the tutor will load it:
- the file loads safely;
- every page is present and the right shape;
- the page count matches the PDF;
- every page image matches what was recorded.

It also writes `out\SHA256SUMS.txt`, a fingerprint of every file, so the owner can tell if
anything got damaged in the upload.

**You should see:**
```
PASS Punjab_10_Biology
PASS Punjab_10_Chemistry
...
PASS Sindh_9_Urdu

72 book folder(s), 0 problem(s)

VERIFY: PASS  (SHA256SUMS.txt written, 18322 files)
```

**What matters:** it must end with **`VERIFY: PASS`**. If any line says `FAIL`, send
`out\verify-report.txt` to the owner.

---

## Step 9: send everything back

Upload these to the shared drive the owner gives you:

1. **The whole `out` folder**, including `out\logs`.
2. From the tool folder: **`preflight-report.txt`** and the **`logs`** folder (the calibrate
   log).

**How:**
- **Upload the folder file by file.** Google Drive, OneDrive web or similar can all upload a
  folder.
- **Don't make one giant zip.** If an upload of one file breaks, only that file needs
  redoing.
- **Don't rename, move or open anything inside `out`.** The checks rely on the exact names
  and contents.

---

## What you should have at the end

```
out\
  Punjab_9_Physics\
    Punjab_9_Physics.colqwen2.pt   the embeddings: about 0.19 MB a page (39 MB for 200 pages)
    manifest.json                  what was made and how: about 65 KB
    docling.json                   figure layout from step 7: about 4 MB for 200 pages
    docling.meta.json              under 1 KB
    pages\
      p001.jpeg ... p200.jpeg      every page, 1049 x 1387 pixels: about 0.2 MB each
  Punjab_9_Biology\                the same files
  ...                              one folder per book: 72 in all
  logs\
    run-YYYYMMDD-HHMMSS.log        one per run (several if you stopped and resumed)
    detect-YYYYMMDD-HHMMSS.log
  verify-report.txt
  SHA256SUMS.txt
```

**Totals** for about 18,000 pages:

| | Size |
|---|---|
| Embeddings | about 3.5 GB |
| Page images | about 3.7 GB |
| Docling layout | about 0.4 GB |
| **All together** | **about 7.5-8 GB, roughly 18,300 files** |

**It is finished when all of these hold:**
- [ ] `RUN: 72 ok, 0 failed`, or as many as there are books, from step 6;
- [ ] `DETECT: 72 ok, 0 failed` from step 7;
- [ ] `VERIFY: PASS` from step 8;
- [ ] the `out` folder, `preflight-report.txt` and both `logs` folders are uploaded.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| `No nvidia-smi found` (setup) | Install the latest NVIDIA driver from nvidia.com, restart, run `setup.bat` again. |
| `Python 3.12 not found` (setup) | Install Python 3.12 from python.org with "Add to PATH" ticked, open a new terminal, run `setup.bat` again. |
| `CUDA available: False` (end of setup) | Update the NVIDIA driver, restart, then delete the `.venv` folder and run `setup.bat` again. |
| `FAIL this torch build has no kernels for sm_120` (calibrate) | The wrong PyTorch build is installed. Delete `.venv` and run `setup.bat` again. Never `pip install torch` by hand. |
| `batch plan WILL NOT FIT in bfloat16` | The GPU has too little memory (needs about 6.2 GB free). Close other programs that use the GPU (games, video, browser tabs with video), or use a bigger GPU. |
| A `mean` below 0.95 and `CALIBRATE: FAIL` | Stop. Send the newest file in `logs` to the owner. |
| A download stalls or crawls | Press `Ctrl+C`, run `set HF_HUB_DISABLE_XET=1`, run the same command again. |
| `PREFLIGHT: FAIL` | Read the `ERRORS` section of `preflight-report.txt`. It names each file and the problem. Rename, fix or remove those, then run preflight again. |
| `is a folder; each book must be one PDF file` | Join the parts into one PDF, named by the convention, and remove the folder. |
| `the same file is used for two books` | Two names hold the same PDF. Find out which one is right and remove the other. |
| `out of memory; retrying at batch 1` | Nothing to do; it continues more slowly. |
| `out of memory at batch 1` | Close every other program that uses the GPU, then run the same command again. |
| `Physics 9 gate FAILED` / `STOPPED` | Stop. Send `out\logs` to the owner. |
| `CUDA error ... Re-run the same command to resume` | Run the same command again. If it keeps happening, restart the laptop first. |
| A book shows `FAILED` in the summary | Run the same command again. If the same book fails again, send `out\logs`. |
| `VERIFY: FAIL` | Send `out\verify-report.txt` to the owner. |
| The console seems frozen | You probably clicked inside it. Press `Esc`. |

---

## Questions

**Can I stop and continue another day?**
Yes. Run the same command again: finished books are skipped.

**More PDFs arrived after I started. What do I do?**
Put them in the same PDF folder and run `preflight`, then step 6, then step 7, then step 8
again. Only the new books are processed.

**How do I redo one book on purpose?**
Add `--books <name> --force`, for example:

```
py encode_books.py run --input D:\books --out out --books Sindh_10_Maths --force
```

**Can I use the laptop while it runs?**
Light use (a browser, documents) is fine. Avoid games, video editing or anything else that
uses the GPU heavily: it slows the run and can run it out of memory.

**Where does the 9 GB model go?**
Your Hugging Face cache (`%USERPROFILE%\.cache\huggingface\hub`), unless you set `HF_HOME`.
It can be deleted after the owner confirms everything arrived.

**Is anything sent anywhere?**
No. Apart from downloading the models during setup and calibrate, everything stays on your
machine until you upload the `out` folder yourself.
