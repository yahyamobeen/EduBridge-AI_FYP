from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.core.errors import invalid_class_group, validation_error
from app.models.enums import (
    BoardCode,
    LanguageCode,
    MediumCode,
    RegistrableRole,
    StudentGroup,
)

# Mirrors the `ck_group_matches_class` CHECK constraint in the applied schema so
# a bad pair gets a readable message before the database rejects it. The
# authoritative list of which groups exist per class comes from `subject_group`
# and is served by /reference/enums; this is only the validation guard.
STUDENT_GROUP_BY_CLASS: dict[int, set[str]] = {
    9: {"science", "computer"},
    10: {"science", "computer"},
    11: {"pre_medical", "pre_engineering", "ics"},
    12: {"pre_medical", "pre_engineering", "ics"},
}

# Presentation only. The codes themselves come from the database.
GROUP_LABELS: dict[str, str] = {
    "science": "Science",
    "computer": "Computer Science",
    "pre_medical": "Pre-Medical",
    "pre_engineering": "Pre-Engineering",
    "ics": "ICS",
}


# ============================================================================
# Shared bounds — finding D12.
#
# ⚠️ AN UNBOUNDED STRING THAT REACHES argon2 IS AN UNBOUNDED AMOUNT OF WORK.
#    `LoginRequest.password` was a bare `str` while `RegisterRequest.password`
#    was already 8..128, so the ONE endpoint an unauthenticated caller can hammer
#    accepted a megabyte and hashed it — at deliberately expensive settings
#    (`argon2_time_cost=3`, `memory_cost=65536`). That is a denial of service
#    with no exploit required, just a large POST body.
#
# Tokens and codes are bounded for a related reason: they are looked up by HMAC
# of their own value, so an enormous one costs a hash and a round trip before it
# can be rejected. None of these is a security boundary on its own — the real
# check is always the lookup — they are there so the cost of being wrong is
# bounded.
# ============================================================================

# `generate_opaque_token` is `secrets.token_urlsafe(48)` -> 64 characters. The
# ceiling is generous rather than exact so a future token length change does not
# silently start rejecting valid tokens.
_MAX_TOKEN = 512
# Six digits today (email OTP), six for TOTP, and backup codes are short. Any
# credential a human types is far below this.
_MAX_CODE = 64
# Matches `RegisterRequest.password`. Deliberately the same number in both
# places rather than a stricter one here, because a login must accept every
# password registration was willing to issue.
_MIN_PASSWORD = 8
_MAX_PASSWORD = 128

