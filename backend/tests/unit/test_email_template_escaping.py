"""
Finding C3 — user-supplied text in an email template.

`student_name` is `app_user.full_name`: bounded in LENGTH by
`RegisterRequest`/`MeUpdateRequest` (200 characters) and unrestricted in
CHARACTERS. It is the only user-controlled interpolation anywhere in
`email_templates.py`.

⚠️ WHY IT STOPPED BEING THEORETICAL. C3 sat latent for as long as
`guardian_invite_email` had no caller — the register recorded it as "latent
because of A10". Two things landed together and removed both halves of that
excuse: KAN-21 wired the invite, and this branch shipped `PATCH /auth/me`, which
lets a student rewrite their own `full_name` whenever they like. So the payload
is attacker-EDITABLE, not merely attacker-supplied, and the delivery target is a
parent's inbox reached from a domain this project has verified.

The two escaping rules differ by destination, and conflating them is how this
gets "fixed" wrongly:

* **HTML** (the body, and `<title>` inside `_wrap`) needs escaping.
* **The subject header** does not — escaping it just shows a parent `&lt;` where
  their child's name belongs. What a header needs is its newlines removed.
"""

import pytest

from app.auth.email_templates import guardian_invite_email

URL = "https://app.example.com/en/guardian/confirm?token=abc123"

# Each is a real delivery mechanism, not a decorative sample.
PAYLOADS = [
    pytest.param("<script>alert(1)</script>", id="script tag"),
    pytest.param('<a href="https://evil.example">Verify your account</a>', id="phishing anchor"),
    pytest.param('<img src=x onerror="alert(1)">', id="event handler"),
    pytest.param("</p><h1>Your account is suspended</h1><p>", id="tag breakout"),
]


class TestTheBodyIsNotInjectable:
    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_markup_arrives_as_text(self, payload):
        _, html = guardian_invite_email(URL, payload)

        assert payload not in html, "the raw payload reached the parent's inbox as markup"
        assert "&lt;" in html

    def test_the_name_is_still_readable(self):
        """
        Escaped, not deleted. A parent must still see whose invitation this is,
        or the message is useless and someone will "fix" it by unescaping.
        """
        _, html = guardian_invite_email(URL, "Ayesha Khan")

        assert "Ayesha Khan" in html

    def test_an_apostrophe_is_not_mangled(self):
        """
        ⚠️ THE OVER-ESCAPING BUG, WHICH IS ALSO A BUG.

        `html.escape` defaults to `quote=True`. Nothing here lands in an
        attribute, so quoting buys nothing and costs a real name: a parent called
        O'Brien would be shown `O&#x27;Brien` by their mail client. That looks
        broken, and code that looks broken gets reverted.
        """
        _, html = guardian_invite_email(URL, "Aisha O'Brien")

        assert "O'Brien" in html
        assert "&#x27;" not in html


class TestTheTitleIsNotInjectable:
    """
    The subject is passed to `_wrap` as the document title, so it reaches HTML
    even though a subject is not HTML. Escaping lives in `_wrap` rather than in
    each template, so a template author cannot forget it.
    """

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_markup_cannot_escape_the_title_element(self, payload):
        _, html = guardian_invite_email(URL, payload)

        title = html.split("<title>")[1].split("</title>")[0]
        assert "<" not in title, f"markup survived inside <title>: {title!r}"


class TestTheSubjectHeader:
    def test_newlines_are_removed(self):
        """
        A CR or LF ends one header and starts the next, which is how a name
        becomes an extra recipient. `html.escape` does nothing about this — it is
        a separate defect at the same call site.
        """
        subject, _ = guardian_invite_email(URL, "Ayesha\r\nBcc: attacker@evil.example")

        assert "\r" not in subject
        assert "\n" not in subject

    def test_it_is_not_html_escaped(self):
        """
        The inverse guard. A subject line is plain text in every mail client, so
        entity-escaping it would show a parent `Aisha O&#x27;Brien` in their
        inbox list. Correct escaping is per-destination, not everywhere.
        """
        subject, _ = guardian_invite_email(URL, "Aisha O'Brien")

        assert "Aisha O'Brien" in subject
        assert "&#x27;" not in subject
        assert "&amp;" not in subject

    def test_the_name_is_still_there(self):
        subject, _ = guardian_invite_email(URL, "Ayesha Khan")

        assert subject.startswith("Ayesha Khan invited you")


class TestTheLinkSurvives:
    """
    Escaping must not break the thing the email exists to deliver. The URL is
    built from an opaque token and a validated locale, so it carries no user
    input and must arrive intact.
    """

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_the_confirm_url_is_intact(self, payload):
        _, html = guardian_invite_email(URL, payload)

        assert URL in html
