"""
Email locale and template behaviour. No database, no network.

WHAT THIS GUARDS. Every verification and reset link was built as
`{base}/en/...` regardless of who was receiving it, in a product whose premise
is Urdu-first (prd.md §3.1) and which stores `language_pref` on every ACCOUNT
(on every student only, until 20260816200000 moved the column to `app_user`).
An Urdu-medium student in Lahore got an English page from the one email that
decides whether they can use the account at all.
"""

import pytest

from app.auth.email_templates import (
    build_guardian_invite_url,
    build_password_reset_url,
    build_verification_url,
    password_reset_email,
    two_factor_otp_email,
    verification_email,
    web_locale,
)


class TestWebLocale:
    @pytest.mark.parametrize(
        ("stored", "expected"),
        [("en", "en"), ("ur", "ur"), ("roman_ur", "ur-Latn")],
    )
    def test_maps_the_stored_language_code_to_the_web_locale(self, stored, expected):
        # `roman_ur` is NOT a valid BCP-47 tag, which is why the web spells it
        # ur-Latn (tdd.md §3.10). This function is the only place that
        # translation happens, so the two spellings cannot drift.
        assert web_locale(stored) == expected

    def test_missing_language_falls_back_to_english(self):
        # ⚠️ THE MEANING OF `None` CHANGED IN 20260816200000, and the fallback
        # deliberately did not. It used to arrive for every teacher, parent and
        # administrator, because `language_pref` lived on `student_profile` —
        # so the fallback WAS the behaviour for three roles out of four, and
        # FR-A8's "the stored preference governs outgoing email" was unmeetable
        # for them. The column is on `app_user` now and NOT NULL, so `None`
        # means no user row at all. Falling back still beats guessing.
        assert web_locale(None) == "en"

    def test_an_unknown_code_falls_back_rather_than_producing_a_broken_url(self):
        assert web_locale("kl") == "en"


class TestLinkBuilding:
    @pytest.mark.parametrize(
        "builder",
        [build_verification_url, build_password_reset_url, build_guardian_invite_url],
    )
    @pytest.mark.parametrize("locale", ["en", "ur", "ur-Latn"])
    def test_every_link_carries_the_recipients_locale(self, builder, locale):
        url = builder("tok-123", locale)
        assert f"/{locale}/" in url
        assert url.endswith("token=tok-123")

    def test_the_default_is_english_not_a_missing_segment(self):
        # A locale-less path would 404 on the frontend, which routes every page
        # under /[locale]/.
        assert "/en/" in build_verification_url("t")


class TestTemplates:
    @pytest.mark.parametrize(
        ("locale", "direction"), [("en", "ltr"), ("ur-Latn", "ltr"), ("ur", "rtl")]
    )
    def test_urdu_renders_right_to_left(self, locale, direction):
        _, html = verification_email("https://x/en/verify-email?token=t", locale)
        assert f'dir="{direction}"' in html
        assert f'lang="{locale}"' in html

    def test_the_otp_is_not_in_the_subject_line(self):
        """
        Subjects appear on lock screens and in notification banners. A one-time
        code there is readable by anyone holding the phone — which, on the
        shared devices prd.md §3.1 describes, is the expected case rather than
        the unlucky one.
        """
        subject, html = two_factor_otp_email("123456")

        assert "123456" not in subject
        assert "123456" in html

    @pytest.mark.parametrize("template", [verification_email, password_reset_email])
    def test_the_link_appears_in_the_body(self, template):
        url = "https://app.example.com/ur/reset-password?token=abc"
        _, html = template(url, "ur")
        assert url in html