# The five states, as ONE definition — finding D13. It was a `Literal` on
# `MeResponse` and a bare `str` on four other responses, so four endpoints could
# report a state the client's union does not contain and only `/auth/me` would
# have failed. `plan_selection_pending` is the one a user reaches AFTER being
# active, when a trial lapses (prd.md MON-4) — the only backward transition in
# the system, and the one most likely to be dropped by a hand-written copy.
OnboardingState = Literal[
    "email_verification_pending",
    "two_factor_enrollment_pending",
    "guardian_link_pending",
    "plan_selection_pending",
    "active",
]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=_MIN_PASSWORD, max_length=_MAX_PASSWORD)
    full_name: str = Field(min_length=1, max_length=200)
    # NOT `UserRole` — `admin` is not self-registrable (see RegistrableRole).
    # An `admin` value is rejected by Pydantic, which `_validation_error_response`
    # renders as the ordinary 400 VALIDATION_ERROR envelope with a per-field
    # message, so no endpoint invents a code (tdd.md §7.3).
    role: RegistrableRole
    # Required Cloudflare Turnstile token (register + login only). Cloudflare
    # documents up to 2048 characters, so the ceiling is above that rather than
    # at it.
    turnstile_token: str = Field(min_length=1, max_length=4096)

    board: BoardCode | None = None
    class_level: int | None = Field(default=None, ge=9, le=12)
    student_group: StudentGroup | None = None
    medium: MediumCode | None = None
    language_pref: LanguageCode = LanguageCode.en

    institution: str | None = Field(default=None, max_length=300)

    def validate_required_student_fields(self) -> None:
        """
        Absent student fields are a 400 VALIDATION_ERROR with per-field detail —
        NOT a 422 INVALID_CLASS_GROUP, which means something else entirely
        ("that group is not offered for that class"). A client rendering the
        second for an empty form tells the user their group is wrong when they
        never chose one.
        """
        if self.role != RegistrableRole.student:
            return

        missing = {
            name: "This field is required for students."
            for name, value in (
                ("board", self.board),
                ("class_level", self.class_level),
                ("student_group", self.student_group),
                ("medium", self.medium),
            )
            if value is None
        }
        if missing:
            raise validation_error(
                message="Student registration requires board, class, group and medium.",
                details={"fields": missing},
            )

    def validate_student_group_for_class(self) -> None:
        """
        The pair itself. Mirrors the `ck_group_matches_class` CHECK constraint,
        so a bad pair is rejected with a useful message before the database
        rejects it with an opaque one. Call after
        `validate_required_student_fields`, which guarantees both are present.
        """
        if self.role != RegistrableRole.student:
            return
        if self.class_level is None or self.student_group is None:
            return

        allowed = STUDENT_GROUP_BY_CLASS.get(self.class_level, set())
        if self.student_group.value not in allowed:
            raise invalid_class_group(
                f"'{self.student_group.value}' is not offered for class {self.class_level}."
            )


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    role: str
    onboarding_state: OnboardingState


class BoardOut(BaseModel):
    code: str
    name: str


class GroupOut(BaseModel):
    code: str
    label: str


class EnumsResponse(BaseModel):
    boards: list[BoardOut]
    class_levels: list[int]
    groups_by_class: dict[str, list[GroupOut]]
    mediums: list[str]
    languages: list[str]


class LoginRequest(BaseModel):
    email: EmailStr
    # ⚠️ FINDING D12. This was a bare `str`: the brute-force surface of the whole
    #    system accepted an unbounded body and fed it to argon2.
    #
    # ⚠️ MAXIMUM ONLY, NO MINIMUM, AND THE ASYMMETRY IS DELIBERATE. This field
    #    carries an EXISTING password, so a minimum here is a guess about
    #    history: any account whose password predates a policy change could
    #    never sign in again, and a short typo would answer `400
    #    VALIDATION_ERROR` instead of the `401 UNAUTHENTICATED` that every other
    #    wrong password gets. The denial-of-service this finding is about is
    #    entirely a question of the upper bound.
    password: str = Field(max_length=_MAX_PASSWORD)
    # Required Cloudflare Turnstile token; a missing or empty value is a 400
    # VALIDATION_ERROR like any other missing required field.
    turnstile_token: str = Field(min_length=1, max_length=4096)


class EmailVerificationRequired(BaseModel):
    status: Literal["email_verification_required"]
    email: str


class TwoFactorEnrollmentRequired(BaseModel):
    status: Literal["two_factor_enrollment_required"]
    enrollment_token: str
    expires_in: int


class TwoFactorRequired(BaseModel):
    status: Literal["two_factor_required"]
    pending_token: str
    method: Literal["totp", "email_otp"]
    expires_in: int


LoginResponse = EmailVerificationRequired | TwoFactorEnrollmentRequired | TwoFactorRequired


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- a scheme name, not a secret
    expires_in: int


class TwoFactorOut(BaseModel):
    enabled: bool
    method: Literal["totp", "email_otp"] | None = None


class ProfileOut(BaseModel):
    board: str | None = None
    class_level: int | None = None
    student_group: str | None = None
    medium: str | None = None
    language_pref: str | None = None


class GuardianOut(BaseModel):
    required: bool
    # `null` when there is no link — not the string "none", which the client
    # types as an unexpected value. `revoked` is a real enum member and passes
    # through rather than being flattened into "none".
    status: Literal["pending", "verified", "revoked"] | None = None


