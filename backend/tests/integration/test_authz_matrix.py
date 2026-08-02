"""
The RBAC authorization matrix (prd.md §4.2, §4.3).

The four gated learning families — /api/tutor/*, /api/practice/adaptive,
/api/quiz/*/attempts*, /api/reports/* — do not have routers in this repo yet
(they belong to teammates), so the gate is PROVEN by mounting the REAL
`require_guardian_verified` dependency onto representative paths on a minimal
in-test app, which uses the exact same `authenticated` -> SessionLocal machinery
as production (patched by conftest to the test transaction). The role and
subject-scope dependencies are exercised the same way, and the guardian
endpoints themselves via the real client.
"""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.dependencies import (
    AuthContext,
    require_guardian_verified,
    require_subject_scope,
)
from app.auth.security import create_access_token
from app.core.db import set_current_user_id
from app.core.errors import register_exception_handlers

GROUP_BY_CLASS = {9: "science", 10: "computer", 11: "pre_medical", 12: "pre_medical"}

# Four representative paths, one per gated family. Method is irrelevant to the
# dependency, so all are GET to keep the matrix iteration trivial.
GATED_PATHS = [
    "/api/tutor/ask",
    "/api/practice/adaptive",
    "/api/quiz/x/attempts/start",
    "/api/reports/weekly",
]


def _create_user(db, email, *, role="student", class_level=9, profile=True) -> str:
    """`profile=False` builds a student with NO student_profile row — the shape
    the gate has to fail closed on, because an unknown class level is
    indistinguishable from an unreadable one."""
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
            "VALUES (:id, :email, 'x', :role, 'active', 'Test User')"
        ),
        {"id": user_id, "email": email, "role": role},
    )
    if not profile:
        db.flush()
        return str(user_id)
    if role == "student":
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, 'PCTB', :level, :group, 'en', 'en')"
            ),
            {"id": user_id, "level": class_level, "group": GROUP_BY_CLASS[class_level]},
        )
    elif role == "teacher":
        db.execute(text("INSERT INTO teacher_profile (user_id) VALUES (:id)"), {"id": user_id})
    elif role == "parent":
        db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _subject_scope_app() -> FastAPI:
    """
    The subject-scope dependency mounted the way a real classroom route mounts
    it: `Depends(require_subject_scope)` on a path that DECLARES `{subject_id}`,
    so FastAPI resolves the id per request. It used to be a factory taking the
    id as a closure argument, which could not see a path parameter at all — and
    the test that appeared to wire one up was in fact binding the enclosing
    function's local variable, so it passed while proving nothing.
    """
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/api/teacher/subjects/{subject_id}/students")
    def _roster(ctx: Annotated[AuthContext, Depends(require_subject_scope)]):
        return {"ok": True}

    return app


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


