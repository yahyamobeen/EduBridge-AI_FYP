from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.core.errors import invalid_class_group, validation_error
from app.models.enums import (
    BoardCode,
    LanguageCode,
    MediumCode,
    StudentGroup,
    UserRole,
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


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole

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
        if self.role != UserRole.student:
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
        if self.role != UserRole.student:
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
    onboarding_state: str


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
    password: str


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


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str
    # FIVE states. `plan_selection_pending` is the one a user can reach AFTER
    # being active, when a 14-day trial lapses (prd.md §2.6 MON-4) — the only
    # backward transition in the system. Omitting it does not merely hide a
    # screen: it means paid access is never enforced, because a lapsed student
    # keeps reporting `active` forever.
    onboarding_state: Literal[
        "email_verification_pending",
        "two_factor_enrollment_pending",
        "guardian_link_pending",
        "plan_selection_pending",
        "active",
    ]
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
    enrollment_token: str


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
    code: str
    enrollment_token: str


class TwoFactorConfirmResponse(BaseModel):
    two_factor: TwoFactorOut
    backup_codes: list[str]
    onboarding_state: str
    access_token: str
    expires_in: int


# --- 2FA Challenge (B) -------------------------------------------------------

class TwoFactorVerifyRequest(BaseModel):
    pending_token: str
    code: str
    type: Literal["totp", "email_otp", "backup_code"]


class TwoFactorVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    onboarding_state: str


class TwoFactorResendRequest(BaseModel):
    pending_token: str


class TwoFactorResendResponse(BaseModel):
    sent_to: str
    expires_in: int


# --- Email Verification (C) --------------------------------------------------

class EmailVerifyRequest(BaseModel):
    token: str


class EmailVerifyResponse(BaseModel):
    email_verified: bool
    onboarding_state: str
    access_token: str
    expires_in: int
    enrollment_token: str


class EmailResendRequest(BaseModel):
    email: EmailStr


# --- Password Reset (D) ------------------------------------------------------

class PasswordForgotRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# --- Backup Code Regeneration (E) --------------------------------------------

class BackupCodesRegenerateResponse(BaseModel):
    backup_codes: list[str]
