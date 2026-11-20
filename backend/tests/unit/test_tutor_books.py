"""The tutor serving many books (tdd.md §3.2a "Many books").

No database and no model: the catalogue reads a temporary folder of manifests, and
the routes' database calls are replaced at the `tutor_service` boundary. What is under
test is the rule set - which books a student may use, what happens to a book that is
missing, hidden or another board's, and that every path stays inside its own book.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthContext, authenticated, require_guardian_verified
from app.core.errors import AppError
from app.main import create_app
from app.retrieval.physics9 import service as retrieval_service
from app.retrieval.physics9.base import (
    BOOK_PAGES,
    CHAPTERS,
    RetrievalUnavailableError,
    make_hits,
)
from app.retrieval.physics9.catalogue import (
    Book,
    Catalogue,
    load_catalogue,
    set_catalogue_for_tests,
)
from app.retrieval.physics9.generator import SYSTEM_PROMPT, system_prompt_for
from app.retrieval.physics9.heuristic import HeuristicRetriever
from app.retrieval.physics9.remote import RemoteRetriever
from app.tutor import routes
from app.tutor import service as tutor_service
from app.tutor.streaming import event_stream
from app.tutor.turns import classify

# -- a temporary folder of books ----------------------------------------------------


def _write_book(
    root: Path, book_id: str, pages: int, *, with_pages=True, complete=True, folder=None
):
    folder_path = root / (folder or book_id)
    folder_path.mkdir(parents=True)
    (folder_path / "manifest.json").write_text(
        json.dumps({"book_id": book_id, "pages": pages, "complete": complete}), encoding="utf-8"
    )
    if with_pages:
        (folder_path / "pages").mkdir()
        (folder_path / "pages" / "p001.jpeg").write_bytes(b"\xff\xd8 fake jpeg")


@pytest.fixture
def books_dir(tmp_path):
    root = tmp_path / "out"
    _write_book(root, "Sindh_10_Chemistry", 140)
    _write_book(root, "Sindh_9_English", 228)
    _write_book(root, "Sindh_10_Urdu", 109)
    _write_book(root, "Punjab_10_TarjumaTulQuran", 240)
    _write_book(root, "Punjab_11_Maths", 312, with_pages=False)
    _write_book(root, "Punjab_11_Biology", 156, folder="Punjab_11_Biology.WRONG")
    _write_book(root, "Punjab_12_Physics", 186, complete=False)
    (root / "logs").mkdir()
    return root


@pytest.fixture
def catalogue(books_dir):
    cat = load_catalogue(books_dir, None)
    set_catalogue_for_tests(cat)
    yield cat
    set_catalogue_for_tests(None)


# -- the catalogue ------------------------------------------------------------------


def test_physics_is_built_in_when_books_dir_is_empty():
    cat = load_catalogue(None, None)
    assert list(cat.books) == ["Punjab_9_Physics"]
    physics = cat.get("Punjab_9_Physics")
    assert physics.pages == BOOK_PAGES and physics.chapters == CHAPTERS


def test_manifests_are_mapped_onto_the_subject_catalogue(catalogue):
    chem = catalogue.get("Sindh_10_Chemistry")
    assert (chem.board, chem.classes, chem.subject, chem.pages) == ("STBB", (10,), "Chemistry", 140)
    assert chem.chapters is None and chem.available


def test_shared_sindh_books_serve_classes_9_and_10(catalogue):
    assert catalogue.get("Sindh_9_English").classes == (9, 10)
    assert catalogue.for_subject("STBB", 10, "English").book_id == "Sindh_9_English"
    assert catalogue.for_subject("STBB", 9, "Urdu").book_id == "Sindh_10_Urdu"


def test_quran_translation_is_hidden(catalogue):
    tarjuma = catalogue.get("Punjab_10_TarjumaTulQuran")
    assert tarjuma.subject == "Quran Translation" and tarjuma.hidden and not tarjuma.available


def test_a_book_without_page_scans_is_not_available(catalogue):
    assert not catalogue.get("Punjab_11_Maths").available


def test_a_renamed_folder_is_skipped(catalogue):
    """How a mislabelled book is taken out of service without touching code."""
    assert catalogue.get("Punjab_11_Biology") is None


def test_an_incomplete_book_is_skipped(catalogue):
    assert catalogue.get("Punjab_12_Physics") is None


def test_paths_come_only_from_catalogue_entries(catalogue):
    assert catalogue.get("../../etc/passwd") is None
    chem = catalogue.get("Sindh_10_Chemistry")
    assert chem.page_path(0) is None and chem.page_path(141) is None
    assert chem.page_path(1).name == "p001.jpeg"
    assert chem.page_path(2) is None  # in range, but the scan is not on this host


def test_session_books_are_derived(catalogue):
    assert catalogue.for_session("STBB", 9, "physics").book_id == "Punjab_9_Physics"  # pilot row
    assert catalogue.for_session("STBB", 10, "English").book_id == "Sindh_9_English"
    assert catalogue.for_session("STBB", 10, None) is None


def test_a_book_without_chapters_cites_pages_only():
    book = Book("Sindh_10_Chemistry", "STBB", (10,), "Chemistry", 140, None)
    hits = make_hits([(26, 9.3)], book)
    assert hits == [
        {
            "page": 26,
            "chapter": None,
            "score": 9.3,
            "url": "/api/tutor/books/Sindh_10_Chemistry/pages/26",
        }
    ]
    assert book.anchor(3) is None


# -- which books a student may use --------------------------------------------------

SUBJECTS_STBB_10_SCIENCE = [
    {"id": uuid4(), "name": n, "content_strategy": s}
    for n, s in (
        ("Biology", "branch_a_english_source"),
        ("Chemistry", "branch_a_english_source"),
        ("English", "english_language"),
        ("Urdu", "branch_b_urdu_native"),
    )
]


def _ctx(monkeypatch, board="STBB", class_level=10, group="science", subjects=None, session=None):
    monkeypatch.setattr(
        tutor_service,
        "student_profile",
        lambda *_: {"board": board, "class_level": class_level, "student_group": group},
    )
    monkeypatch.setattr(
        tutor_service,
        "student_subjects",
        lambda *_: SUBJECTS_STBB_10_SCIENCE if subjects is None else subjects,
    )
    if session is not None:
        monkeypatch.setattr(tutor_service, "session_meta", lambda *_: session)
    return AuthContext(session=None, user_id=uuid4(), role="student")


def _code(fn) -> str:
    with pytest.raises(AppError) as exc:
        fn()
    return exc.value.code


def test_the_students_own_book_resolves(monkeypatch, catalogue):
    ctx = _ctx(monkeypatch)
    resolved = routes.resolve_book(ctx, book_id="Sindh_10_Chemistry", session_id=None)
    assert resolved.book.book_id == "Sindh_10_Chemistry"
    assert resolved.class_level == 10 and resolved.content_strategy == "branch_a_english_source"


def test_a_class_10_student_gets_the_shared_class_9_book(monkeypatch, catalogue):
    ctx = _ctx(monkeypatch)
    assert routes.resolve_book(ctx, book_id="Sindh_9_English", session_id=None).book.classes == (
        9,
        10,
    )


def test_another_boards_book_is_refused(monkeypatch, catalogue):
    ctx = _ctx(monkeypatch, board="PCTB")
    assert _code(
        lambda: routes.resolve_book(ctx, book_id="Sindh_10_Chemistry", session_id=None)
    ) == ("FORBIDDEN_SCOPE")


def test_a_subject_outside_the_students_group_is_refused(monkeypatch, catalogue):
    ctx = _ctx(
        monkeypatch, subjects=[s for s in SUBJECTS_STBB_10_SCIENCE if s["name"] != "Chemistry"]
    )
    assert _code(
        lambda: routes.resolve_book(ctx, book_id="Sindh_10_Chemistry", session_id=None)
    ) == ("FORBIDDEN_SCOPE")


def test_another_classs_book_is_refused(monkeypatch, catalogue):
    ctx = _ctx(monkeypatch, class_level=11)
    assert _code(
        lambda: routes.resolve_book(ctx, book_id="Sindh_10_Chemistry", session_id=None)
    ) == ("FORBIDDEN_SCOPE")


def test_an_unknown_book_is_refused_like_an_unowned_one(monkeypatch, catalogue):
    ctx = _ctx(monkeypatch)
    assert _code(lambda: routes.resolve_book(ctx, book_id="../../etc", session_id=None)) == (
        "FORBIDDEN_SCOPE"
    )


def test_a_hidden_or_absent_book_is_unavailable(monkeypatch, catalogue):
    subjects = [
        {"id": uuid4(), "name": "Quran Translation", "content_strategy": "religious_verbatim"}
    ]
    ctx = _ctx(monkeypatch, board="PCTB", class_level=10, subjects=subjects)
    assert (
        _code(
            lambda: routes.resolve_book(ctx, book_id="Punjab_10_TarjumaTulQuran", session_id=None)
        )
        == "MODEL_UNAVAILABLE"
    )


def test_resuming_brings_the_sessions_book(monkeypatch, catalogue):
    session = {"id": uuid4(), "subject": "Chemistry", "class_level": 10, "chapter": None}
    ctx = _ctx(monkeypatch, session=session)
    assert (
        routes.resolve_book(ctx, book_id=None, session_id=uuid4()).book.book_id
        == "Sindh_10_Chemistry"
    )


def test_resuming_with_a_different_book_is_a_validation_error(monkeypatch, catalogue):
    session = {"id": uuid4(), "subject": "Chemistry", "class_level": 10, "chapter": None}
    ctx = _ctx(monkeypatch, session=session)
    assert _code(
        lambda: routes.resolve_book(ctx, book_id="Sindh_9_English", session_id=uuid4())
    ) == ("VALIDATION_ERROR")


# -- the routes ---------------------------------------------------------------------


def _client(monkeypatch, **profile):
    ctx = _ctx(monkeypatch, **profile)
    app = create_app()
    app.dependency_overrides[authenticated] = lambda: ctx
    app.dependency_overrides[require_guardian_verified] = lambda: ctx
    return TestClient(app)


def test_books_lists_the_students_subjects_with_availability(monkeypatch, catalogue):
    body = _client(monkeypatch).get("/api/tutor/books").json()
    assert body["board"] == "STBB" and body["class_level"] == 10
    assert {b["subject"]: (b["book_id"], b["available"]) for b in body["books"]} == {
        "Biology": (None, False),  # no book in this folder
        "Chemistry": ("Sindh_10_Chemistry", True),
        "English": ("Sindh_9_English", True),  # the shared Class 9 book
        "Urdu": ("Sindh_10_Urdu", True),
    }


def test_a_page_of_an_owned_book_is_served(monkeypatch, catalogue):
    resp = _client(monkeypatch).get("/api/tutor/books/Sindh_10_Chemistry/pages/1")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert "private" in resp.headers["cache-control"]


def test_a_page_outside_the_book_is_a_validation_error(monkeypatch, catalogue):
    resp = _client(monkeypatch).get("/api/tutor/books/Sindh_10_Chemistry/pages/141")
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_page_of_another_boards_book_is_refused(monkeypatch, catalogue):
    resp = _client(monkeypatch, board="PCTB").get("/api/tutor/books/Sindh_10_Chemistry/pages/1")
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_a_missing_scan_is_refused_not_404(monkeypatch, catalogue):
    resp = _client(monkeypatch).get("/api/tutor/books/Sindh_10_Chemistry/pages/2")
    assert resp.status_code == 403


# -- retrieval: no fallback outside Physics 9 -------------------------------------------

CHEMISTRY = Book("Sindh_10_Chemistry", "STBB", (10,), "Chemistry", 140, None)


def test_the_keyword_index_refuses_every_other_book():
    with pytest.raises(RetrievalUnavailableError):
        HeuristicRetriever().search("what is an ionic bond", book=CHEMISTRY)


def test_a_failed_tier_does_not_fall_back_for_another_book(monkeypatch):
    class Down:
        name = "remote"

        def search(self, *a, **k):
            raise RetrievalUnavailableError("down")

    monkeypatch.setattr(retrieval_service, "get_physics_retriever", lambda: Down())
    with pytest.raises(RetrievalUnavailableError):
        retrieval_service.search("what is an ionic bond", book=CHEMISTRY)
    # Physics 9 still degrades to its keyword index, exactly as before.
    hits, _timings, tier = retrieval_service.search("how does a thermocouple work")
    assert tier == "heuristic" and hits


def _remote_reply(monkeypatch, body):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr("app.retrieval.physics9.remote.httpx.Client", _Client)
    return captured


def test_the_remote_tier_sends_the_book_and_no_anchor_without_chapters(monkeypatch):
    captured = _remote_reply(
        monkeypatch, {"book": "Sindh_10_Chemistry", "pages": [26, 139], "scores": [9.3, 8.9]}
    )
    hits, _ = RemoteRetriever("https://r.example.com").search(
        "ionic bond", chapter=3, book=CHEMISTRY
    )
    assert captured["json"] == {"book": "Sindh_10_Chemistry", "question": "ionic bond", "top_k": 3}
    assert [h["url"] for h in hits] == [
        "/api/tutor/books/Sindh_10_Chemistry/pages/26",
        "/api/tutor/books/Sindh_10_Chemistry/pages/139",
    ]


def test_the_remote_tier_refuses_an_answer_for_another_book(monkeypatch):
    _remote_reply(monkeypatch, {"book": "Punjab_9_Physics", "pages": [26], "scores": [9.3]})
    with pytest.raises(RetrievalUnavailableError):
        RemoteRetriever("https://r.example.com").search("ionic bond", book=CHEMISTRY)


def test_the_remote_tier_bounds_pages_by_the_book(monkeypatch):
    _remote_reply(monkeypatch, {"book": "Sindh_10_Chemistry", "pages": [141], "scores": [9.3]})
    with pytest.raises(RetrievalUnavailableError):
        RemoteRetriever("https://r.example.com").search("ionic bond", book=CHEMISTRY)


def test_an_older_service_that_echoes_no_book_is_accepted(monkeypatch):
    _remote_reply(monkeypatch, {"pages": [155], "scores": [15.0]})
    hits, _ = RemoteRetriever("https://r.example.com").search("thermocouple")
    assert hits[0]["page"] == 155


# -- turns, follow-ups and figures stay in their book -------------------------------------


class _PayloadDB:
    """Answers `last_turn_pages`' single query with one stored citation payload."""

    def __init__(self, payload):
        self.payload = payload
        self.inserted: list[dict] = []

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        payload = self.payload

        class _R:
            def __init__(self, value):
                self.value = value

            def scalars(self):
                return self

            def one_or_none(self):
                return self.value

            def one(self):
                return uuid4()

        if "INSERT INTO" in sql:
            self.inserted.append(params or {})
        return _R(payload if "SELECT v.payload" in sql else None)


