"""
Email dispatch — findings D1 and D18 (Phase 5).

Two defects on the same code path, which is why they are fixed and tested
together.

**D1** — `send_async` handed the message to a worker thread immediately, while
the transaction that justified it was still open. The real commit happens in
`get_db` AFTER the route returns, so a request that failed late sent a
verification or reset link for a token row that was then rolled back. The user
receives a link that can only ever answer INVALID_TOKEN. An email is
unrecallable and a transaction is not, which is the wrong way round.

**D18** — `login()` never sent the email OTP at all. `_issue_and_send_email_otp`
was called from `two_factor_enroll` and `two_factor_resend` only, so an
`email_otp` account reached a challenge screen saying a code had been sent while
nothing was. The only way to get the first code was to press Resend on the
screen that exists to say the first one is coming.
"""

from uuid import uuid4

from sqlalchemy import text

from app.auth import email as email_module
from app.auth.email import send_after_commit
from app.auth.security import hash_password
from app.core.db import set_current_user_id

PASSWORD = "password123"  # noqa: S105 -- a fixture value, not a credential


# `_Recorder` and the `sent` fixture moved to conftest.py when the guardian
# invite acquired a delivery path and needed the same capture. One definition,
# because two would drift.


def _user(db, email: str, *, method: str | None = None) -> str:
    user_id = uuid4()
    set_current_user_id(db, user_id)
    db.execute(
        text(
            "INSERT INTO app_user "
            "(id, email, password_hash, role, status, full_name, email_verified_at) "
            "VALUES (:id, :e, :pw, 'parent', 'active', 'Dispatch Probe', now())"
        ),
        {"id": user_id, "e": email, "pw": hash_password(PASSWORD)},
    )
    db.execute(text("INSERT INTO parent_profile (user_id) VALUES (:id)"), {"id": user_id})
    if method is not None:
        db.execute(
            text(
                "INSERT INTO two_factor_enrollment "
                "(user_id, method, status, totp_secret_encrypted, confirmed_at) "
                "VALUES (:id, :m, 'active', NULL, now())"
            ),
            {"id": user_id, "m": method},
        )
    db.flush()

    # ⚠️ UNBIND BEFORE HANDING THE ACCOUNT BACK, AND THIS IS NOT TIDINESS.
    #
    # The harness routes every application session onto ONE connection, so the
    # `app.current_user_id` this helper set while inserting is STILL BOUND when
    # the test then calls an endpoint. Unauthenticated routes run on `get_db`,
    # which binds nobody — so without this line the request under test reads
    # `app_user` with a binding production would not have, and any missing
    # `set_current_user_id` in the code under test is invisible.
    #
    # That is not hypothetical: D18's first fix read the recipient row without
    # binding, this file's login test passed, and every `email_otp` sign-in
    # 500ed with `NoResultFound` in the browser.
    db.execute(text("SELECT set_config('app.current_user_id', '', true)"))
    return str(user_id)