def _gate_client() -> TestClient:
    """Minimal app mounting the REAL gate on the learning paths."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/api/tutor/ask")
    def _tutor(ctx: AuthContext = Depends(require_guardian_verified)):
        return {"ok": True}

    @app.get("/api/practice/adaptive")
    def _practice(ctx: AuthContext = Depends(require_guardian_verified)):
        return {"ok": True}

    @app.get("/api/quiz/{quiz_id}/attempts/start")
    def _attempt(quiz_id: str, ctx: AuthContext = Depends(require_guardian_verified)):
        return {"ok": True}

    @app.get("/api/reports/weekly")
    def _reports(ctx: AuthContext = Depends(require_guardian_verified)):
        return {"ok": True}

    return TestClient(app)


class TestGuardianGateOnLearningEndpoints:
    def test_class_9_student_without_a_verified_guardian_is_blocked_everywhere(
        self, db, unique_email
    ):
        student = _create_user(db, unique_email("mx"), role="student", class_level=9)
        client = _gate_client()

        for path in GATED_PATHS:
            resp = client.get(path, headers=_auth(student))
            assert resp.status_code == 403, (path, resp.text)
            assert resp.json()["error"]["code"] == "GATE_PENDING", path

    def test_class_10_student_without_a_verified_guardian_is_blocked(self, db, unique_email):
        student = _create_user(db, unique_email("mx"), role="student", class_level=10)
        client = _gate_client()

        resp = client.get("/api/tutor/ask", headers=_auth(student))

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "GATE_PENDING"

    def test_verified_guardian_opens_every_gated_path(self, db, unique_email, make_link):
        student = _create_user(db, unique_email("mx"), role="student", class_level=9)
        parent = _create_user(db, unique_email("mx"), role="parent")
        make_link(parent_id=parent, student_id=student, status="verified")
        client = _gate_client()

        for path in GATED_PATHS:
            resp = client.get(path, headers=_auth(student))
            assert resp.status_code == 200, (path, resp.text)

    @pytest.mark.parametrize("class_level", [11, 12])
    def test_class_11_12_students_are_never_gated(self, class_level, db, unique_email):
        student = _create_user(db, unique_email("mx"), role="student", class_level=class_level)
        client = _gate_client()

        for path in GATED_PATHS:
            resp = client.get(path, headers=_auth(student))
            assert resp.status_code == 200, (path, resp.text)

    def test_a_student_with_no_profile_is_gated_not_waved_through(self, db, unique_email):
        """
        FAIL CLOSED. No `student_profile` row means the class level is unknown,
        and under RLS an unreadable row looks exactly like an absent one. The
        gate used to treat unknown as "not 9-10" and let the request through —
        serving a possibly-14-year-old because a read came back empty. It now
        holds, and `me()` reports `guardian_link_pending` to match, so the
        student lands on a screen that can actually resolve it.
        """
        student = _create_user(db, unique_email("mx"), role="student", profile=False)
        client = _gate_client()

        for path in GATED_PATHS:
            resp = client.get(path, headers=_auth(student))
            assert resp.status_code == 403, (path, resp.text)
            assert resp.json()["error"]["code"] == "GATE_PENDING", path

    @pytest.mark.parametrize("role", ["teacher", "parent", "admin"])
    def test_non_students_are_never_gated(self, role, db, unique_email):
        user = _create_user(db, unique_email("mx"), role=role)
        client = _gate_client()

        for path in GATED_PATHS:
            resp = client.get(path, headers=_auth(user))
            assert resp.status_code == 200, (path, resp.text)

    def test_a_revoked_link_holds_the_gate(self, db, unique_email, make_link):
        """`revoked` is not `verified`: consent withdrawn means the gate closes."""
        student = _create_user(db, unique_email("mx"), role="student", class_level=9)
        parent = _create_user(db, unique_email("mx"), role="parent")
        make_link(parent_id=parent, student_id=student, status="revoked")
        client = _gate_client()

        resp = client.get("/api/tutor/ask", headers=_auth(student))

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "GATE_PENDING"


class TestTeacherSubjectScope:
    def test_teacher_with_scope_passes_the_subject_route(self, db, unique_email):
        teacher = _create_user(db, unique_email("mx"), role="teacher")
        subject_id = db.execute(text("SELECT id FROM subject ORDER BY name LIMIT 1")).scalar_one()
        # Scope rows are provisioned by an admin (tss_admin_write), so seed as one.
        admin = _create_user(db, unique_email("mx"), role="admin")
        set_current_user_id(db, UUID(admin))
        db.execute(
            text("INSERT INTO teacher_subject_scope (teacher_id, subject_id) VALUES (:t, :s)"),
            {"t": teacher, "s": subject_id},
        )
        db.flush()

        resp = TestClient(_subject_scope_app()).get(
            f"/api/teacher/subjects/{subject_id}/students", headers=_auth(teacher)
        )
        assert resp.status_code == 200

    def test_teacher_without_scope_is_forbidden(self, db, unique_email):
        teacher = _create_user(db, unique_email("mx"), role="teacher")
        subject_id = db.execute(text("SELECT id FROM subject ORDER BY name LIMIT 1")).scalar_one()

        resp = TestClient(_subject_scope_app()).get(
            f"/api/teacher/subjects/{subject_id}/students", headers=_auth(teacher)
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    def test_a_student_has_no_teacher_scope(self, db, unique_email):
        student = _create_user(db, unique_email("mx"), role="student", class_level=11)
        subject_id = db.execute(text("SELECT id FROM subject ORDER BY name LIMIT 1")).scalar_one()

        resp = TestClient(_subject_scope_app()).get(
            f"/api/teacher/subjects/{subject_id}/students", headers=_auth(student)
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    def test_the_scope_is_read_from_the_path_not_from_a_closure(self, db, unique_email):
        """
        The bug this dependency had: written as a factory it took the subject id
        at route-definition time, so every request checked the SAME id no matter
        what the URL said. A teacher scoped to subject A would have passed a
        request for subject B. Two subjects, one scope row, opposite answers.
        """
        teacher = _create_user(db, unique_email("mx"), role="teacher")
        scoped, other = (
            db.execute(text("SELECT id FROM subject ORDER BY name LIMIT 2")).scalars().all()
        )
        admin = _create_user(db, unique_email("mx"), role="admin")
        set_current_user_id(db, UUID(admin))
        db.execute(
            text("INSERT INTO teacher_subject_scope (teacher_id, subject_id) VALUES (:t, :s)"),
            {"t": teacher, "s": scoped},
        )
        db.flush()

        client = TestClient(_subject_scope_app())
        allowed = client.get(f"/api/teacher/subjects/{scoped}/students", headers=_auth(teacher))
        refused = client.get(f"/api/teacher/subjects/{other}/students", headers=_auth(teacher))

        assert allowed.status_code == 200, allowed.text
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "FORBIDDEN_SCOPE"


class TestGuardianEndpointsAreRoleGatedNotGuardianGated:
    """A gated student must still be able to reach /auth/guardian/*."""

    def test_a_gated_student_can_check_status_and_invite(self, client, db, unique_email):
        student = _create_user(db, unique_email("mx"), role="student", class_level=9)

        status = client.get("/api/auth/guardian/status", headers=_auth(student))
        assert status.status_code == 200

        invite = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": "someone@example.com"},
        )
        # Reaches the service (no verified link), so the only failure here would
        # be an over-eager gate. GUARDIAN_NOT_FOUND proves the request got past
        # the role dependency, not a GATE_PENDING.
        assert invite.status_code == 422
        assert invite.json()["error"]["code"] == "GUARDIAN_NOT_FOUND"

    def test_a_parent_cannot_reach_student_only_routes(self, client, db, unique_email):
        parent = _create_user(db, unique_email("mx"), role="parent")

        status = client.get("/api/auth/guardian/status", headers=_auth(parent))
        assert status.status_code == 403
        assert status.json()["error"]["code"] == "FORBIDDEN_SCOPE"

        invite = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(parent),
            json={"parent_email": "x@example.com"},
        )
        assert invite.status_code == 403
        assert invite.json()["error"]["code"] == "FORBIDDEN_SCOPE"
