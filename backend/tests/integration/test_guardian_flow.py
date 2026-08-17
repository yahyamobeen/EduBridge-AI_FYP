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

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.auth import email as email_module
from app.auth import service as service_module
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

    def test_invite_delivers_an_email_to_the_parent(self, client, db, unique_email, sent):
        """
        The invite must actually be emailed, not just marked `invite_sent`
        (finding A10 — the token was minted and discarded while the interface
        rendered "We emailed {email}").

        ⚠️ CAPTURED AT THE PROVIDER SEAM, NOT BY REPLACING `_queue_email`.

        The original version of this test monkeypatched `service._queue_email`
        with a 3-parameter stub. That made it blind to the ONE thing most likely
        to break here: this branch reaches mail through `send_after_commit`
        (session first, finding D1), and a stub with the older signature accepts
        a call the real function rejects with a TypeError. The endpoint answered
        500 and this test passed.

        Patching `get_email_sender` instead exercises the whole path — the real
        alias, the real outbox, the real release on commit — so the only way to
        pass is for a parent to actually receive something.
        """
        student = _create_user(
            db, unique_email("gate"), role="student", class_level=9, full_name="Ayesha"
        )
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
        assert resp.json()["invite_sent"] is True

        # `send_async` returns before delivery; the outbox is released on the
        # request's commit and dispatched on a worker thread.
        email_module.drain_pending_emails()

        assert len(sent) == 1, f"expected one delivered email, got {len(sent)}"
        to, subject, html = sent[0]
        assert to == parent_email
        assert "Ayesha" in subject
        # The confirm URL carries the locale segment and a token query param.
        assert "/en/guardian/confirm?token=" in html

    def test_a_refused_invite_mails_nobody(self, client, db, unique_email, sent):
        """
        The cheap half: validation runs before delivery, so an unknown parent
        address produces 422 and no mail.

        ⚠️ This does NOT prove the D1 rollback property, and saying so would be
        the more comfortable lie. The refusal happens before `_queue_email` is
        ever reached, so this passes whether or not the outbox works. The test
        below is the one that can tell.
        """
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": unique_email("nobody")},
        )

        assert resp.status_code == 422, resp.text
        email_module.drain_pending_emails()
        assert sent == []

    def test_an_invite_that_fails_after_queueing_mails_nobody(
        self, client, db, unique_email, sent, monkeypatch
    ):
        """
        The D1 property at the call site this merge added, forced rather than
        hoped for.

        The failure is injected AFTER `_queue_email` has run — `_mask_email` is
        the next statement — so the message is genuinely sitting in the outbox
        when the request dies. A guardian invite is exactly the message a parent
        acts on, and the token behind it no longer exists, so the only correct
        outcome is that nothing leaves.

        With `send_async` in place of `send_after_commit` this test fails: the
        worker thread has already been handed the message by the time the
        transaction rolls back.
        """
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()

        def _boom(_value: str) -> str:
            raise RuntimeError("injected failure after the email was queued")

        monkeypatch.setattr(service_module, "_mask_email", _boom)

        with pytest.raises(RuntimeError, match="injected failure"):
            client.post(
                "/api/auth/guardian/invite",
                headers=_auth(student),
                json={"parent_email": parent_email},
            )

        email_module.drain_pending_emails()
        assert sent == [], "an invite survived the rollback of the work that justified it"

    def test_the_invite_language_follows_app_user_not_the_profile(
        self, client, db, unique_email, sent
    ):
        """
        ⚠️ THE TWO COLUMNS DISAGREE ON PURPOSE HERE, AND ONLY ONE IS AUTHORITATIVE.

        `language_pref` moved to `app_user` in 20260816200000; the
        `student_profile` copy still exists but nothing writes it after
        registration. `PATCH /auth/me` and the settings screen update `app_user`
        alone, so reading the profile copy builds the invite in whatever language
        the student chose when they signed up and ignores every change since.

        Set to different values, this test fails against the LEFT JOIN and passes
        against `app_user`. Left equal — as a fixture naturally leaves them — it
        cannot tell the two apart at all.
        """
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        set_current_user_id(db, student)
        db.execute(text("UPDATE app_user SET language_pref = 'ur' WHERE id = :id"), {"id": student})
        stale = db.execute(
            text("SELECT language_pref FROM student_profile WHERE user_id = :id"), {"id": student}
        ).scalar()
        assert stale == "en", "fixture no longer sets up the disagreement this test needs"

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
        email_module.drain_pending_emails()

        _, _, html = sent[0]
        assert "/ur/guardian/confirm?token=" in html
        assert "/en/guardian/confirm?token=" not in html

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

    def test_invite_with_a_verified_link_is_409(self, client, db, unique_email, make_link):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="verified")

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

    def test_reinvite_invalidates_older_tokens(self, client, db, unique_email, make_link):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()

        # A pending link with a token issued directly (the "old email").
        make_link(parent_id=parent, student_id=student, status="pending")
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

    def test_reinvite_after_a_revoke_actually_resets_the_link(
        self, client, db, unique_email, make_link
    ):
        """
        REGRESSION. The re-invite reset was an UPDATE issued as the student, and
        `guardian_link_update` is parent-only — so it matched zero rows and
        raised nothing. The endpoint answered `{"invite_sent": true, "status":
        "pending"}` while the link stayed `revoked`, `GET /guardian/status`
        contradicted it on the very next poll, and the parent's fresh
        invitation was then refused by `app.confirm_guardian_link`, which only
        transitions `pending`. The student had no route back through the API.

        The reset now goes through `app.reinvite_guardian_link`, so all three
        views agree and the invitation is confirmable.
        """
        student = _create_user(
            db, unique_email("gate"), role="student", class_level=9, full_name="Ayesha"
        )
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()
        make_link(parent_id=parent, student_id=student, status="revoked")

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": parent_email},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "pending"

        # The response, the status endpoint and the row must not disagree.
        assert client.get("/api/auth/guardian/status", headers=_auth(student)).json()["status"] == (
            "pending"
        )
        set_current_user_id(db, UUID(student))
        assert (
            db.execute(
                text("SELECT status FROM guardian_link WHERE student_id = :s"), {"s": student}
            ).scalar_one()
            == "pending"
        )

        # And the invitation the parent receives is now actually confirmable.
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()
        confirm = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": token},
        )
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["student_name"] == "Ayesha"

    def test_reinvite_to_the_same_parent_stays_pending(self, client, db, unique_email, make_link):
        """The ordinary resend: an existing pending link is reset, not duplicated."""
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        parent_email = db.execute(
            text("SELECT email FROM app_user WHERE id = :id"), {"id": parent}
        ).scalar()
        make_link(parent_id=parent, student_id=student, status="pending")

        resp = client.post(
            "/api/auth/guardian/invite",
            headers=_auth(student),
            json={"parent_email": parent_email},
        )

        assert resp.status_code == 200, resp.text
        set_current_user_id(db, UUID(student))
        assert (
            db.execute(
                text("SELECT count(*) FROM guardian_link WHERE student_id = :s"), {"s": student}
            ).scalar_one()
            == 1
        )


