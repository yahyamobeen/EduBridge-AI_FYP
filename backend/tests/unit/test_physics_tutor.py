"""Unit tests for the Class 9 Physics AI Tutor module."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthContext
from app.core.errors import AppError
from app.main import create_app
from app.retrieval.physics9.generator import PhysicsGenerator
from app.retrieval.physics9.retriever import CHAPTERS, PhysicsRetriever, chapter_of
from app.retrieval.physics9.service import answer_physics_query
from app.tutor.routes import require_class_9_student


def test_chapter_mapping():
    assert chapter_of(1) is None  # Front matter
    assert chapter_of(5) == 1
    assert chapter_of(27) == 1
    assert chapter_of(148) == 7
    assert chapter_of(155) == 7
    assert chapter_of(160) == 7
    assert chapter_of(195) is None  # Index / back matter
    assert len(CHAPTERS) == 9


def test_retriever_search_top_k():
    retriever = PhysicsRetriever(load_model=False)
    hits, encode_s, search_s = retriever.search("thermocouple working", top_k=3)
    assert len(hits) == 3
    assert all("page" in h and "chapter" in h and "score" in h and "url" in h for h in hits)
    # Thermocouple is in chapter 7 (p154-155)
    pages = [h["page"] for h in hits]
    assert 154 in pages or 155 in pages
    assert encode_s >= 0.0
    assert search_s >= 0.0


def test_generator_fallback_multilingual():
    gen = PhysicsGenerator(api_key="")
    hits = [
        {"page": 155, "chapter": 7, "score": 18.0, "url": "/api/tutor/class9/physics/pages/155"}
    ]

    # English
    reply_en, _, err_en = gen.generate("How does a thermocouple work?", hits, lang="en")
    assert "thermocouple" in reply_en.lower()
    assert "(p155)" in reply_en or "page 155" in reply_en.lower()
    assert err_en is not None  # Notes no api key

    # Roman Urdu
    reply_ur_latn, _, _ = gen.generate("thermocouple kaise kaam karta hai?", hits, lang="ur-Latn")
    assert "thermocouple" in reply_ur_latn.lower()  # Kept in English script
    assert "p155" in reply_ur_latn or "155" in reply_ur_latn

    # Urdu script
    reply_ur, _, _ = gen.generate("تھرمو کپل کیسے کام کرتا ہے؟", hits, lang="ur")
    assert "thermocouple" in reply_ur.lower()  # Kept in English script per pedagogical rule


def test_service_answer_physics_query():
    res = answer_physics_query("Explain Pascal's law with formula", lang="en", top_k=2)
    assert "reply" in res
    assert len(res["pages"]) == 2
    assert "timings" in res
    assert "encode" in res["timings"]
    assert "pascal" in res["reply"].lower()


def test_require_class_9_student_guard():
    user_id = uuid4()
    mock_session = MagicMock()

    # Case 1: Not a student
    teacher_ctx = AuthContext(session=mock_session, user_id=user_id, role="teacher")
    with pytest.raises(AppError) as exc_info:
        require_class_9_student(teacher_ctx)
    assert exc_info.value.code == "FORBIDDEN_SCOPE"

    # Case 2: Student in Class 10
    mock_result = MagicMock()
    mock_result.mappings.return_value.one_or_none.return_value = {"class_level": 10}
    mock_session.execute.return_value = mock_result
    student_10_ctx = AuthContext(session=mock_session, user_id=user_id, role="student")
    with pytest.raises(AppError) as exc_info:
        require_class_9_student(student_10_ctx)
    assert exc_info.value.code == "FORBIDDEN_SCOPE"

    # Case 3: Student in Class 9 -> passes
    mock_result.mappings.return_value.one_or_none.return_value = {"class_level": 9}
    student_9_ctx = AuthContext(session=mock_session, user_id=user_id, role="student")
    result_ctx = require_class_9_student(student_9_ctx)
    assert result_ctx.user_id == user_id


def test_tutor_info_endpoint():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/tutor/class9/physics/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["subject"] == "Physics"
    assert data["class_level"] == 9
    assert data["board"] == "PCTB"
    assert data["book_pages"] == 200


def test_page_image_bounds_check():
    from app.tutor.routes import get_physics_page_image

    # Page 0 and 201 should raise 404
    with pytest.raises(HTTPException) as exc1:
        get_physics_page_image(0)
    assert exc1.value.status_code == 404

    with pytest.raises(HTTPException) as exc2:
        get_physics_page_image(201)
    assert exc2.value.status_code == 404
