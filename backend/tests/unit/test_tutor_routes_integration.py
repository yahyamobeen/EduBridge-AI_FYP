"""Integration tests for the Class 9 Physics Tutor routes using FastAPI TestClient."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthContext, authenticated, require_guardian_verified
from app.core.errors import AppError, forbidden_scope
from app.main import create_app
from app.tutor.routes import require_class_9_student


@pytest.fixture
def app_with_overrides():
    """Build FastAPI app with configurable dependency overrides for tutor testing."""
    return create_app()


def test_tutor_chat_success_for_class_9(app_with_overrides):
    """A verified Class 9 student can query the Physics Tutor and receive citations."""
    user_id = uuid4()
    mock_ctx = AuthContext(session=None, user_id=user_id, role="student")

    # Override dependencies to simulate valid authentication, guardian check, and class 9 check
    app_with_overrides.dependency_overrides[authenticated] = lambda: mock_ctx
    app_with_overrides.dependency_overrides[require_guardian_verified] = lambda: mock_ctx
    app_with_overrides.dependency_overrides[require_class_9_student] = lambda: mock_ctx

    client = TestClient(app_with_overrides)
    payload = {
        "message": "What is Pascal's law?",
        "lang": "en",
        "history": [],
    }

    resp = client.post("/api/tutor/class9/physics/chat", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data
    assert "pages" in data
    assert len(data["pages"]) > 0
    assert "timings" in data
    assert all("page" in p and "url" in p for p in data["pages"])


def test_tutor_chat_forbidden_for_other_grades(app_with_overrides):
    """Students in grades other than Class 9 must be rejected with FORBIDDEN_SCOPE."""
    user_id = uuid4()
    mock_ctx = AuthContext(session=None, user_id=user_id, role="student")

    def reject_grade():
        raise forbidden_scope("Only Class 9 students may access this tutor.")

    app_with_overrides.dependency_overrides[authenticated] = lambda: mock_ctx
    app_with_overrides.dependency_overrides[require_guardian_verified] = lambda: mock_ctx
    app_with_overrides.dependency_overrides[require_class_9_student] = reject_grade

    client = TestClient(app_with_overrides)
    payload = {"message": "Explain kinetic energy", "lang": "en"}

    resp = client.post("/api/tutor/class9/physics/chat", json=payload)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_tutor_chat_guardian_consent_required(app_with_overrides):
    """Unverified students cannot access tutor before guardian verification."""
    user_id = uuid4()
    mock_ctx = AuthContext(session=None, user_id=user_id, role="student")

    def reject_guardian():
        raise AppError(
            code="GUARDIAN_CONSENT_REQUIRED",
            message="Guardian verification required.",
            status_code=403,
        )

    app_with_overrides.dependency_overrides[authenticated] = lambda: mock_ctx
    app_with_overrides.dependency_overrides[require_guardian_verified] = reject_guardian

    client = TestClient(app_with_overrides)
    payload = {"message": "Explain kinetic energy", "lang": "en"}

    resp = client.post("/api/tutor/class9/physics/chat", json=payload)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "GUARDIAN_CONSENT_REQUIRED"


def test_tutor_chat_validation_error_on_empty_message(app_with_overrides):
    """Empty messages or missing fields should fail validation with 400 VALIDATION_ERROR."""
    user_id = uuid4()
    mock_ctx = AuthContext(session=None, user_id=user_id, role="student")

    app_with_overrides.dependency_overrides[authenticated] = lambda: mock_ctx
    app_with_overrides.dependency_overrides[require_guardian_verified] = lambda: mock_ctx
    app_with_overrides.dependency_overrides[require_class_9_student] = lambda: mock_ctx

    client = TestClient(app_with_overrides)

    # Empty string should fail min_length=1
    resp = client.post("/api/tutor/class9/physics/chat", json={"message": ""})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_page_scan_bounds_rejection(app_with_overrides):
    """Out-of-bounds page scan requests (e.g. 0, 201) return 404."""
    user_id = uuid4()
    mock_ctx = AuthContext(session=None, user_id=user_id, role="student")
    app_with_overrides.dependency_overrides[authenticated] = lambda: mock_ctx

    client = TestClient(app_with_overrides)

    resp_low = client.get("/api/tutor/class9/physics/pages/0")
    assert resp_low.status_code == 404

    resp_high = client.get("/api/tutor/class9/physics/pages/201")
    assert resp_high.status_code == 404