def test_a_follow_up_cites_its_own_books_pages():
    db = _PayloadDB({"pages": [{"page": 26, "chapter": None, "score": 9.3}]})
    pages = tutor_service.last_turn_pages(db, uuid4(), CHEMISTRY)
    assert pages[0]["url"] == "/api/tutor/books/Sindh_10_Chemistry/pages/26"


def test_a_figure_beyond_page_200_survives_in_a_long_book():
    db = _PayloadDB(None)
    marker = '@@FIGURE {"page": 300, "box": [0.1, 0.2, 0.8, 0.7], "caption": "Fig. 9.1"}'
    frames = b"".join(
        event_stream(
            db=db,
            session_id=uuid4(),
            question="q",
            hits=[{"page": 300, "chapter": None, "score": 1.0, "url": "u"}],
            retriever="remote",
            timings={},
            token_source=iter(["An answer.\n", marker]),
            book_pages=440,
        )
    ).decode()
    assert "event: figure" in frames and '"page": 300' in frames


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("explain that again", "followup"),
        ("phir se samjhao", "followup"),
        ("why?", "followup"),
        ("give another example", "followup"),
        ("explain photosynthesis again", "retrieve"),
        ("what about ionic bonds", "retrieve"),
        ("dobara batao mitosis", "retrieve"),
    ],
)
def test_books_without_a_vocabulary_retrieve_on_any_content_word(question, intent):
    assert classify(question, has_prior_turn=True, topic_terms=None) == intent


