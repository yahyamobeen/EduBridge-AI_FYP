"""
The guardian gate flow (RBAC-002), end to end through the real API inside the
rolled-back test transaction.

The invite token travels by EMAIL in production and the API response never
contains it (only the mock's dev shortcut does). A test therefore cannot read
the token the invite endpoint issued — the token delivery seam is the one thing
here that is genuinely out of band. The tests that need a plaintext token for
`/guardian/confirm` issue one through the real issuance function
(`issue_guardian_invite_token`) after the invite created the pending link, which
is exactly the state the parent would be in after opening the email.

Setup inserts bind a user first (the applied `app_user_insert` policy is
owner-scoped) — see the same note in test_rls.py.
"""

from uuid import UUID, uuid4

from sqlalchemy import text

from app.auth.security import create_access_token
from app.auth.tokens import issue_guardian_invite_token
from app.core.db import set_current_user_id

GROUP_BY_CLASS = {9: "science", 10: "computer", 11: "pre_medical", 12: "pre_medical"}


def _create_user(db, email, *, role="student", class_level=9, full_name="Test User") -> str:
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
            "VALUES (:id, :email, 'x', :role, 'active', :full_name)"
        ),
        {"id": user_id, "email": email, "role": role, "full_name": full_name},
    )
    if role == "student":
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:id, 'PCTB', :level, :group, 'en', 'en')"
            ),
            {"id": user_id, "level": class_level, "group": GROUP_BY_CLASS[class_level]},
        )
    elif role == "parent":
        db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": user_id})
    db.flush()
    return str(user_id)


def _link(db, *, parent_id, student_id, status="pending"):
    """Create a guardian_link as the parent (a participant, so RLS allows it)."""
    set_current_user_id(db, UUID(parent_id))
    if status == "verified":
        db.execute(
            text(
                "INSERT INTO guardian_link (parent_id, student_id, status, "
                "verification_method, verified_at) "
                "VALUES (:p, :s, 'verified', 'oob_email', now())"
            ),
            {"p": parent_id, "s": student_id},
        )
    else:
        db.execute(
            text(
                "INSERT INTO guardian_link (parent_id, student_id, status) VALUES (:p, :s, :status)"
            ),
            {"p": parent_id, "s": student_id, "status": status},
        )
    db.flush()


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