class TestD1TheTransactionDecidesWhetherToSend:
    def test_a_rollback_discards_the_queued_email(self, db, sent):
        """
        ⚠️ THE DEFECT, STATED AS A TEST. Before this fix the message was already
        in flight by the time the rollback happened, so there was nothing to
        discard — the user had a link for a token that no longer existed.
        """
        send_after_commit(db, "nobody@example.com", "Subject", "<p>body</p>")
        db.rollback()
        email_module.drain_pending_emails()

        assert sent == [], "an email survived the rollback of the work that justified it"

    def test_a_commit_dispatches_it(self, db, sent):
        """
        The control. Without it, a change that simply dropped every message
        would pass the test above and look like a fix.
        """
        send_after_commit(db, "somebody@example.com", "Subject", "<p>body</p>")
        db.commit()
        email_module.drain_pending_emails()

        assert [to for to, _, _ in sent] == ["somebody@example.com"]

    def test_nothing_is_sent_before_the_commit(self, db, sent):
        """
        The ordering itself, rather than the outcome. Queuing must be inert
        until the transaction resolves — otherwise the fix is only a narrower
        race.
        """
        send_after_commit(db, "early@example.com", "Subject", "<p>body</p>")
        email_module.drain_pending_emails()
        assert sent == [], "the message was dispatched while the transaction was still open"

        db.commit()
        email_module.drain_pending_emails()
        assert len(sent) == 1

    def test_the_old_path_still_dispatches_immediately(self, db, sent):
        """
        ⚠️ THE CONTROL THAT PROVES THE TESTS ABOVE CAN FAIL.

        `send_async` is what every caller used before this fix, and it is
        deliberately still public — the after-commit path calls it. Asserting
        that it fires with no transaction involved shows these tests are
        distinguishing the two behaviours rather than passing because nothing
        is ever sent.

        If a future change routes a service caller back through `send_async`,
        D1 is reintroduced and `test_nothing_is_sent_before_the_commit` fails.
        """
        email_module.send_async("immediate@example.com", "Subject", "<p>body</p>")
        email_module.drain_pending_emails()

        assert [to for to, _, _ in sent] == ["immediate@example.com"]

    def test_no_service_caller_uses_the_immediate_path(self):
        """
        The structural half. `service.py` must reach email only through the
        after-commit seam; a stray `send_async` import there is D1 returning,
        and it would be invisible to every behavioural test that happens not to
        cover that one call site.

        ⚠️ IT MATCHES A CALL OR AN IMPORT, NOT A MENTION. The first version
        asserted `"send_async" not in source` and failed immediately —
        `_lookup_for_email_flow`'s docstring names `email.send_async` while
        explaining the timing-attack fix. A prose reference is not a call site,
        and a guard that cannot tell them apart is one somebody deletes.
        """
        import ast
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / "app" / "auth" / "service.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))

        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "app.auth.email"
            for alias in node.names
        }
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        } | {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        assert "send_after_commit" in imported, "service.py no longer uses the after-commit seam"
        assert "send_async" not in imported, (
            "service.py imports the immediate dispatch path again -- finding D1"
        )
        assert "send_async" not in called, "service.py calls send_async directly -- finding D1"

    def test_every_queued_email_passes_the_session(self):
        """
        ⚠️ THE RIGHT NAME IS NOT THE RIGHT CALL, AND THE ABOVE CANNOT TELL.

        The two seams differ by their FIRST parameter -- `send_async(to, subject,
        html_body)` against `send_after_commit(session, to, subject, html_body)`
        -- and both are reached through the same `_queue_email` alias. So a call
        site written for the old seam still names the new one.

        That is not hypothetical. Merging KAN-21 took OUR import line and THEIR
        call site, producing `_queue_email(parent_email, subject, html)` against
        the 4-parameter function: a TypeError on every guardian invite. Git
        reported no conflict, the check above passed, and KAN-21's own new test
        passed too -- it monkeypatched `_queue_email` with a 3-parameter stub, so
        the real callee was never reached. Green suite, dead endpoint.

        Arity is the part that was unguarded, so arity is what this asserts.
        """
        import ast
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / "app" / "auth" / "service.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))

        offenders = [
            (node.lineno, len(node.args))
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_queue_email"
            and (
                len(node.args) != 4
                # Positional, and the session first. A keyword call would still
                # work, but every existing site is positional and one that is
                # not is worth a human look rather than a silent pass.
                or not isinstance(node.args[0], ast.Name)
                or node.args[0].id not in {"db", "session"}
            )
        ]

        assert not offenders, (
            "_queue_email must be called as (session, to, subject, html_body). "
            f"Wrong at service.py lines {[line for line, _ in offenders]} "
            f"(arg counts {[count for _, count in offenders]})."
        )

    def test_a_second_commit_does_not_send_it_again(self, db, sent):
        """
        The outbox is popped, not read. A message left behind would be
        re-delivered by the next commit on the same session — and `get_db`
        commits once per request, so a long-lived session would duplicate.
        """
        send_after_commit(db, "once@example.com", "Subject", "<p>body</p>")
        db.commit()
        db.commit()
        email_module.drain_pending_emails()

        assert len(sent) == 1


class TestD18LoginSendsTheEmailOtp:
    def test_signing_in_to_an_email_otp_account_actually_sends_the_code(
        self, client, db, sent, unique_email
    ):
        """
        ⚠️ THE SCREEN SAID A CODE HAD BEEN SENT AND NOTHING HAD BEEN.

        `_issue_and_send_email_otp` was reachable from enrolment and resend only.
        Phase 1b fixed the missing `resend` button labels on this screen, which
        made the workaround usable — this makes the workaround unnecessary.
        """
        address = unique_email("dispatch")
        _user(db, address, method="email_otp")

        resp = client.post(
            "/api/auth/login",
            json={
                "email": address,
                "password": PASSWORD,
                "turnstile_token": "test-turnstile-token",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "two_factor_required"
        assert resp.json()["method"] == "email_otp"

        email_module.drain_pending_emails()
        assert [to for to, _, _ in sent] == [address], (
            "the challenge screen was reached with no code sent -- finding D18"
        )

    def test_a_totp_account_is_sent_nothing(self, client, db, sent, unique_email):
        """
        The complement, and it matters: a TOTP code is generated on the user's
        own device. Mailing one would be both pointless and a second, weaker
        channel for the same factor.
        """
        address = unique_email("dispatch")
        db_user = _user(db, address)
        # Re-bind for THIS insert only: `_user` clears the binding so the
        # request under test runs unbound like `get_db` does, and
        # `two_factor_enrollment` is owner-scoped so writing it needs one.
        set_current_user_id(db, db_user)
        db.execute(
            text(
                "INSERT INTO two_factor_enrollment "
                "(user_id, method, status, totp_secret_encrypted, confirmed_at) "
                "VALUES (:id, 'totp', 'active', :s, now())"
            ),
            {"id": db_user, "s": b"\x00" * 32},
        )
        db.flush()

        resp = client.post(
            "/api/auth/login",
            json={
                "email": address,
                "password": PASSWORD,
                "turnstile_token": "test-turnstile-token",
            },
        )

        assert resp.json()["method"] == "totp"
        email_module.drain_pending_emails()
        assert sent == []

    def test_a_failed_login_sends_nothing(self, client, db, sent, unique_email):
        """
        D1 and D18 meeting: the OTP is queued inside the login transaction, so a
        wrong password must not mail a code. It also must not mail one to an
        address an attacker merely guessed.
        """
        address = unique_email("dispatch")
        _user(db, address, method="email_otp")

        resp = client.post(
            "/api/auth/login",
            json={
                "email": address,
                "password": "wrong-password",
                "turnstile_token": "test-turnstile-token",
            },
        )

        assert resp.status_code == 401
        email_module.drain_pending_emails()
        assert sent == []
