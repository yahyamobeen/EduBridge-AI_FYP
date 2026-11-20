"""The books the tutor can serve (tdd.md §3.2a "Many books").

A book is `<Board>_<Class>_<Subject>`, described by the `manifest.json` that
`ml/indexing` writes next to its page scans. This module turns a folder of those into
`Book` records the routes and the retrieval tiers share, and maps each onto the
subject catalogue in the database (`subject`, `board`, `class_level`).

Physics 9 is always present, served from the committed scans, so a host with an empty
`BOOKS_DIR` - production - serves exactly what it did before this module existed.

No torch, no httpx, no database: the routes do the ownership query and hand this module
the subject name, so everything here is testable from a temporary folder.

⚠️ FILE PATHS COME ONLY FROM CATALOGUE ENTRIES. A `book_id` arriving in a request is
looked up here and never joined onto a path, so `../../etc` is simply an unknown book.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.retrieval.physics9.base import BOOK_PAGES, CHAPTERS, PHYSICS_BOOK

logger = logging.getLogger("edubridge.retrieval.catalogue")

BOOK_ID = re.compile(r"^(Punjab|Sindh)_(9|10|11|12)_([A-Za-z]+)$")

# ml/indexing's names -> the subject catalogue's. The board column is `board_code`.
BOARD_CODES = {"Punjab": "PCTB", "Sindh": "STBB"}
SUBJECT_NAMES = {
    "English": "English",
    "Urdu": "Urdu",
    "Islamiat": "Islamiat",
    "PakStudies": "Pakistan Studies",
    "Maths": "Mathematics",
    "TarjumaTulQuran": "Quran Translation",
    "Physics": "Physics",
    "Chemistry": "Chemistry",
    "Biology": "Biology",
    "ComputerScience": "Computer Science",
}

# The Sindh board prints ONE book for both matric years in these subjects (owner,
# 2026-11-17), so a Class 10 student's English is the book named for Class 9.
SHARED_BOOKS: dict[str, tuple[int, ...]] = {
    "Sindh_9_English": (9, 10),
    "Sindh_10_Urdu": (9, 10),
    "Sindh_9_Islamiat": (9, 10),
}

# prd.md FR-17 disables generation and paraphrase for Quran translation. Until that has
# its own design the subject is listed as "coming soon", like a subject with no book.
HIDDEN_SUBJECTS = frozenset({"Quran Translation"})


@dataclass(frozen=True)
class Book:
    book_id: str
    board: str  # board_code: PCTB | STBB
    classes: tuple[int, ...]
    subject: str  # the subject catalogue's name
    pages: int
    pages_dir: Path | None
    chapters: dict[int, tuple[int, int]] | None = field(default=None, compare=False)

    @property
    def is_physics(self) -> bool:
        return self.book_id == PHYSICS_BOOK

    @property
    def hidden(self) -> bool:
        return self.subject in HIDDEN_SUBJECTS

    @property
    def available(self) -> bool:
        """Servable on THIS host: not hidden, and its page scans are here."""
        return not self.hidden and self.pages_dir is not None and self.pages_dir.is_dir()

    def chapter_of(self, page: int) -> int | None:
        for chapter, (first, last) in (self.chapters or {}).items():
            if first <= page <= last:
                return chapter
        return None

    def anchor(self, chapter: int | None) -> tuple[int, int] | None:
        """The page range a chapter anchor stands for, or None (no chapter, or none)."""
        if chapter is None or not self.chapters:
            return None
        return self.chapters.get(chapter)

    def page_path(self, page: int) -> Path | None:
        """The scan for one page, or None when the page or the folder is not there."""
        if self.pages_dir is None or not 1 <= page <= self.pages:
            return None
        path = self.pages_dir / f"p{page:03}.jpeg"
        return path if path.is_file() else None


class Catalogue:
    def __init__(self, books: dict[str, Book]) -> None:
        self.books = books

    def get(self, book_id: str | None) -> Book | None:
        return self.books.get(book_id) if book_id else None

    def for_subject(self, board: str, class_level: int, subject: str) -> Book | None:
        """The book a student of this board and class uses for this subject."""
        wanted = subject.casefold()
        for book in self.books.values():
            if (
                book.board == board
                and class_level in book.classes
                and book.subject.casefold() == wanted
            ):
                return book
        return None

    def for_session(self, board: str, class_level: int | None, subject: str | None) -> Book | None:
        """The book a stored session belongs to (derived, never stored).

        Pilot rows wrote lowercase `physics` - and only ever served the Punjab Physics 9
        book, whatever the student's board - so that exact value maps there. New
        sessions write the subject catalogue's name ("Physics", "Mathematics").
        """
        if subject == "physics":
            return self.get(PHYSICS_BOOK)
        if subject is None or class_level is None:
            return None
        return self.for_subject(board, class_level, subject)


def _book_from_manifest(folder: Path) -> Book | None:
    path = folder / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("book %s skipped: unreadable manifest (%s)", folder.name, exc)
        return None
    book_id = manifest.get("book_id")
    match = BOOK_ID.match(book_id or "")
    if not match or book_id != folder.name:
        # A renamed folder (e.g. `Punjab_11_Biology.WRONG`) lands here on purpose: that
        # is how a mislabelled book is taken out of service without touching code.
        logger.warning("book folder %s skipped: manifest book_id is %r", folder.name, book_id)
        return None
    board, class_level, token = match.group(1), int(match.group(2)), match.group(3)
    pages = manifest.get("pages")
    if token not in SUBJECT_NAMES or not isinstance(pages, int) or pages < 1:
        logger.warning("book %s skipped: unknown subject or page count", book_id)
        return None
    if manifest.get("complete") is not True:
        logger.warning("book %s skipped: not marked complete", book_id)
        return None
    pages_dir = folder / "pages"
    chapters = CHAPTERS if book_id == PHYSICS_BOOK and pages == BOOK_PAGES else None
    return Book(
        book_id=book_id,
        board=BOARD_CODES[board],
        classes=SHARED_BOOKS.get(book_id, (class_level,)),
        subject=SUBJECT_NAMES[token],
        pages=pages,
        pages_dir=pages_dir if pages_dir.is_dir() else None,
        chapters=chapters,
    )


def load_catalogue(books_dir: str | Path | None, physics_pages_dir: Path | None) -> Catalogue:
    """Physics 9 from the committed scans, then every book under `books_dir`.

    A book folder there replaces the built-in Physics entry, so the laptop serves the
    same Physics scans it indexed. A malformed folder is skipped with a warning rather
    than refusing the start: the backend degrades, the retrieval service does not.
    """
    books: dict[str, Book] = {
        PHYSICS_BOOK: Book(
            book_id=PHYSICS_BOOK,
            board="PCTB",
            classes=(9,),
            subject="Physics",
            pages=BOOK_PAGES,
            pages_dir=physics_pages_dir,
            chapters=CHAPTERS,
        )
    }
    if books_dir:
        root = Path(books_dir)
        if not root.is_dir():
            logger.warning("BOOKS_DIR %s is not a folder; serving Physics 9 only", root)
        else:
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                if (folder / "manifest.json").exists() and (book := _book_from_manifest(folder)):
                    books[book.book_id] = book
    logger.info(
        "tutor catalogue: %d book(s), %d available",
        len(books),
        sum(1 for b in books.values() if b.available),
    )
    return Catalogue(books)


_catalogue: Catalogue | None = None


def get_catalogue() -> Catalogue:
    global _catalogue
    if _catalogue is None:
        from app.core.config import get_settings
        from app.retrieval.physics9.local import _resolve_pages_dir

        settings = get_settings()
        _catalogue = load_catalogue(
            settings.books_dir or None, _resolve_pages_dir(settings.physics_pages_dir or None)
        )
    return _catalogue


def set_catalogue_for_tests(catalogue: Catalogue | None) -> None:
    global _catalogue
    _catalogue = catalogue