class TestInvite:
    def test_invite_happy_path(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": parent_email},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["invite_sent"] is True
        assert body["status"] == "pending"
        assert body["parent_email"] == f"{parent_email[0]}***@{parent_email.split('@')[1]}"

        # The link exists, pending, and an invite token was stored.
        link_status = db.execute(
            text("SELECT status FROM guardian_link WHERE student_id = :s"),
            {"s": student},
        ).scalar_one()
        assert link_status == "pending"

    def test_self_link_is_forbidden(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        own_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": student}
        ).scalar()

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": own_email},
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SELF_LINK_FORBIDDEN"

    def test_unknown_parent_email_is_guardian_not_found(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": "nobody@example.com"},
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "GUARDIAN_NOT_FOUND"

    def test_a_non_parent_or_inactive_account_is_not_linkable(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        # A teacher's address must not resolve as a parent.
        teacher = _create_user(db, unique_email("gate"), role="teacher")
        teacher_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": teacher}
        ).scalar()

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": teacher_email},
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "GUARDIAN_NOT_FOUND"

    def test_invite_with_a_verified_link_is_409(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        _link(db, parent_id=parent, student_id=student, status="verified")

        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": parent_email},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GUARDIAN_ALREADY_LINKED"

    def test_invite_requires_the_student_role(self, client, db, unique_email):
        parent = _create_user(db, unique_email("gate"), role="parent")

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(parent),
            json={"parent_email": "x@example.com"},
        )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    def test_reinvite_invalidates_older_tokens(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()

        # A pending link with a token issued directly (the "old email").
        _link(db, parent_id=parent, student_id=student, status="pending")
        old_token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        # Resend through the API: the old token must now be dead.
        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": parent_email},
        )
        assert resp.status_code == 200

        confirm = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": old_token},
        )
        assert confirm.status_code == 400
        assert confirm.json()["error"]["code"] == "INVALID_TOKEN"


class TestConfirm:
    def test_confirm_flips_the_link_and_consumes_the_token(self, client, db, unique_email):
        student = _create_user(
            db, unique_email("gate"), role="student", class_level=9, full_name="Ayesha"
        )
        parent = _create_user(db, unique_email("gate"), role="parent")
        _link(db, parent_id=parent, student_id=student, status="pending")
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": token},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "verified", "student_name": "Ayesha"}

        status = db.execute(
            text(
                "SELECT status, verification_method, verified_at IS NOT NULL "
                "FROM guardian_link WHERE student_id = :s"
            ),
            {"s": student},
        ).one()
        assert status == ("verified", "oob_email", True)

        # One-time-use: the consumed token cannot be replayed.
        replay = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": token},
        )
        assert replay.status_code == 400
        assert replay.json()["error"]["code"] == "INVALID_TOKEN"

    def test_unknown_token_is_invalid(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        _link(db, parent_id=parent, student_id=student, status="pending")

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": "definitely-not-a-real-token"},
        )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_a_token_only_confirms_the_linked_parent(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        linked_parent = _create_user(db, unique_email("gate"), role="parent")
        other_parent = _create_user(db, unique_email("gate"), role="parent")
        _link(db, parent_id=linked_parent, student_id=student, status="pending")
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(other_parent),
            json={"invite_token": token},
        )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_confirm_of_an_already_verified_link_is_409(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        _link(db, parent_id=parent, student_id=student, status="verified")
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": token},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GUARDIAN_ALREADY_LINKED"

    def test_a_revoked_link_cannot_be_confirmed(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        _link(db, parent_id=parent, student_id=student, status="revoked")
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": token},
        )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_confirm_requires_the_parent_role(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(student),
            json={"invite_token": token},
        )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


class TestStatus:
    def test_status_is_null_when_no_link_exists(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)

        resp = client.get("/api/auth/guardian/status", headers=_auth(student))

        assert resp.status_code == 200
        assert resp.json() == {
            "required": True,
            "status": None,
            "parent_email": None,
            "invited_at": None,
        }

    def test_status_reflects_a_pending_invite(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()

        client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": parent_email},
        )

        resp = client.get("/api/auth/guardian/status", headers=_auth(student))
        body = resp.json()
        assert resp.status_code == 200
        assert body["required"] is True
        assert body["status"] == "pending"
        assert body["parent_email"] == f"{parent_email[0]}***@{parent_email.split('@')[1]}"
        assert body["invited_at"] is not None

    def test_status_passes_revoked_through_unchanged(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        _link(db, parent_id=parent, student_id=student, status="revoked")

        resp = client.get("/api/auth/guardian/status", headers=_auth(student))

        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "revoked"
        assert body["required"] is True

    def test_class_11_student_is_never_required(self, client, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=11)

        resp = client.get("/api/auth/guardian/status", headers=_auth(student))

        assert resp.status_code == 200
        assert resp.json()["required"] is False
        assert resp.json()["status"] is None

    def test_status_requires_the_student_role(self, client, db, unique_email):
        parent = _create_user(db, unique_email("gate"), role="parent")

        resp = client.get("/api/auth/guardian/status", headers=_auth(parent))

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


class TestFullFlow:
    """invite -> status -> confirm -> status, all through the API."""

    def test_full_flow(self, client, db, unique_email):
        student = _create_user(
            db, unique_email("gate"), role="student", class_level=9, full_name="Ayesha"
        )
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()

        invite = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": parent_email},
        )
        assert invite.status_code == 200

        pending = client.get("/api/auth/guardian/status", headers=_auth(student))
        assert pending.json()["status"] == "pending"

        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        confirm = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": token},
        )
        assert confirm.status_code == 200
        assert confirm.json()["student_name"] == "Ayesha"

        done = client.get("/api/auth/guardian/status", headers=_auth(student))
        assert done.json()["status"] == "verified"
        assert done.json()["required"] is True


class TestSelfLinkBlockedAtSchema:
    def test_a_student_cannot_create_a_self_link(self, db, unique_email):
        """ck_guardian_not_self AND the RLS WITH CHECK both reject it."""
        import pytest
        from sqlalchemy.exc import DBAPIError, ProgrammingError

        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        set_current_user_id(db, UUID(student))

        with pytest.raises((ProgrammingError, DBAPIError)):
            db.execute(
                text(
                    "INSERT INTO guardian_link (parent_id, student_id, status) "
                    "VALUES (:id, :id, 'pending')"
                ),
                {"id": student},
            )
            db.flush()
