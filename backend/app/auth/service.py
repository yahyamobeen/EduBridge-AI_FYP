from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import gate
from app.auth.onboarding import derive_onboarding_state
from app.auth.schemas import GROUP_LABELS, LoginRequest, RegisterRequest
from app.auth.security import create_access_token, hash_password, verify_password
from app.auth.tokens import (
    RefreshTokenReuseError,
    find_token,
    issue_challenge_token,
    revoke_refresh_family,
    revoke_user_tokens,
    rotate_refresh_token,
)
from app.core.config import get_settings
from app.core.db import set_current_user_id
from app.core.errors import (
    email_already_registered,
    two_factor_locked,
    unauthenticated,
)
from app.models.enums import TokenKind, UserRole

# The one plan in v1, seeded by 20260802120000_subscriptions_and_oauth.sql and
# referenced by subscription.plan_code.
_DEFAULT_PLAN_CODE = "standard"


def register(db: Session, payload: RegisterRequest) -> dict:
    # Two DIFFERENT failures, two different codes. Absent student fields are a
    # 400 VALIDATION_ERROR with per-field detail; a class/group pair that does
    # not exist is a 422 INVALID_CLASS_GROUP. Collapsing both into the second
    # tells a user who submitted an empty form that "that group is not offered
    # for the class you selected", which is not what happened.
    payload.validate_required_student_fields()
    payload.validate_student_group_for_class()

    new_id = uuid4()

    # REQUIRED, despite looking odd on an unauthenticated endpoint. `app_user`
    # inserts are open (`app_user_insert` is WITH CHECK (true)), but every
    # profile policy is `WITH CHECK (user_id = app.current_user_id())`, and so
    # is `subscription_owner`. Without binding the id we are about to create,
    # RLS refuses the profile and subscription inserts below.
    set_current_user_id(db, new_id)

    try:
        db.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, role, status, full_name) "
                "VALUES (:id, :email, :pwhash, :role, 'active', :full_name)"
            ),
            {
                "id": new_id,
                "email": str(payload.email).lower(),
                "pwhash": hash_password(payload.password),
                "role": payload.role.value,
                "full_name": payload.full_name,
            },
        )
        db.flush()
    except IntegrityError as exc:
        if isinstance(exc.orig, UniqueViolation):
            raise email_already_registered() from exc
        raise

    if payload.role == UserRole.student:
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
    elif payload.role == UserRole.teacher:
        db.execute(
            text(
                "INSERT INTO teacher_profile (user_id, institution) VALUES (:user_id, :institution)"
            ),
            {"user_id": new_id, "institution": payload.institution},
        )
    elif payload.role == UserRole.parent:
        db.execute(
            text("INSERT INTO parent_profile (user_id) VALUES (:user_id)"),
            {"user_id": new_id},
        )

    return {
        "user_id": str(new_id),
        "email": str(payload.email).lower(),
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


def login(db: Session, payload: LoginRequest) -> dict:
    """
    A CORRECT password never returns a session — it returns 200 with a `status`
    discriminator saying which step comes next (tdd.md §3.1). Only a WRONG
    password is a failure, and its message must not reveal whether the address
    exists.

    This runs pre-authentication, so the lookup goes through the narrow
    SECURITY DEFINER function rather than an RLS-bypassing connection: there is
    no `app.current_user_id()` yet to satisfy `app_user_self_read` with.
    """
    row = (
        db.execute(
            text(
                "SELECT id, password_hash, status, email_verified_at "
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

    user_id = row["id"]

    twofa = (
        db.execute(
            text(
                "SELECT method, status, locked_until FROM two_factor_enrollment "
                "WHERE user_id = :uid"
            ),
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
    SELECT u.id, u.email, u.full_name, u.role, u.email_verified_at,
           sp.board, sp.class_level, sp.student_group, sp.medium, sp.language_pref,
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