class TestConfirm:
    def test_confirm_flips_the_link_and_consumes_the_token(
        self, client, db, unique_email, make_link
    ):
        student = _create_user(
            db, unique_email("gate"), role="student", class_level=9, full_name="Ayesha"
        )
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="pending")
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

    def test_unknown_token_is_invalid(self, client, db, unique_email, make_link):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="pending")

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": "definitely-not-a-real-token"},
        )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_a_token_only_confirms_the_linked_parent(self, client, db, unique_email, make_link):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        linked_parent = _create_user(db, unique_email("gate"), role="parent")
        other_parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=linked_parent, student_id=student, status="pending")
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(other_parent),
            json={"invite_token": token},
        )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_confirm_of_an_already_verified_link_is_409(self, client, db, unique_email, make_link):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="verified")
        token = issue_guardian_invite_token(db, UUID(student))
        db.flush()

        resp = client.post(
            "/api/auth/guardian/confirm",
            headers=_auth(parent),
            json={"invite_token": token},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GUARDIAN_ALREADY_LINKED"

    def test_a_revoked_link_cannot_be_confirmed(self, client, db, unique_email, make_link):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="revoked")
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

    def test_status_passes_revoked_through_unchanged(self, client, db, unique_email, make_link):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="revoked")

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


class TestVerificationCannotBeForged:
    """
    Migration 20260803090000. `rls_policies.sql` claims of guardian_link that
    "neither may forge a verified status"; before that migration the policies
    did not enforce it and a direct INSERT of a verified row was ALLOWED. These
    are the negative tests that claim needed: after this, `verified` is
    reachable only through `app.confirm_guardian_link`, which demands a valid
    one-time invite token.
    """

    def test_a_student_cannot_insert_an_already_verified_link(self, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        set_current_user_id(db, UUID(student))

        with pytest.raises((ProgrammingError, DBAPIError)):
            db.execute(
                text(
                    "INSERT INTO guardian_link (parent_id, student_id, status, "
                    "verification_method, verified_at) "
                    "VALUES (:p, :s, 'verified', 'oob_email', now())"
                ),
                {"p": parent, "s": student},
            )

    def test_a_parent_cannot_insert_an_already_verified_link(self, db, unique_email):
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        set_current_user_id(db, UUID(parent))

        with pytest.raises((ProgrammingError, DBAPIError)):
            db.execute(
                text(
                    "INSERT INTO guardian_link (parent_id, student_id, status, "
                    "verification_method, verified_at) "
                    "VALUES (:p, :s, 'verified', 'oob_email', now())"
                ),
                {"p": parent, "s": student},
            )

    def test_a_student_cannot_update_their_own_link_at_all(self, db, unique_email, make_link):
        """
        `guardian_link_update` is parent-only, so the student's UPDATE matches
        zero rows. It does NOT raise — which is exactly why `guardian_invite`
        must not depend on it (see the re-invite regression below).
        """
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="pending")

        set_current_user_id(db, UUID(student))
        affected = db.execute(
            text(
                "UPDATE guardian_link SET status = 'verified', "
                "verification_method = 'oob_email', verified_at = now() "
                "WHERE student_id = :s"
            ),
            {"s": student},
        ).rowcount

        assert affected == 0
        set_current_user_id(db, UUID(student))
        assert (
            db.execute(
                text("SELECT status FROM guardian_link WHERE student_id = :s"), {"s": student}
            ).scalar_one()
            == "pending"
        )

    def test_a_parent_cannot_update_a_link_to_verified(self, db, unique_email, make_link):
        """A parent may withdraw consent, never grant it outside the token path."""
        student = _create_user(db, unique_email("gate"), role="student", class_level=9)
        parent = _create_user(db, unique_email("gate"), role="parent")
        make_link(parent_id=parent, student_id=student, status="pending")

        set_current_user_id(db, UUID(parent))
        with pytest.raises((ProgrammingError, DBAPIError)):
            db.execute(
                text(
                    "UPDATE guardian_link SET status = 'verified', "
                    "verification_method = 'oob_email', verified_at = now() "
                    "WHERE student_id = :s"
                ),
                {"s": student},
            )
