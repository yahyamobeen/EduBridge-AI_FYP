import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import gate
from app.auth.backup_codes import generate_backup_codes, hash_backup_code, verify_backup_code
from app.auth.email import send_async as _queue_email
from app.auth.email_templates import (
    build_password_reset_url,
    build_verification_url,
    password_reset_email,
    two_factor_otp_email,
    verification_email,
    web_locale,
)
from app.auth.onboarding import derive_onboarding_state
from app.auth.schemas import (
    GROUP_LABELS,
    EmailResendRequest,
    EmailVerifyRequest,
    GuardianConfirmRequest,
    GuardianInviteRequest,
    LoginRequest,
    MeUpdateRequest,
    PasswordChangeRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RegisterRequest,
    TwoFactorConfirmRequest,
    TwoFactorEnrollRequest,
    TwoFactorResendRequest,
    TwoFactorVerifyRequest,
)
from app.auth.security import create_access_token, hash_password, hash_token, verify_password
from app.auth.tokens import (
    RefreshTokenReuseError,
    find_token,
    issue_challenge_token,
    issue_guardian_invite_token,
    issue_preauth_token,
    issue_refresh_token,
    revoke_refresh_family,
    revoke_user_tokens,
    rotate_refresh_token,
)
from app.auth.totp import (
    build_otpauth_uri,
    decrypt_secret,
    encrypt_secret,
    generate_qr_svg,
    generate_totp_secret,
    verify_totp_code,
)
from app.auth.turnstile import verify_turnstile_token
from app.core.config import get_settings
from app.core.db import set_current_user_id
from app.core.errors import (
    AppError,
    captcha_failed,
    email_already_registered,
    guardian_already_linked,
    guardian_not_found,
    invalid_token,
    pending_token_expired,
    self_link_forbidden,
    token_expired,
    two_factor_invalid,
    two_factor_locked,
    unauthenticated,
    validation_error,
)
from app.core.ratelimit import (
    TWO_FA_CONFIRM_USER_LIMIT,
    TWO_FA_ENROLL_USER_LIMIT,
    TWO_FA_RESEND_USER_LIMIT,
    TWO_FA_VERIFY_USER_LIMIT,
    enforce_subject,
)
from app.models.enums import RegistrableRole, TokenKind

# The one plan in v1, seeded by 20260802120000_subscriptions_and_oauth.sql and
# referenced by subscription.plan_code.
_DEFAULT_PLAN_CODE = "standard"

# One hour for both email links (tdd.md §3.1). Long enough for a parent to get
# to a shared computer, short enough that a forwarded mail goes stale.
_EMAIL_LINK_TTL_SECONDS = 3600

# Ten minutes for an email OTP, matching the code's own copy.
_EMAIL_OTP_TTL_SECONDS = 600


def register(db: Session, payload: RegisterRequest) -> dict:
    # Captcha BEFORE any schema/DB work and before issuing anything: a client
    # asserting "I solved the captcha" is never trusted alone, and a rejected
    # token must waste no account machinery and, especially, no hash.
    if not verify_turnstile_token(payload.turnstile_token):
        raise captcha_failed()

    # Two DIFFERENT failures, two different codes. Absent student fields are a
    # 400 VALIDATION_ERROR with per-field detail; a class/group pair that does
    # not exist is a 422 INVALID_CLASS_GROUP. Collapsing both into the second
    # tells a user who submitted an empty form that "that group is not offered
    # for the class you selected", which is not what happened.
    payload.validate_required_student_fields()
    payload.validate_student_group_for_class()

    new_id = uuid4()

    # REQUIRED, despite looking odd on an unauthenticated endpoint. `app_user`
    # itself is now owner-scoped -- `app_user_insert` is
    # `WITH CHECK (id = app.current_user_id() AND role <> 'admin')` -- and every
    # profile policy is `WITH CHECK (user_id = app.current_user_id())`, as is
    # `subscription_owner`. Without binding the id we are about to create, RLS
    # refuses the app_user row itself and every insert below it.
    #
    # The comment here previously said `app_user_insert` was `WITH CHECK (true)`.
    # That was accurate for 20260801120100 and stopped being true at
    # 20260802150000, which reconciled it to the owner-scoped form. Corrected
    # while adding the `role <> 'admin'` clause.
    set_current_user_id(db, new_id)

    try:
        db.execute(
            text(
                "INSERT INTO app_user "
                "(id, email, password_hash, role, status, full_name, language_pref) "
                "VALUES (:id, :email, :pwhash, :role, 'active', :full_name, :lang)"
            ),
            {
                "id": new_id,
                "email": str(payload.email).lower(),
                "pwhash": hash_password(payload.password),
                "role": payload.role.value,
                "full_name": payload.full_name,
                # `RegisterRequest.language_pref` was always accepted for every
                # role and, before 20260816200000, only ever STORED for
                # students. A teacher's answer was read once for the
                # verification email below and then thrown away. INSERT on
                # app_user is still table-wide (only UPDATE narrowed in
                # 20260816160000), so this needs no additional grant.
                "lang": payload.language_pref.value,
            },
        )
        db.flush()
    except IntegrityError as exc:
        if isinstance(exc.orig, UniqueViolation):
            raise email_already_registered() from exc
        raise

    if payload.role == RegistrableRole.student:
        db.execute(
            text(
                "INSERT INTO student_profile "
                "(user_id, board, class_level, student_group, medium, language_pref) "
                "VALUES (:user_id, :board, :class_level, :group, :medium, :lang)"
            ),
            {
                "user_id": new_id,
                "board": payload.board.value,
                "class_level": payload.class_level,
                "group": payload.student_group.value,
                "medium": payload.medium.value,
                "lang": payload.language_pref.value,
            },
        )
        # Starts the 14-day trial. Without this row the derivation below fails
        # CLOSED (prd.md MON-2), so every student would land on plan selection
        # the moment they clear the guardian gate, having never had a trial.
        #
        # `status` and `trial_ends_at` are left to their schema defaults on
        # purpose: `trial_ends_at DEFAULT (now() + interval '14 days')` is the
        # single definition of trial length, and a second copy of "14" in
        # Python is exactly how the two drift apart.
        db.execute(
            text("INSERT INTO subscription (user_id, plan_code) VALUES (:user_id, :plan)"),
            {"user_id": new_id, "plan": _DEFAULT_PLAN_CODE},
        )
    elif payload.role == RegistrableRole.teacher:
        db.execute(
            text(
                "INSERT INTO teacher_profile (user_id, institution) VALUES (:user_id, :institution)"
            ),
            {"user_id": new_id, "institution": payload.institution},
        )
    elif payload.role == RegistrableRole.parent:
        db.execute(
            text("INSERT INTO parent_profile (user_id) VALUES (:user_id)"),
            {"user_id": new_id},
        )

    # SEND THE VERIFICATION EMAIL. Registration returned
    # `email_verification_pending` and issued no token and no mail, so the
    # client showed "check your email" for a message that was never sent. The
    # only way to receive the first one was to press Resend on a screen that
    # exists to say the first one is already on its way.
    #
    # The locale comes off the request rather than a read-back: this is the one
    # moment we know it without asking, and `student_profile` is the only place
    # it is stored, so a teacher or parent has none at all.
    email = str(payload.email).lower()
    locale = web_locale(payload.language_pref.value)
    token = issue_preauth_token(
        db, new_id, kind=TokenKind.email_verify, ttl_seconds=_EMAIL_LINK_TTL_SECONDS
    )
    subject, body = verification_email(build_verification_url(token, locale), locale)
    _queue_email(email, subject, body)

    return {
        "user_id": str(new_id),
        "email": email,
        "role": payload.role.value,
        "onboarding_state": "email_verification_pending",
    }