# ---------------------------------------------------------------------------
# Guardian gate (RBAC-002). All shapes mirror frontend/lib/api/types.ts
# exactly; the parent email is masked before it leaves the API.
# ---------------------------------------------------------------------------


class GuardianInviteRequest(BaseModel):
    parent_email: EmailStr


class GuardianInviteResponse(BaseModel):
    invite_sent: bool
    parent_email: str
    status: Literal["pending"]


class GuardianConfirmRequest(BaseModel):
    # A parent with two children must say WHICH link is being confirmed, so the
    # token from the email travels in the body (a token is always a body field).
    invite_token: str = Field(min_length=1, max_length=_MAX_TOKEN)


class GuardianConfirmResponse(BaseModel):
    status: Literal["verified"]
    # Nullable because `app_user.full_name` is (initial_schema.sql L103) and
    # `MeResponse` already types it that way. Declared as `str` this raised a
    # ResponseValidationError -> 500 on the SUCCESS path for any student without
    # a name, and the generator dependency then rolled the verification back, so
    # the parent retried into the same 500 forever. The client renders neutral
    # copy instead of a name.
    student_name: str | None = None


class GuardianStatusResponse(BaseModel):
    required: bool
    status: Literal["pending", "verified", "revoked"] | None = None
    parent_email: str | None = None
    invited_at: str | None = None


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str
    # ⚠️ TOP-LEVEL, NOT ONLY INSIDE `profile` — and the omission was a real gap.
    #
    # `20260816200000` moved the column to `app_user` precisely so all four
    # roles could HAVE a stored language, and `PATCH /auth/me` accepts it from
    # all four. But this response reported it only through `profile`, which is
    # `null` for teachers, parents and administrators — so it was WRITABLE BY
    # EVERY ROLE AND READABLE BY ONE. A teacher who chose Urdu had no way to see
    # that they had, and the settings screen showed them English.
    #
    # `profile.language_pref` is kept and now reads the same column, so the two
    # cannot disagree.
    language_pref: LanguageCode
    # FIVE states. `plan_selection_pending` is the one a user can reach AFTER
    # being active, when a 14-day trial lapses (prd.md §2.6 MON-4) — the only
    # backward transition in the system. Omitting it does not merely hide a
    # screen: it means paid access is never enforced, because a lapsed student
    # keeps reporting `active` forever.
    onboarding_state: OnboardingState
    email_verified: bool
    two_factor: TwoFactorOut
    profile: ProfileOut | None
    guardian: GuardianOut


# ============================================================================
# KAN-10b — 2FA Enrolment, Challenge, Email Verification, Password Reset
# ============================================================================


# --- 2FA Enrolment (A) -------------------------------------------------------


class TwoFactorEnrollRequest(BaseModel):
    method: Literal["totp", "email_otp"]
    enrollment_token: str = Field(min_length=1, max_length=_MAX_TOKEN)


class TwoFactorEnrollResponseTOTP(BaseModel):
    method: Literal["totp"]
    secret: str
    otpauth_uri: str
    qr_svg: str


class TwoFactorEnrollResponseEmailOTP(BaseModel):
    method: Literal["email_otp"]
    sent_to: str
    expires_in: int


TwoFactorEnrollResponse = TwoFactorEnrollResponseTOTP | TwoFactorEnrollResponseEmailOTP


class TwoFactorConfirmRequest(BaseModel):
    code: str = Field(min_length=1, max_length=_MAX_CODE)
    enrollment_token: str = Field(min_length=1, max_length=_MAX_TOKEN)


class TwoFactorConfirmResponse(BaseModel):
    two_factor: TwoFactorOut
    backup_codes: list[str]
    onboarding_state: OnboardingState
    access_token: str
    expires_in: int


# --- 2FA Challenge (B) -------------------------------------------------------


class TwoFactorVerifyRequest(BaseModel):
    pending_token: str = Field(min_length=1, max_length=_MAX_TOKEN)
    code: str = Field(min_length=1, max_length=_MAX_CODE)
    type: Literal["totp", "email_otp", "backup_code"]


class TwoFactorVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    onboarding_state: OnboardingState


class TwoFactorResendRequest(BaseModel):
    pending_token: str = Field(min_length=1, max_length=_MAX_TOKEN)


class TwoFactorResendResponse(BaseModel):
    sent_to: str
    expires_in: int


# --- Email Verification (C) --------------------------------------------------


class EmailVerifyRequest(BaseModel):
    token: str = Field(min_length=1, max_length=_MAX_TOKEN)


class EmailVerifyResponse(BaseModel):
    email_verified: bool
    onboarding_state: OnboardingState
    access_token: str
    expires_in: int
    enrollment_token: str


class EmailResendRequest(BaseModel):
    email: EmailStr


# --- Password Reset (D) ------------------------------------------------------


class PasswordForgotRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=_MAX_TOKEN)
    new_password: str = Field(min_length=_MIN_PASSWORD, max_length=_MAX_PASSWORD)


# ============================================================================
# FR-A8 — manage own account (tdd.md §3.1, prd.md:450). Role: ALL FOUR.
# ============================================================================


class PasswordChangeRequest(BaseModel):
    # Both bounds copied from `RegisterRequest.password` and
    # `PasswordResetRequest.new_password` rather than chosen again. A stricter
    # rule here would reject passwords the same system issued, and the client is
    # explicitly not the authority on the policy (ResetPassword.tsx:21-30).
    #
    # `current_password` is bounded for the same reason `new_password` is: it
    # reaches argon2, and an unbounded string is an unbounded amount of hashing
    # (finding D12, which fixes the rest of them).
    # Maximum only, for the reason on `LoginRequest.password`: this is the
    # password the account ALREADY has, and rejecting it for being short would
    # refuse the very users most in need of changing it.
    current_password: str = Field(max_length=_MAX_PASSWORD)
    # The new one is a policy decision, so the minimum applies.
    new_password: str = Field(min_length=_MIN_PASSWORD, max_length=_MAX_PASSWORD)


class MeUpdateRequest(BaseModel):
    """
    PATCH /api/auth/me.

    ⚠️ TWO FIELDS, AND THE OMISSIONS ARE THE POINT. `class_level` is the input
    the parental-consent gate reads, and `board` / `student_group` scope every
    progress, mastery and coverage record ever written for a student — changing
    one silently reinterprets their whole history. `20260816160000:86-94`
    records that none of the three is editable even by its owner, and the
    database enforces that independently of this model.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    # Accepted for EVERY role since 20260816200000 moved the column to
    # `app_user`. It used to live on `student_profile`, so a teacher, parent or
    # administrator had nowhere to store it and always received English mail.
    language_pref: LanguageCode | None = None

    def validate_at_least_one_field(self) -> None:
        """
        An empty body is a 400, not a silent success.

        PATCH with no fields would otherwise return 200 and the current row,
        which is indistinguishable from "your change was saved" to a client that
        posted the wrong shape.
        """
        if self.full_name is None and self.language_pref is None:
            raise validation_error(
                message="Provide at least one field to update.",
                details={"fields": {"full_name": "Provide this or language_pref."}},
            )


class TwoFactorStatusResponse(BaseModel):
    """
    GET /api/auth/2fa/status.

    ⚠️ NO SECRET, NO HASHES, NO COUNTER. `tdd.md:195` says "Never returns the
    secret" and `user-stories.md:97` makes retrieving it a failure criterion.
    The source is `two_factor_status_v`, which was built without those columns
    (20260801120000:236-242) — so the guarantee is structural rather than a
    field this model happens not to declare.
    """

    enabled: bool
    method: Literal["totp", "email_otp"] | None = None
    locked_until: str | None = None
    # From `unused_backup_codes` on the view. `user-stories.md:93` requires the
    # remaining count be visible "without regenerating"; it is not in tdd.md
    # §3.1, so that row is amended in the same change.
    backup_codes_remaining: int = 0
