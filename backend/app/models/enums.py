from enum import Enum


class UserRole(str, Enum):
    student = "student"
    teacher = "teacher"
    parent = "parent"
    admin = "admin"


class RegistrableRole(str, Enum):
    """
    The roles `POST /auth/register` accepts. DELIBERATELY EXCLUDES `admin`.

    A separate type rather than a validator on `UserRole`, because this way the
    restriction lands in the generated OpenAPI schema — a client reading the
    interface description sees three roles, not four with one that always fails.
    The frontend already models it the same way (`Exclude<Role, 'admin'>` in
    `lib/api/types.ts`).

    Registering an admin used to reach `active` in a single request: the student
    validators return early for a non-student, the role chain in `register()`
    has no `else`, and `derive_onboarding_state` skips both the guardian and the
    subscription rules — so nothing downstream objected. `app.is_admin()` then
    opened six read policies.

    Narrowing the type is the FIRST of two layers. The second is the
    `app_user_insert` policy, which refuses an admin row to `app_backend`
    outright. Neither is sufficient alone: a validator can be bypassed by a new
    endpoint that forgets it, and the policy cannot produce a readable error.
    """

    student = "student"
    teacher = "teacher"
    parent = "parent"


class UserStatus(str, Enum):
    active = "active"
    suspended = "suspended"
    deleted = "deleted"


class BoardCode(str, Enum):
    pctb = "PCTB"
    stbb = "STBB"


class MediumCode(str, Enum):
    en = "en"
    ur = "ur"


class LanguageCode(str, Enum):
    en = "en"
    ur = "ur"
    roman_ur = "roman_ur"


class StudentGroup(str, Enum):
    science = "science"
    computer = "computer"
    pre_medical = "pre_medical"
    pre_engineering = "pre_engineering"
    ics = "ics"


class ContentStrategy(str, Enum):
    branch_a_english_source = "branch_a_english_source"
    branch_b_urdu_native = "branch_b_urdu_native"
    religious_verbatim = "religious_verbatim"
    english_language = "english_language"


class GuardianStatus(str, Enum):
    pending = "pending"
    verified = "verified"
    revoked = "revoked"


class TokenKind(str, Enum):
    refresh = "refresh"
    guardian_invite = "guardian_invite"
    email_verify = "email_verify"
    password_reset = "password_reset"  # noqa: S105 -- an enum member, not a secret
    two_factor_email_otp = "two_factor_email_otp"
    # Two DISTINCT kinds on purpose. `two_factor_pending` (~5 min) is exchanged
    # by /2fa/verify for a full session; `two_factor_enrollment` (~15 min) is
    # only good for /2fa/enroll and /2fa/confirm. Storing both under the same
    # kind — as this originally did — left /2fa/verify unable to reject the
    # longer-lived one (migration 20260802140100).
    two_factor_pending = "two_factor_pending"
    two_factor_enrollment = "two_factor_enrollment"


class TwoFactorMethod(str, Enum):
    totp = "totp"
    email_otp = "email_otp"


class TwoFactorStatus(str, Enum):
    pending = "pending"
    active = "active"
    disabled = "disabled"


class SpaceOwnerRole(str, Enum):
    teacher = "teacher"
    parent = "parent"


class SpaceStatus(str, Enum):
    active = "active"
    archived = "archived"