def enums(db: Session) -> dict:
    """
    Reference data for the signup form.

    `groups_by_class` is DERIVED from `subject_group`, which carries the seeded
    subject-to-group mappings, rather than hardcoded. A literal here would let
    the seed and the API drift apart silently, and the test guarding it would
    only ever assert the literal against itself.
    """
    boards = db.execute(text("SELECT code, name FROM board ORDER BY code")).mappings().all()
    class_levels = (
        db.execute(text("SELECT DISTINCT level FROM class_level ORDER BY level")).scalars().all()
    )

    pairs = db.execute(
        text(
            "SELECT DISTINCT cl.level, sg.student_group "
            "FROM subject_group sg "
            "JOIN subject s      ON s.id  = sg.subject_id "
            "JOIN class_level cl ON cl.id = s.class_level_id "
            "ORDER BY cl.level, sg.student_group"
        )
    ).all()

    groups_by_class: dict[str, list[dict[str, str]]] = {}
    for level, group in pairs:
        code = str(group)
        # The set of codes is data and comes from the database; the labels are
        # presentation and stay in the application.
        groups_by_class.setdefault(str(level), []).append(
            {"code": code, "label": GROUP_LABELS.get(code, code)}
        )

    return {
        "boards": [{"code": b.code, "name": b.name} for b in boards],
        "class_levels": list(class_levels),
        "groups_by_class": groups_by_class,
        "mediums": ["en", "ur"],
        "languages": ["en", "ur", "roman_ur"],
    }


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """
    A real argon2 hash to verify against when the account does not exist.

    Without it, `login` short-circuits on an unknown email and never runs the
    hash, so a missing account answers in about a millisecond while a wrong
    password pays the full argon2 cost. That gap is measurable from anywhere and
    turns the login form into an account-enumeration oracle — which tdd.md §6.11
    forbids "by body, status code, OR TIMING". Computed once at first use with
    the configured parameters, so it costs the same as a real verify.
    """
    return hash_password("edubridge-dummy-password-for-constant-time-login")