# -- the prompt follows the book ----------------------------------------------------------


def test_physics_keeps_its_prompt_word_for_word():
    assert system_prompt_for(None) is SYSTEM_PROMPT
    physics = Book("Punjab_9_Physics", "PCTB", (9,), "Physics", BOOK_PAGES, None, CHAPTERS)
    assert system_prompt_for(physics) is SYSTEM_PROMPT


def test_other_books_get_their_board_class_and_subject():
    prompt = system_prompt_for(CHEMISTRY, 10, "branch_a_english_source")
    assert "Chemistry tutor" in prompt and "Class 10" in prompt and "Sindh Textbook Board" in prompt
    assert "KEEP TECHNICAL TERMS IN ENGLISH" in prompt


def test_an_urdu_book_is_quoted_in_urdu_not_anglicised():
    urdu = Book("Sindh_10_Urdu", "STBB", (9, 10), "Urdu", 109, None)
    prompt = system_prompt_for(urdu, 9, "branch_b_urdu_native")
    assert prompt.startswith("You are an Urdu tutor")
    assert "KEEP TECHNICAL TERMS IN ENGLISH" not in prompt and "Urdu script" in prompt


def test_the_english_book_is_quoted_exactly():
    english = Book("Sindh_9_English", "STBB", (9, 10), "English", 228, None)
    assert "EXACTLY as printed" in system_prompt_for(english, 10, "english_language")


def test_an_unknown_catalogue_falls_back_to_physics_for_the_default_book():
    cat = Catalogue({})
    assert cat.get(None) is None and cat.for_session("PCTB", 9, None) is None
