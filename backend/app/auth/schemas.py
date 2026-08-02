from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import (
    BoardCode,
    LanguageCode,
    MediumCode,
    StudentGroup,
    UserRole,
)

STUDENT_GROUP_BY_CLASS: dict[int, set[str]] = {
    9: {"science", "computer"},
    10: {"science", "computer"},
    11: {"pre_medical", "pre_engineering", "ics"},
    12: {"pre_medical", "pre_engineering", "ics"},
}

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

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        return value

    @field_validator("student_group")
    @classmethod
    def _validate_group(cls, value: StudentGroup | None) -> StudentGroup | None:
        if value is None:
            return value
        return value

    def validate_student_group_for_class(self) -> None:
        if self.role != UserRole.student:
            return
        if self.class_level is None or self.student_group is None:
            raise ValueError("board, class_level and student_group are required for students.")
        allowed = STUDENT_GROUP_BY_CLASS.get(self.class_level, set())
        if self.student_group.value not in allowed:
            raise ValueError(
                f"student_group '{self.student_group.value}' is not valid "
                f"for class {self.class_level}."
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
    token_type: str = "bearer"
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
    status: Literal["pending", "verified", "none"]


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str
    onboarding_state: Literal[
        "email_verification_pending",
        "two_factor_enrollment_pending",
        "guardian_link_pending",
        "active",
    ]
    email_verified: bool
    two_factor: TwoFactorOut
    profile: ProfileOut | None
    guardian: GuardianOut