def login(db: Session, payload: LoginRequest, *, admin_portal: bool = False) -> dict:
    """
    A CORRECT password never returns a session — it returns 200 with a `status`
    discriminator saying which step comes next (tdd.md §3.1). Only a WRONG
    password is a failure, and its message must not reveal whether the address
    exists.

    This runs pre-authentication, so the lookup goes through the narrow
    SECURITY DEFINER function rather than an RLS-bypassing connection: there is
    no `app.current_user_id()` yet to satisfy `app_user_self_read` with.

    `admin_portal` selects WHICH SET OF ROLES may authenticate here, and it is
    the only difference between the two login endpoints (prd.md FR-A2a). ONE
    function, deliberately, rather than a second copy for administrators: the
    constant-time dummy-hash branch, the lockout ladder, the e-mail-verification
    branch and the two challenge-token branches below are the whole security
    argument of this path, and a copy would drift from them. That is the same
    reasoning that produced `onboarding_state_for` after the state machine had
    been reimplemented four times.
    """
    # 1) CAPTCHA, FIRST — before the lookup and before the dummy-hash branch,
    #    so the captcha is a constant cost for every account and never tells
    #    a caller whether an address exists (tdd.md §6.11, timing side).
    if not verify_turnstile_token(payload.turnstile_token):
        raise captcha_failed()

    # 2) ... then the existing lookup.
    row = (
        db.execute(
            text(
                "SELECT id, password_hash, status, email_verified_at, role "
                "FROM app.lookup_user_for_login(:email)"
            ),
            {"email": str(payload.email).lower()},
        )
        .mappings()
        .one_or_none()
    )

    # Deliberately NOT short-circuited: both branches perform one argon2 verify.
    if row is None:
        verify_password(payload.password, _dummy_password_hash())
        raise unauthenticated("Incorrect email or password.")
    if not verify_password(payload.password, row["password_hash"]):
        raise unauthenticated("Incorrect email or password.")
    if str(row["status"]) != "active":
        raise unauthenticated("Incorrect email or password.")

    # WHICH DOOR THIS ACCOUNT MAY USE (prd.md FR-A2a). Administrators do not
    # authenticate at the public endpoint, and nobody else authenticates at the
    # administrator one.
    #
    # THE SAME 401, WITH THE SAME BODY, AS A WRONG PASSWORD — deliberately, and
    # this is the whole point of the check rather than an implementation detail.
    # A distinguishable answer (403, or any different message) would turn the
    # public login form into an administrator-enumeration oracle: submit an
    # address, read the status code, learn whether it is an admin account. That
    # is the enumeration-resistance rule in tdd.md §6.11, which forbids
    # revealing account facts "by body, status code, OR TIMING" — and the timing
    # side holds too, because the argon2 verify above has already run either way.
    #
    # ⚠️ THE UNLISTED URL IS NOT WHAT ENFORCES THIS. The path is an unlisted
    #    door; these two lines are the lock. Anyone who learns the path still
    #    cannot sign in without administrator credentials, and anyone who has
    #    administrator credentials still cannot use them at /auth/login.
    #
    # Written as one exclusive-or rather than two `if`s so the rule cannot be
    # half-changed: the endpoint and the role must agree, in both directions.
    if (str(row["role"]) == "admin") != admin_portal:
        raise unauthenticated("Incorrect email or password.")

    user_id = row["id"]

    # THROUGH THE SECURITY DEFINER FUNCTION, not a plain SELECT. Login has no
    # bound user, so reading `two_factor_enrollment` directly matched
    # `two_factor_enrollment_owner` against an unset `app.current_user_id()` and
    # returned zero rows for EVERY account — which this code then read as "no
    # second factor yet". A user with active TOTP was handed an enrolment token,
    # `/2fa/enroll` refused because its own read happens after binding and saw
    # the truth, and the account became unreachable with the correct password
    # and the correct authenticator. The lockout check below was dead for the
    # same reason.
    twofa = (
        db.execute(
            text("SELECT method, status, locked_until FROM app.lookup_2fa_for_login(:uid)"),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )

    # Checked only AFTER the password is verified, so a wrong password against a
    # locked account still answers 401 and reveals nothing about the account.
    if twofa is not None and twofa["locked_until"] is not None:
        locked_until = twofa["locked_until"]
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
        if locked_until > datetime.now(UTC):
            raise two_factor_locked(locked_until.isoformat())

    if row["email_verified_at"] is None:
        # Masked: this is reachable with a correct password but no session. The
        # client keeps the unmasked address the user typed, because /email/resend
        # cannot act on a masked one.
        return {"status": "email_verification_required", "email": _mask_email(str(payload.email))}

    settings = get_settings()
    if twofa is None or str(twofa["status"]) != "active":
        token = issue_challenge_token(
            db,
            user_id,
            kind=TokenKind.two_factor_enrollment,
            ttl_seconds=settings.enrollment_token_ttl_seconds,
        )
        return {
            "status": "two_factor_enrollment_required",
            "enrollment_token": token,
            "expires_in": settings.enrollment_token_ttl_seconds,
        }

    token = issue_challenge_token(
        db,
        user_id,
        kind=TokenKind.two_factor_pending,
        ttl_seconds=settings.pending_token_ttl_seconds,
    )
    return {
        "status": "two_factor_required",
        "pending_token": token,
        "method": str(twofa["method"]),
        "expires_in": settings.pending_token_ttl_seconds,
    }


def refresh(db: Session, refresh_token: str) -> dict:
    try:
        rotated = rotate_refresh_token(db, refresh_token)
    except RefreshTokenReuseError as reuse:
        # Rotation means a token is valid exactly once, so a second use means
        # two parties hold it. Kill the whole family rather than answering 401
        # and leaving the thief with a working chain.
        revoke_refresh_family(db, reuse.user_id)
        # COMMIT BEFORE RAISING. The 401 below propagates out through `get_db`,
        # which rolls the session back on any exception — so without this the
        # revocation is undone by the very response that reports the reuse, and
        # the stolen chain keeps working. A test caught exactly that.
        db.commit()
        raise unauthenticated("Invalid or expired refresh token.") from None

    if rotated is None:
        raise unauthenticated("Invalid or expired refresh token.")

    new_plain, _ = rotated
    stored = find_token(db, new_plain)
    if stored is None:
        raise unauthenticated("Invalid or expired refresh token.")

    access_token, expires_in = create_access_token(stored.user_id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "refresh_token": new_plain,
    }


def logout(db: Session, user_id: UUID) -> None:
    revoke_user_tokens(db, user_id, kind=TokenKind.refresh.value)


# ----------------------------------------------------------------------------
# Identity
# ----------------------------------------------------------------------------

_ME_QUERY = text(
    """
    -- `language_pref` comes from `u`, NOT from `sp`. It moved to app_user in
    -- 20260816200000 so that FR-A8 could reach the three roles without a
    -- student_profile row; `student_profile.language_pref` still exists and is
    -- deliberately read by nothing. Sourcing it here keeps ONE value behind
    -- both `MeResponse.profile.language_pref` and outgoing email, so the
    -- settings screen cannot show one thing while mail is sent in another.
    SELECT u.id, u.email, u.full_name, u.role, u.email_verified_at, u.language_pref,
           sp.board, sp.class_level, sp.student_group, sp.medium,
           tf.method  AS tf_method,
           tf.status  AS tf_status,
           gl.status  AS guardian_status,
           sub.status AS subscription_status
      FROM app_user u
      LEFT JOIN student_profile sp       ON sp.user_id  = u.id
      LEFT JOIN two_factor_enrollment tf ON tf.user_id  = u.id
      LEFT JOIN subscription sub         ON sub.user_id = u.id
      -- A student may have more than one guardian_link row, so this picks one
      -- representative with 'verified' winning. A plain LEFT JOIN would
      -- duplicate the user row once per parent.
      LEFT JOIN LATERAL (
            SELECT g.status
              FROM guardian_link g
             WHERE g.student_id = u.id
             ORDER BY (g.status = 'verified') DESC, g.created_at DESC
             LIMIT 1
      ) gl ON true
     WHERE u.id = :uid AND u.deleted_at IS NULL
    """
)


def onboarding_state_for(
    db: Session, user_id: UUID, *, two_factor_active: bool | None = None
) -> str:
    """
    The single derivation used by every endpoint that reports `onboarding_state`.

    THIS EXISTS BECAUSE THERE WERE FOUR COPIES. `/2fa/confirm`, `/2fa/verify` and
    `/email/verify` each rebuilt the derivation inline, each carrying its own
    `class_level in (9, 10)` and its own guardian lookup. That is one field the
    frontend routes on being computed four ways: the copies did NOT apply the
    fail-closed rule in `gate.py`, so a student whose `student_profile` row is
    missing or unreadable would have been told `active` by `/email/verify` and
    `guardian_link_pending` by `/auth/me` in the same session.

    `two_factor_active` overrides what the row says. The 2FA endpoints call this
    in the same transaction that activates the enrolment, and an override is
    honest about that ordering — re-reading a row we just wrote in order to
    learn what we wrote is the kind of thing that silently breaks when the
    binding or the isolation level changes.
    """
    row = db.execute(_ME_QUERY, {"uid": user_id}).mappings().one_or_none()
    if row is None:
        raise unauthenticated()

    is_student = str(row["role"]) == "student"
    resolved_2fa = (
        two_factor_active
        if two_factor_active is not None
        else (row["tf_status"] is not None and str(row["tf_status"]) == "active")
    )
    return derive_onboarding_state(
        email_verified=row["email_verified_at"] is not None,
        two_factor_active=resolved_2fa,
        is_student=is_student,
        guardian_required=gate.guardian_required(
            is_student=is_student, class_level=row["class_level"]
        ),
        guardian_status=(
            str(row["guardian_status"]) if row["guardian_status"] is not None else None
        ),
        subscription_status=(
            str(row["subscription_status"]) if row["subscription_status"] is not None else None
        ),
    )


def me(db: Session, user_id: UUID) -> dict:
    """
    Identity plus the derived `onboarding_state`.

    ONE query, not five. The frontend guard calls this on every dashboard mount
    and re-evaluates rather than caching — the state is non-monotonic — so these
    round trips sit on the hot path.
    """
    row = db.execute(_ME_QUERY, {"uid": user_id}).mappings().one_or_none()
    if row is None:
        raise unauthenticated()

    is_student = str(row["role"]) == "student"
    class_level = row["class_level"]

    # prd.md §4.3: Classes 9-10 only. Delegated to gate.py so `me()` and
    # GET /api/auth/guardian/status cannot drift apart on this rule.
    guardian_required = gate.guardian_required(is_student=is_student, class_level=class_level)
    # `null`, not the string "none": the contract types this as
    # `GuardianStatus | null`, and `revoked` is a real value that has to pass
    # through rather than being flattened away.
    guardian_status = str(row["guardian_status"]) if row["guardian_status"] is not None else None

    two_factor_active = row["tf_status"] is not None and str(row["tf_status"]) == "active"
    subscription_status = (
        str(row["subscription_status"]) if row["subscription_status"] is not None else None
    )

    onboarding_state = derive_onboarding_state(
        email_verified=row["email_verified_at"] is not None,
        two_factor_active=two_factor_active,
        is_student=is_student,
        guardian_required=guardian_required,
        guardian_status=guardian_status,
        subscription_status=subscription_status,
    )

    profile = None
    if is_student and row["board"] is not None:
        profile = {
            "board": str(row["board"]),
            "class_level": class_level,
            "student_group": str(row["student_group"]),
            "medium": str(row["medium"]),
            "language_pref": str(row["language_pref"]),
        }

    return {
        "user_id": str(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"],
        "role": str(row["role"]),
        "onboarding_state": onboarding_state,
        "email_verified": row["email_verified_at"] is not None,
        "two_factor": {
            "enabled": two_factor_active,
            "method": str(row["tf_method"]) if two_factor_active else None,
        },
        "profile": profile,
        "guardian": {"required": guardian_required, "status": guardian_status},
    }


# ----------------------------------------------------------------------------
# FR-A8 — manage own account (tdd.md §3.1). Every route below is authenticated,
# so the session is already bound and every statement runs under the ordinary
# owner-scoped policies. None of them touches `get_service_db`.
# ----------------------------------------------------------------------------


def change_password(db: Session, user_id: UUID, payload: PasswordChangeRequest) -> int:
    """
    POST /api/auth/password/change. Returns the number of sessions ended.

    ⚠️ 401 UNAUTHENTICATED FOR A WRONG CURRENT PASSWORD, NOT A NEW CODE.
    `tdd.md:1053` makes UNAUTHENTICATED "also the only response meaning 'wrong
    password'", and `tdd.md:1074` says "No endpoint invents a code." A
    WRONG_PASSWORD code would reach the client as an unrecognised string and
    render as "something went wrong".

    ⚠️ THAT MAKES THIS THE ONLY ROUTE WHERE BOTH MEANINGS OF 401 ARE LIVE AT
    ONCE — expired token and wrong password — which is why the client wrapper
    must pass `noRetry: true`. Without it every mistyped password fires a token
    refresh (`REFRESHABLE_401_CODES` in errors.ts).

    READING `password_hash` NEEDS NO PRIVILEGED PATH. §2.2 revoked UPDATE and
    never SELECT, so `app_user_self_read` still serves it to the bound user.
    After the column-grant work the instinct is to reach for a function for
    every `app_user` access; here that would move an argon2 comparison inside
    something running as the database owner, for no gain.
    """
    row = (
        db.execute(
            text("SELECT password_hash FROM app_user WHERE id = :uid AND deleted_at IS NULL"),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    # `authenticated` already proved this row exists and is active; reaching
    # here means it stopped being true mid-request.
    if row is None:
        raise unauthenticated()

    if not verify_password(payload.current_password, row["password_hash"]):
        raise unauthenticated("Incorrect password.")

    # The function takes NO user identifier — it acts on `app.current_user_id()`,
    # which `authenticated` bound. See 20260816210000 for why that is stronger
    # than passing one and checking it.
    result = (
        db.execute(
            text("SELECT changed, tokens_revoked FROM app.change_password(:new_hash)"),
            {"new_hash": hash_password(payload.new_password)},
        )
        .mappings()
        .one()
    )
    # ⚠️ `changed` IS CHECKED, and it is not ceremony. `tokens_revoked` is 0 for
    #    a legitimate change by a user with no live sessions, so the count
    #    cannot carry this signal — that is why the function returns two fields.
    if not result["changed"]:
        raise unauthenticated()

    db.execute(
        text(
            "INSERT INTO audit_log (actor_id, action, target) "
            "VALUES (:uid, 'password_changed', 'app_user')"
        ),
        {"uid": user_id},
    )
    # NO db.commit(). `authenticated` commits on success (dependencies.py:84);
    # committing here would end the transaction and silently discard the user
    # binding for anything that ran afterwards.
    return int(result["tokens_revoked"])


def update_me(db: Session, user_id: UUID, payload: MeUpdateRequest) -> dict:
    """
    PATCH /api/auth/me — `full_name` and `language_pref` only.

    Returns a full `MeResponse` by delegating to `me()` rather than assembling
    one, so the PATCH and GET shapes cannot drift. It costs one extra query on a
    route nobody calls in a loop.

    ⚠️ THE COLUMN LIST IS BUILT FROM THE FIELDS ACTUALLY SUPPLIED, so a PATCH of
    one field does not overwrite the other with None. Both columns carry their
    own UPDATE grant (`full_name` from 20260816160000, `language_pref` from
    20260816200000) and nothing else on `app_user` does — so a future edit that
    added a column here would be refused by PostgreSQL rather than silently
    permitted.
    """
    payload.validate_at_least_one_field()

    assignments = []
    params: dict[str, object] = {"uid": user_id}
    if payload.full_name is not None:
        assignments.append("full_name = :full_name")
        params["full_name"] = payload.full_name
    if payload.language_pref is not None:
        assignments.append("language_pref = :language_pref")
        params["language_pref"] = payload.language_pref.value

    # Every fragment above is a fixed literal chosen by the two `if`s; the
    # values are bound. `updated_at` is left to `trg_app_user_updated`.
    db.execute(text(f"UPDATE app_user SET {', '.join(assignments)} WHERE id = :uid"), params)  # noqa: S608

    return me(db, user_id)


def two_factor_status(db: Session, user_id: UUID) -> dict:
    """
    GET /api/auth/2fa/status.

    ONE SELECT against `two_factor_status_v`, which existed unused since
    20260801120000 and was given `security_invoker = true` by 20260816150000
    (finding B1) — before that it ran as its owner and a caller bound to a user
    owning nothing read every account's second-factor state through it.
    Measured then: 7 of 7 rows readable; now 0. `user_id` is therefore NOT in
    the WHERE clause by accident of trust — it is there because the view now
    applies `two_factor_enrollment`'s owner policy to the caller.

    ⚠️ DO NOT SWITCH THIS TO `app.get_unused_backup_codes`. That returns the
    HASHES (20260803120000:284-293), which the verify path needs because argon2
    is non-deterministic and a status endpoint has no business reading.

    ⚠️ DO NOT FOLD THIS INTO `GET /auth/me`. That is one deliberate extra round
    trip, on a screen the user visits occasionally, to keep the dashboard's
    hot-path query from growing a join nobody there needs.

    An account that never enrolled has no row at all, which is `enabled: false`
    rather than an error.
    """
    row = (
        db.execute(
            text(
                "SELECT method, status, locked_until, unused_backup_codes "
                "  FROM two_factor_status_v WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return {
            "enabled": False,
            "method": None,
            "locked_until": None,
            "backup_codes_remaining": 0,
        }

    enabled = str(row["status"]) == "active"
    return {
        "enabled": enabled,
        # Mirrors `MeResponse.two_factor`, which reports the method only while
        # the enrolment is active — a pending enrolment is not a second factor.
        "method": str(row["method"]) if enabled else None,
        "locked_until": row["locked_until"].isoformat() if row["locked_until"] else None,
        "backup_codes_remaining": int(row["unused_backup_codes"] or 0),
    }


# ============================================================================
# KAN-10b — 2FA Enrolment, Challenge, Email Verification, Password Reset
# ============================================================================


def _issue_and_send_email_otp(db: Session, user_id: UUID, recipient: Mapping) -> None:
    """
    Mint a six-digit OTP, store it hashed, and queue the mail.

    The code is stored under the KEYED hash (`hash_token`, HMAC-SHA256 with the
    app secret), not a bare digest. Six digits is a million possibilities — a
    plain SHA of that space is a rainbow table, whereas an HMAC is useless to
    anyone holding a database dump but not the application secret.

    `app.issue_email_otp` revokes any earlier unrevoked OTP in the same
    statement, so exactly one is live at a time.
    """
    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute(
        text("SELECT app.issue_email_otp(:uid, :hash, :expires)"),
        {
            "uid": user_id,
            "hash": hash_token(otp_code),
            "expires": datetime.now(UTC) + timedelta(seconds=_EMAIL_OTP_TTL_SECONDS),
        },
    )
    locale = _locale_of(recipient)
    subject, html = two_factor_otp_email(
        otp_code, expires_minutes=_EMAIL_OTP_TTL_SECONDS // 60, locale=locale
    )
    _queue_email(str(recipient["email"]), subject, html)


def _raise_for_token_status(db: Session, token: str, kind: TokenKind) -> None:
    """
    Turn "the consume function returned nothing" into the RIGHT error code.

    Three outcomes the client renders differently (tdd.md §7.3), and they must
    not be conflated:
      * never existed   -> 400 INVALID_TOKEN   ("this link is not valid")
      * already spent   -> 400 INVALID_TOKEN   (it worked once; it is not stale)
      * lapsed unused   -> 410 TOKEN_EXPIRED   ("ask for a new one" + a resend)

    Offering a resend for a token that was already used sends the user round a
    loop they have in fact already completed. `revoked` is what separates the
    two, which is why `check_token_status` now returns it.

    Always raises; typed as `-> None` because the caller has nothing to do after.
    """
    status_row = (
        db.execute(
            text("SELECT * FROM app.check_token_status(:hash, :kind)"),
            {"hash": hash_token(token), "kind": kind.value},
        )
        .mappings()
        .first()
    )
    if status_row and status_row["token_expired"] and not status_row["token_revoked"]:
        raise token_expired()
    raise invalid_token()


def _lookup_for_email_flow(db: Session, email: str) -> Mapping | None:
    """
    The read behind `password/forgot` and `email/resend`, plus the constant-time
    filler.

    The argon2 verify runs on BOTH paths so an unknown address costs what a
    known one does. It is not sufficient on its own — see `email.send_async` for
    the part that actually mattered — but it is still the right floor, because
    it makes the two branches expensive in the same way.
    """
    row = (
        db.execute(
            text("SELECT * FROM app.lookup_user_for_email_flow(:email)"),
            {"email": email},
        )
        .mappings()
        .one_or_none()
    )
    verify_password("dummy", _dummy_password_hash())
    # A suspended or deleted account is treated exactly like an unknown one:
    # nothing is sent, and the caller cannot tell the two apart.
    if row is None or str(row["status"]) != "active":
        return None
    return row


def _locale_of(row: Mapping) -> str:
    """Recipient's locale for links and templates; English when unknown."""
    return web_locale(row["language_pref"])


def _lockout_after(failed_attempts: int) -> datetime | None:
    """
    The lockout ladder (tdd.md §6.9 D7). Thresholds are evaluated in order and
    the HIGHEST one met wins, so the penalty escalates. `None` means the first
    threshold has not been reached yet.
    """
    settings = get_settings()
    locked_until = None
    for threshold, lockout_seconds in settings.two_factor_lockout_thresholds:
        if failed_attempts >= threshold:
            locked_until = datetime.now(UTC) + timedelta(seconds=lockout_seconds)
    return locked_until


def _record_2fa_failure(db: Session, user_id: UUID, failed_attempts: int) -> None:
    """
    Persist a wrong code and any lockout it triggers, then COMMIT.

    The commit is the whole point. The caller raises immediately afterwards, and
    that exception unwinds through `get_db`, which rolls the session back — so a
    lockout written and not committed is a lockout that never happened, and the
    attacker gets unlimited attempts while the code looks correct. Same shape as
    the refresh-reuse handler in `refresh()`.

    Shared by /2fa/confirm and /2fa/verify so enrolment and challenge cannot
    drift apart on the threshold table.
    """
    db.execute(
        text("SELECT app.verify_2fa_failure(:uid, :failed, :locked)"),
        {
            "uid": user_id,
            "failed": failed_attempts,
            "locked": _lockout_after(failed_attempts),
        },
    )
    db.execute(
        text(
            "INSERT INTO audit_log (actor_id, action, target) "
            "VALUES (:uid, '2fa_verify_failed', 'two_factor_enrollment')"
        ),
        {"uid": user_id},
    )
    db.commit()


def two_factor_enroll(db: Session, payload: TwoFactorEnrollRequest) -> dict:
    """
    POST /auth/2fa/enroll

    Initiates 2FA enrollment. Accepts an enrollment_token (from login response)
    and the chosen method (totp or email_otp).

    For TOTP: generates a secret, encrypts it, stores it, returns the secret
    + otpauth URI + QR code SVG for the user to scan.
    For email_otp: generates a 6-digit OTP, hashes it, sends it via email.

    The enrollment_token must be kind='two_factor_enrollment' (not pending).
    """
    # Validate enrollment_token
    token_row = db.execute(
        text("SELECT * FROM app.lookup_challenge_token(:hash, :kind)"),
        {
            "hash": hash_token(payload.enrollment_token),
            "kind": TokenKind.two_factor_enrollment.value,
        },
    ).first()

    if not token_row:
        raise pending_token_expired()

    # The SQL function does NOT check expiry or revocation — enforce it here
    if token_row.revoked or token_row.expires_at <= datetime.now(UTC):
        raise pending_token_expired()

    user_id = token_row.user_id

    set_current_user_id(db, user_id)
    enforce_subject(bucket="2fa_enroll", subject=str(user_id), limit=TWO_FA_ENROLL_USER_LIMIT)

    # One read, two checks. The bind above is what makes it see the row at all —
    # `two_factor_enrollment_owner` matches on `app.current_user_id()`.
    enrollment_check = db.execute(
        text("SELECT status, locked_until FROM two_factor_enrollment WHERE user_id = :uid"),
        {"uid": user_id},
    ).first()

    # Finding A9: the lockout was enforced at login, confirm, verify and resend,
    # but NOT here -- and this path sends an email one-time password.
    #
    # SCOPE, HONESTLY: this was never a way to bypass guessing. `/2fa/confirm`
    # checks the lockout, and `app.upsert_2fa_enrollment` deliberately preserves
    # `failed_attempts` and `locked_until` across a re-enrolment, so the counter
    # survives. What it allowed was MAIL FLOODING a locked account -- bounded at
    # five per five minutes per account by `enforce_subject` above, and needing a
    # live enrolment token, so a nuisance rather than a breach. It is fixed
    # because a lockout that four of five entry points honour is not a lockout.
    if (
        enrollment_check is not None
        and enrollment_check.locked_until is not None
        and enrollment_check.locked_until > datetime.now(UTC)
    ):
        raise two_factor_locked(enrollment_check.locked_until.isoformat())

    # Reject if 2FA is already active (cannot re-enroll)
    if enrollment_check and str(enrollment_check.status) == "active":
        raise AppError(
            status_code=400,
            code="VALIDATION_ERROR",
            message="2FA is already active. Cannot re-enroll.",
        )

    recipient = (
        db.execute(
            text(
                # `u.language_pref` since 20260816200000. The LEFT JOIN this
                # replaced returned NULL for every non-student, so a teacher who
                # had chosen Urdu still received an English OTP mail.
                "SELECT u.email, u.language_pref FROM app_user u WHERE u.id = :uid"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one()
    )

    if payload.method == "totp":
        secret = generate_totp_secret()
        db.execute(
            text("SELECT app.upsert_2fa_enrollment(:uid, :method, :secret)"),
            {"uid": user_id, "method": "totp", "secret": encrypt_secret(secret)},
        )

        otpauth_uri = build_otpauth_uri(secret, str(recipient["email"]))
        return {
            "method": "totp",
            "secret": secret,
            "otpauth_uri": otpauth_uri,
            "qr_svg": generate_qr_svg(otpauth_uri),
        }

    db.execute(
        text("SELECT app.upsert_2fa_enrollment(:uid, :method, NULL)"),
        {"uid": user_id, "method": "email_otp"},
    )
    _issue_and_send_email_otp(db, user_id, recipient)
    return {
        "method": "email_otp",
        "sent_to": _mask_email(str(recipient["email"])),
        "expires_in": _EMAIL_OTP_TTL_SECONDS,
    }


def two_factor_confirm(db: Session, payload: TwoFactorConfirmRequest) -> dict:
    """
    POST /auth/2fa/confirm

    Confirms 2FA enrollment by verifying the first code. Activates 2FA,
    generates 10 backup codes, revokes the enrollment_token, and issues
    access + refresh tokens.

    The enrollment_token must be kind='two_factor_enrollment'.
    """
    # Validate enrollment_token
    token_row = db.execute(
        text("SELECT * FROM app.lookup_challenge_token(:hash, :kind)"),
        {
            "hash": hash_token(payload.enrollment_token),
            "kind": TokenKind.two_factor_enrollment.value,
        },
    ).first()

    if not token_row:
        raise pending_token_expired()

    # The SQL function does NOT check expiry or revocation — enforce it here
    if token_row.revoked or token_row.expires_at <= datetime.now(UTC):
        raise pending_token_expired()

    user_id = token_row.user_id

    set_current_user_id(db, user_id)
    enforce_subject(bucket="2fa_confirm", subject=str(user_id), limit=TWO_FA_CONFIRM_USER_LIMIT)

    enrollment = (
        db.execute(
            text(
                "SELECT method, totp_secret_encrypted, failed_attempts, locked_until "
                "FROM two_factor_enrollment WHERE user_id = :uid AND status = 'pending'"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )

    if enrollment is None:
        raise unauthenticated("2FA enrollment not found or already active")

    # ENROLMENT IS RATE-LIMITED THE SAME WAY THE CHALLENGE IS. It was not: this
    # endpoint verified a code and raised, never touching `failed_attempts`, so
    # a six-digit email OTP was guessable with only the per-address limiter in
    # the way and the account never locked. tdd.md §6.9 D7 makes no distinction
    # between enrolment and challenge, and neither does an attacker.
    locked_until = enrollment["locked_until"]
    if locked_until is not None and locked_until > datetime.now(UTC):
        raise two_factor_locked(locked_until.isoformat())

    method = str(enrollment["method"])
    counter: int | None = None

    if method == "totp":
        secret = decrypt_secret(enrollment["totp_secret_encrypted"])
        counter = verify_totp_code(secret, payload.code)
        if counter is None:
            _record_2fa_failure(db, user_id, enrollment["failed_attempts"] + 1)
            raise two_factor_invalid()

    else:  # email_otp
        otp_row = db.execute(
            text("SELECT id FROM app.lookup_email_otp(:uid, :hash)"),
            {"uid": user_id, "hash": hash_token(payload.code)},
        ).first()
        if not otp_row:
            _record_2fa_failure(db, user_id, enrollment["failed_attempts"] + 1)
            raise two_factor_invalid()
        db.execute(
            text("UPDATE auth_token SET revoked = true WHERE id = :id"),
            {"id": otp_row.id},
        )

    # Activate, recording the TOTP counter that was just consumed. Without the
    # counter the code that completed enrolment stayed replayable at
    # /2fa/verify for its whole +/-1 window, because the replay guard there has
    # nothing to compare against until the first successful challenge.
    db.execute(
        text("SELECT app.activate_2fa(:uid, :counter)"),
        {"uid": user_id, "counter": counter},
    )

    codes = generate_backup_codes(10)
    code_hashes = [hash_backup_code(c) for c in codes]
    db.execute(
        text("SELECT app.replace_backup_codes(:uid, :hashes)"),
        {"uid": user_id, "hashes": code_hashes},
    )

    # Revoke enrollment_token
    db.execute(
        text("UPDATE auth_token SET revoked = true WHERE id = :id"),
        {"id": token_row.id},
    )

    # Issue access + refresh tokens
    access_token, expires_in = create_access_token(user_id)
    refresh_plain, _ = issue_refresh_token(db, user_id)

    return {
        "two_factor": {"enabled": True, "method": method},
        "backup_codes": codes,
        "onboarding_state": onboarding_state_for(db, user_id, two_factor_active=True),
        "access_token": access_token,
        "expires_in": expires_in,
        "refresh_token": refresh_plain,
    }


def two_factor_verify(db: Session, payload: TwoFactorVerifyRequest) -> dict:
    """
    POST /auth/2fa/verify

    Verifies a 2FA challenge. Accepts a pending_token (kind='two_factor_pending')
    and a code (TOTP, email_otp, or backup_code).

    On success: revokes the pending_token, issues access + refresh tokens.
    On failure: increments failed_attempts, potentially locks the account.

    REJECTS enrollment_tokens (kind='two_factor_enrollment') — only pending
    tokens are valid here.
    """
    # ONE round trip, not two. `start_2fa_challenge` already filters on kind,
    # `revoked = false` and `expires_at > now()` in SQL — which is what makes an
    # enrolment token presented here return zero rows rather than a session. The
    # separate `lookup_challenge_token` call it used to make first re-checked the
    # same three things in Python and could only ever agree.
    enrollment_row = (
        db.execute(
            text("SELECT * FROM app.start_2fa_challenge(:hash, :kind)"),
            {
                "hash": hash_token(payload.pending_token),
                "kind": TokenKind.two_factor_pending.value,
            },
        )
        .mappings()
        .first()
    )

    if not enrollment_row:
        raise pending_token_expired()

    user_id = enrollment_row["token_user_id"]

    set_current_user_id(db, user_id)
    enforce_subject(bucket="2fa_verify", subject=str(user_id), limit=TWO_FA_VERIFY_USER_LIMIT)

    # A challenge only exists for a COMPLETED enrolment. Defensive: `login()`
    # hands out a pending token only when the enrolment is active, so reaching
    # here otherwise means something upstream changed.
    if str(enrollment_row["status"]) != "active":
        raise pending_token_expired()

    # Check lockout
    locked_until = enrollment_row["locked_until"]
    if locked_until and locked_until > datetime.now(UTC):
        raise two_factor_locked(locked_until.isoformat())

    method = str(enrollment_row["method"])

    # Verify code based on type
    verified = False
    counter = None

    if payload.type == "totp":
        if method != "totp":
            raise two_factor_invalid()
        secret = decrypt_secret(enrollment_row["totp_secret_encrypted"])
        counter = verify_totp_code(
            secret,
            payload.code,
            last_counter=enrollment_row["last_used_counter"],
        )
        verified = counter is not None

    elif payload.type == "email_otp":
        if method != "email_otp":
            raise two_factor_invalid()
        otp_hash = hash_token(payload.code)
        otp_row = db.execute(
            text("SELECT id FROM app.lookup_email_otp(:uid, :hash)"),
            {"uid": user_id, "hash": otp_hash},
        ).first()
        if otp_row:
            # Revoke the OTP
            db.execute(
                text("UPDATE auth_token SET revoked = true WHERE id = :id"),
                {"id": otp_row[0]},
            )
            verified = True

    elif payload.type == "backup_code":
        # Backup codes are argon2id-hashed, so we must retrieve all unused
        # hashes and compare with verify_backup_code (not a simple hash
        # lookup like HMAC tokens). This is deliberate: argon2id is
        # non-deterministic, so the same code produces different hashes.
        unused_rows = db.execute(
            text("SELECT code_hash FROM app.get_unused_backup_codes(:uid)"),
            {"uid": user_id},
        ).fetchall()

        for row in unused_rows:
            if verify_backup_code(payload.code, row[0]):
                db.execute(
                    text("SELECT app.consume_backup_code(:uid, :hash)"),
                    {"uid": user_id, "hash": row[0]},
                )
                verified = True
                break

    if not verified:
        _record_2fa_failure(db, user_id, enrollment_row["failed_attempts"] + 1)
        raise two_factor_invalid()

    # Success: reset failed_attempts, update last_used
    db.execute(
        text("SELECT app.verify_2fa_success(:uid, :counter)"),
        {"uid": user_id, "counter": counter},
    )

    # Revoke pending_token
    db.execute(
        text("UPDATE auth_token SET revoked = true WHERE id = :id"),
        {"id": enrollment_row["token_id"]},
    )

    # Issue access + refresh tokens
    access_token, expires_in = create_access_token(user_id)
    refresh_plain, _ = issue_refresh_token(db, user_id)

    return {
        "access_token": access_token,
        "token_type": "bearer",  # noqa: S106 -- the OAuth scheme name, not a secret
        "expires_in": expires_in,
        "onboarding_state": onboarding_state_for(db, user_id, two_factor_active=True),
        "refresh_token": refresh_plain,
    }


def two_factor_resend(db: Session, payload: TwoFactorResendRequest) -> dict:
    """
    POST /auth/2fa/resend

    Resends the email OTP for an email_otp enrollment. Only valid for
    email_otp method (TOTP users should use backup codes).

    The pending_token must be kind='two_factor_pending'.
    """
    challenge = (
        db.execute(
            text("SELECT * FROM app.start_2fa_challenge(:hash, :kind)"),
            {
                "hash": hash_token(payload.pending_token),
                "kind": TokenKind.two_factor_pending.value,
            },
        )
        .mappings()
        .first()
    )
    if not challenge:
        raise pending_token_expired()

    user_id = challenge["token_user_id"]
    set_current_user_id(db, user_id)
    enforce_subject(bucket="2fa_resend", subject=str(user_id), limit=TWO_FA_RESEND_USER_LIMIT)

    # A lockout has to cover the resend too, or it buys nothing: an attacker who
    # cannot guess can still make the victim's inbox unusable, and the whole
    # point of `locked_until` is that the challenge goes quiet.
    locked_until = challenge["locked_until"]
    if locked_until is not None and locked_until > datetime.now(UTC):
        raise two_factor_locked(locked_until.isoformat())

    # `/2fa/resend` re-sends to the ENROLLED method; nothing sends a first OTP to
    # a TOTP user (tdd.md §14.4 finding 3), so this is the client asking for
    # something the contract does not offer. `VALIDATION_ERROR` with a field is
    # the catalogued way to say that — the previous `INVALID_METHOD` appears in
    # neither tdd.md §7.3 nor the client's ERROR_CODES, so it rendered as the
    # generic "something went wrong".
    if str(challenge["method"]) != "email_otp":
        raise validation_error(
            message="Resend is not available for this second factor.",
            details={
                "fields": {
                    "type": "Resend is only available when the second factor is an emailed code."
                }
            },
        )

    recipient = (
        db.execute(
            text(
                # `u.language_pref` since 20260816200000. The LEFT JOIN this
                # replaced returned NULL for every non-student, so a teacher who
                # had chosen Urdu still received an English OTP mail.
                "SELECT u.email, u.language_pref FROM app_user u WHERE u.id = :uid"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one()
    )
    _issue_and_send_email_otp(db, user_id, recipient)

    return {
        "sent_to": _mask_email(str(recipient["email"])),
        "expires_in": _EMAIL_OTP_TTL_SECONDS,
    }


def verify_email(db: Session, payload: EmailVerifyRequest) -> dict:
    """
    POST /auth/email/verify

    Verifies the email address using a token from the verification email.
    Idempotent: if the email is already verified, returns success.

    Issues an onboarding-scoped access_token (type='onboarding') and a new
    enrollment_token for 2FA enrollment.
    """
    # Call the idempotent verification function
    result = db.execute(
        text("SELECT * FROM app.consume_token_and_verify_email(:hash)"),
        {"hash": hash_token(payload.token)},
    ).first()

    if not result:
        _raise_for_token_status(db, payload.token, TokenKind.email_verify)

    user_id = result.user_id

    # Bind user to transaction
    set_current_user_id(db, user_id)

    # Issue onboarding-scoped access_token
    access_token, expires_in = create_access_token(
        user_id,
        token_type="onboarding",  # noqa: S106 -- a JWT claim value, not a secret
    )

    # Issue enrollment_token for 2FA
    settings = get_settings()
    enrollment_plain = issue_challenge_token(
        db,
        user_id,
        kind=TokenKind.two_factor_enrollment,
        ttl_seconds=settings.enrollment_token_ttl_seconds,
    )

    return {
        "email_verified": True,
        "onboarding_state": onboarding_state_for(db, user_id),
        "access_token": access_token,
        "expires_in": expires_in,
        "enrollment_token": enrollment_plain,
    }


def resend_email_verification(db: Session, payload: EmailResendRequest) -> None:
    """
    POST /auth/email/resend

    Resends the email verification link. Constant-time whether or not the
    address exists (prevents enumeration).
    """
    user_row = _lookup_for_email_flow(db, payload.email)

    if user_row is not None and not user_row["email_verified_at"]:
        token = issue_preauth_token(
            db,
            user_row["id"],
            kind=TokenKind.email_verify,
            ttl_seconds=_EMAIL_LINK_TTL_SECONDS,
        )
        locale = _locale_of(user_row)
        subject, html = verification_email(build_verification_url(token, locale), locale)
        _queue_email(str(user_row["email"]), subject, html)


def forgot_password(db: Session, payload: PasswordForgotRequest) -> None:
    """
    POST /auth/password/forgot

    Identical response for a known and an unknown address — body, status AND
    timing (tdd.md §6.11). See `_lookup_for_email_flow` for why the dummy hash
    alone was not enough.

    Deliberately requires a VERIFIED address: a reset link mailed to an
    unverified one would let whoever controls that mailbox take an account they
    never proved they own. An unverified user re-verifies first.
    """
    user_row = _lookup_for_email_flow(db, payload.email)

    if user_row is not None and user_row["email_verified_at"]:
        token = issue_preauth_token(
            db,
            user_row["id"],
            kind=TokenKind.password_reset,
            ttl_seconds=_EMAIL_LINK_TTL_SECONDS,
        )
        locale = _locale_of(user_row)
        subject, html = password_reset_email(build_password_reset_url(token, locale), locale)
        _queue_email(str(user_row["email"]), subject, html)


def reset_password(db: Session, payload: PasswordResetRequest) -> None:
    """
    POST /auth/password/reset

    Resets the password using a token from the reset email. Revokes all
    refresh tokens (logs out all sessions).
    """
    # Hash the new password
    new_password_hash = hash_password(payload.new_password)

    # Consume the reset token
    result = db.execute(
        text("SELECT app.consume_password_reset_token(:hash, :new_hash)"),
        {"hash": hash_token(payload.token), "new_hash": new_password_hash},
    ).scalar()

    if not result:
        _raise_for_token_status(db, payload.token, TokenKind.password_reset)


# ----------------------------------------------------------------------------
# Guardian gate (RBAC-002). PRD §4.3: a class 9-10 student cannot use learning
# endpoints until a parent confirms an out-of-band invite. No route in this
# file touches `get_service_db`; the two privileged reads (parent id by email,
# parent email by student) and the atomic confirm write are the SECURITY
# DEFINER functions from migration 20260802150000.
# ----------------------------------------------------------------------------


def guardian_invite(db: Session, student_id: UUID, payload: GuardianInviteRequest) -> dict:
    """
    Student -> parent invite. Requires the parent's account to EXIST (decision
    5: the parent signs up first); a missing/inactive/non-parent account is a
    422 GUARDIAN_NOT_FOUND. All writes happen after every validation, so nothing
    is made that must survive an error.
    """
    parent_email = str(payload.parent_email).lower()

    # Self-link is checked against the student's OWN email (readable under
    # app_user_self_read), not the parent lookup, so a student can't learn
    # whether an arbitrary address exists from this endpoint's response codes.
    student = (
        db.execute(
            text("SELECT email FROM app_user WHERE id = :uid AND deleted_at IS NULL"),
            {"uid": student_id},
        )
        .mappings()
        .one_or_none()
    )
    if student is None:
        raise unauthenticated()
    if str(student["email"]).lower() == parent_email:
        raise self_link_forbidden()

    parent_id = db.execute(
        text("SELECT app.lookup_parent_id_by_email(:email)"), {"email": parent_email}
    ).scalar_one_or_none()
    if parent_id is None:
        raise guardian_not_found()

    already_verified = db.execute(
        text("SELECT 1 FROM guardian_link WHERE student_id = :sid AND status = 'verified' LIMIT 1"),
        {"sid": student_id},
    ).one_or_none()
    if already_verified is not None:
        raise guardian_already_linked()

    # Create the link if it is missing, then reset it to pending. Two statements
    # rather than a read-then-branch, so two invites racing cannot both decide
    # the row is absent and collide on uq_guardian_pair.
    #
    # The INSERT runs under `guardian_link_create` as the student. The RESET does
    # NOT run under RLS as the student, because `guardian_link_update` is
    # PARENT-ONLY in the applied database: a student's UPDATE matches zero rows
    # and raises nothing, which is how re-inviting after a revoke used to return
    # `invite_sent: true` while leaving the link `revoked` and un-confirmable.
    # Widening that policy is not the fix — a student who can UPDATE their own
    # link can set `verified` and clear their own gate. `reinvite_guardian_link`
    # is the narrow privileged path and can only ever write `pending`
    # (migration 20260803090000).
    db.execute(
        text(
            "INSERT INTO guardian_link (parent_id, student_id, status) "
            "VALUES (:pid, :sid, 'pending') "
            "ON CONFLICT (parent_id, student_id) DO NOTHING"
        ),
        {"pid": parent_id, "sid": student_id},
    )
    reset_to = db.execute(
        text("SELECT app.reinvite_guardian_link(:sid, :pid)"),
        {"sid": student_id, "pid": parent_id},
    ).scalar_one()
    if reset_to != "pending":
        # NULL means nothing was reset, which after the INSERT above can only be
        # a link that turned `verified` between the check and here. Fail loudly:
        # an invitation that is already superseded must not be reported as sent.
        raise guardian_already_linked()

    # Only the newest invite is live: revoking BEFORE issuance means a stale
    # email link cannot be redeemed after a resend. Both are owner-scoped writes
    # under RLS as the student.
    revoke_user_tokens(db, student_id, kind=TokenKind.guardian_invite.value)
    issue_guardian_invite_token(db, student_id)

    return {
        "invite_sent": True,
        "parent_email": _mask_email(parent_email),
        "status": "pending",
    }


def guardian_status(db: Session, student_id: UUID) -> dict:
    """
    The student's gate state. `required` and the gated decision share the pure
    helpers in gate.py with `me()`. `status` is `null` when there is no link and
    `revoked` passes through unchanged; the parent email is masked.
    """
    profile = (
        db.execute(
            text("SELECT class_level FROM student_profile WHERE user_id = :uid"),
            {"uid": student_id},
        )
        .mappings()
        .one_or_none()
    )
    link = (
        db.execute(
            text(
                "SELECT status, created_at FROM guardian_link g "
                "WHERE g.student_id = :uid "
                "ORDER BY (g.status = 'verified') DESC, g.created_at DESC LIMIT 1"
            ),
            {"uid": student_id},
        )
        .mappings()
        .one_or_none()
    )

    # The route is role=student, so is_student is True; class_level comes from
    # the profile, and a missing profile (defensive) means "not gated".
    required = gate.guardian_required(
        is_student=True, class_level=profile["class_level"] if profile is not None else None
    )
    guardian_status = str(link["status"]) if link is not None else None

    parent_email = None
    if link is not None:
        email = db.execute(
            text("SELECT app.lookup_guardian_parent_email(:sid)"), {"sid": student_id}
        ).scalar_one_or_none()
        if email is not None:
            parent_email = _mask_email(str(email))

    invited_at = link["created_at"].isoformat() if link is not None else None

    return {
        "required": required,
        "status": guardian_status,
        "parent_email": parent_email,
        "invited_at": invited_at,
    }


def guardian_confirm(db: Session, parent_id: UUID, payload: GuardianConfirmRequest) -> dict:
    """
    Parent confirms a one-time invite token. The atomic write (flip link +
    consume token) lives inside app.confirm_guardian_link and is the ONLY write
    here — so nothing is written that must survive an error (transaction safety
    rule). The function returns the link status BEFORE the transition:
      * 0 rows        -> unknown/expired/revoked token, or no link  -> 400
      * 'verified'    -> was already verified (token untouched)      -> 409
      * 'pending'     -> this call flipped it to verified            -> 200
    """
    token_hash = hash_token(payload.invite_token)
    row = (
        db.execute(
            text("SELECT status, student_name FROM app.confirm_guardian_link(:pid, :hash)"),
            {"pid": parent_id, "hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )

    if row is None:
        raise invalid_token()
    if str(row["status"]) == "verified":
        raise guardian_already_linked()
    return {"status": "verified", "student_name": row["student_name"]}
