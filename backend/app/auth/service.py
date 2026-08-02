from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.onboarding import derive_onboarding_state
from app.auth.schemas import GROUP_LABELS, LoginRequest, RegisterRequest
from app.auth.security import create_access_token, hash_password, hash_token, verify_password
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
    forbidden_scope,
    invalid_token,
    pending_token_expired,
    token_expired,
    two_factor_invalid,
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

    # prd.md §4.3: Classes 9-10 only.
    guardian_required = is_student and class_level in (9, 10)
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


# ============================================================================
# KAN-10b — 2FA Enrolment, Challenge, Email Verification, Password Reset
# ============================================================================

def two_factor_enroll(db: Session, payload) -> dict:
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

    user_id = token_row.user_id

    # Bind user to transaction
    set_current_user_id(db, user_id)

    if payload.method == "totp":
        # Generate TOTP secret
        from app.auth.totp import build_otpauth_uri, encrypt_secret, generate_qr_svg, generate_totp_secret
        secret = generate_totp_secret()
        encrypted = encrypt_secret(secret)

        # Upsert enrollment (re-calling /2fa/enroll regenerates the secret)
        db.execute(
            text("SELECT app.upsert_2fa_enrollment(:uid, :method, :secret)"),
            {"uid": user_id, "method": "totp", "secret": encrypted},
        )

        # Build response
        user_row = db.execute(
            text("SELECT email FROM app_user WHERE id = :uid"),
            {"uid": user_id},
        ).first()
        otpauth_uri = build_otpauth_uri(secret, user_row.email)
        qr_svg = generate_qr_svg(otpauth_uri)

        return {
            "method": "totp",
            "secret": secret,
            "otpauth_uri": otpauth_uri,
            "qr_svg": qr_svg,
        }

    else:  # email_otp
        import secrets
        from app.auth.email import get_email_sender
        from app.auth.email_templates import two_factor_otp_email
        from app.auth.security import hash_token as hash_otp

        # Upsert enrollment (no secret for email_otp)
        db.execute(
            text("SELECT app.upsert_2fa_enrollment(:uid, :method, NULL)"),
            {"uid": user_id, "method": "email_otp"},
        )

        # Generate 6-digit OTP
        otp_code = f"{secrets.randbelow(1000000):06d}"
        otp_hash = hash_otp(otp_code)

        # Get user email
        user_row = db.execute(
            text("SELECT email FROM app_user WHERE id = :uid"),
            {"uid": user_id},
        ).first()

        # Store OTP (revokes prior OTPs, inserts new one)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        db.execute(
            text("SELECT app.issue_email_otp(:uid, :hash, :expires)"),
            {"uid": user_id, "hash": otp_hash, "expires": expires_at},
        )

        # Send email
        subject, html = two_factor_otp_email(otp_code, expires_minutes=10)
        get_email_sender().send(user_row.email, subject, html)

        return {
            "method": "email_otp",
            "sent_to": _mask_email(user_row.email),
            "expires_in": 600,
        }


def two_factor_confirm(db: Session, payload) -> dict:
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

    user_id = token_row.user_id

    # Bind user to transaction
    set_current_user_id(db, user_id)

    # Get enrollment data
    enrollment = db.execute(
        text("""
            SELECT method, totp_secret_encrypted
            FROM two_factor_enrollment
            WHERE user_id = :uid AND status = 'pending'
        """),
        {"uid": user_id},
    ).first()

    if not enrollment:
        raise unauthenticated("2FA enrollment not found or already active")

    method = str(enrollment.method)

    # Verify code based on method
    if method == "totp":
        from app.auth.totp import decrypt_secret, verify_totp_code
        secret = decrypt_secret(enrollment.totp_secret_encrypted)
        counter = verify_totp_code(secret, payload.code)
        if counter is None:
            raise two_factor_invalid()

    else:  # email_otp
        otp_hash = hash_token(payload.code)
        otp_row = db.execute(
            text("SELECT id FROM app.lookup_email_otp(:uid, :hash)"),
            {"uid": user_id, "hash": otp_hash},
        ).first()
        if not otp_row:
            raise two_factor_invalid()
        # Revoke the OTP
        db.execute(
            text("UPDATE auth_token SET revoked = true WHERE id = :id"),
            {"id": otp_row.id},
        )

    # Activate 2FA
    db.execute(
        text("SELECT app.activate_2fa(:uid)"),
        {"uid": user_id},
    )

    # Generate 10 backup codes
    from app.auth.backup_codes import generate_backup_codes, hash_backup_code
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

    # Derive onboarding_state
    user_row = db.execute(
        text("SELECT * FROM app_user WHERE id = :uid"),
        {"uid": user_id},
    ).first()

    profile_row = None
    if str(user_row.role) == "student":
        profile_row = db.execute(
            text("SELECT board, class_level, student_group, medium, language_pref FROM student_profile WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()

    is_student = str(user_row.role) == "student"
    guardian_required = is_student and profile_row and profile_row.class_level in (9, 10)
    guardian_status = None
    if guardian_required:
        guardian_row = db.execute(
            text("SELECT status FROM guardian_link WHERE student_id = :uid AND status = 'verified'"),
            {"uid": user_id},
        ).first()
        guardian_status = "verified" if guardian_row else None

    subscription_status = None
    if is_student:
        sub_row = db.execute(
            text("SELECT status FROM subscription WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()
        subscription_status = str(sub_row.status) if sub_row else None

    onboarding_state = derive_onboarding_state(
        email_verified=user_row.email_verified_at is not None,
        two_factor_active=True,
        is_student=is_student,
        guardian_required=guardian_required,
        guardian_status=guardian_status,
        subscription_status=subscription_status,
    )

    return {
        "two_factor": {"enabled": True, "method": method},
        "backup_codes": codes,
        "onboarding_state": onboarding_state,
        "access_token": access_token,
        "expires_in": expires_in,
        "refresh_token": refresh_plain,
    }


def two_factor_verify(db: Session, payload) -> dict:
    """
    POST /auth/2fa/verify

    Verifies a 2FA challenge. Accepts a pending_token (kind='two_factor_pending')
    and a code (TOTP, email_otp, or backup_code).

    On success: revokes the pending_token, issues access + refresh tokens.
    On failure: increments failed_attempts, potentially locks the account.

    REJECTS enrollment_tokens (kind='two_factor_enrollment') — only pending
    tokens are valid here.
    """
    # Validate pending_token (MUST be two_factor_pending, NOT two_factor_enrollment)
    token_row = db.execute(
        text("SELECT * FROM app.lookup_challenge_token(:hash, :kind)"),
        {
            "hash": hash_token(payload.pending_token),
            "kind": TokenKind.two_factor_pending.value,
        },
    ).first()

    if not token_row:
        raise pending_token_expired()

    user_id = token_row.user_id

    # Bind user to transaction
    set_current_user_id(db, user_id)

    # Get enrollment data
    enrollment_data = db.execute(
        text("SELECT * FROM app.start_2fa_challenge(:hash, :kind)"),
        {
            "hash": hash_token(payload.pending_token),
            "kind": TokenKind.two_factor_pending.value,
        },
    ).first()

    if not enrollment_data:
        raise pending_token_expired()

    # Check lockout
    locked_until = enrollment_data.locked_until
    if locked_until and locked_until > datetime.now(timezone.utc):
        raise two_factor_locked(locked_until.isoformat())

    method = str(enrollment_data.method)

    # Verify code based on type
    verified = False
    counter = None

    if payload.type == "totp":
        if method != "totp":
            raise two_factor_invalid()
        from app.auth.totp import decrypt_secret, verify_totp_code
        secret = decrypt_secret(enrollment_data.totp_secret_encrypted)
        counter = verify_totp_code(
            secret,
            payload.code,
            last_counter=enrollment_data.last_used_counter,
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
                {"id": otp_row.id},
            )
            verified = True

    elif payload.type == "backup_code":
        code_hash = hash_token(payload.code.upper())
        result = db.execute(
            text("SELECT app.consume_backup_code(:uid, :hash)"),
            {"uid": user_id, "hash": code_hash},
        ).scalar()
        verified = result == 1

    if not verified:
        # Increment failed_attempts
        failed_attempts = enrollment_data.failed_attempts + 1

        # Compute lockout
        settings = get_settings()
        locked_until = None
        for threshold, lockout_seconds in settings.two_factor_lockout_thresholds:
            if failed_attempts >= threshold:
                locked_until = datetime.now(timezone.utc) + timedelta(seconds=lockout_seconds)

        db.execute(
            text("SELECT app.verify_2fa_failure(:uid, :failed, :locked)"),
            {"uid": user_id, "failed": failed_attempts, "locked": locked_until},
        )

        # Audit log
        db.execute(
            text("""
                INSERT INTO audit_log (user_id, action, ip_address)
                VALUES (:uid, '2fa_verify_failed', :ip)
            """),
            {"uid": user_id, "ip": None},
        )

        raise two_factor_invalid()

    # Success: reset failed_attempts, update last_used
    db.execute(
        text("SELECT app.verify_2fa_success(:uid, :counter)"),
        {"uid": user_id, "counter": counter},
    )

    # Revoke pending_token
    db.execute(
        text("UPDATE auth_token SET revoked = true WHERE id = :id"),
        {"id": token_row.id},
    )

    # Issue access + refresh tokens
    access_token, expires_in = create_access_token(user_id)
    refresh_plain, _ = issue_refresh_token(db, user_id)

    # Derive onboarding_state
    user_row = db.execute(
        text("SELECT * FROM app_user WHERE id = :uid"),
        {"uid": user_id},
    ).first()

    profile_row = None
    if str(user_row.role) == "student":
        profile_row = db.execute(
            text("SELECT board, class_level, student_group, medium, language_pref FROM student_profile WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()

    is_student = str(user_row.role) == "student"
    guardian_required = is_student and profile_row and profile_row.class_level in (9, 10)
    guardian_status = None
    if guardian_required:
        guardian_row = db.execute(
            text("SELECT status FROM guardian_link WHERE student_id = :uid AND status = 'verified'"),
            {"uid": user_id},
        ).first()
        guardian_status = "verified" if guardian_row else None

    subscription_status = None
    if is_student:
        sub_row = db.execute(
            text("SELECT status FROM subscription WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()
        subscription_status = str(sub_row.status) if sub_row else None

    onboarding_state = derive_onboarding_state(
        email_verified=user_row.email_verified_at is not None,
        two_factor_active=True,
        is_student=is_student,
        guardian_required=guardian_required,
        guardian_status=guardian_status,
        subscription_status=subscription_status,
    )

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "onboarding_state": onboarding_state,
        "refresh_token": refresh_plain,
    }


def two_factor_resend(db: Session, payload) -> dict:
    """
    POST /auth/2fa/resend

    Resends the email OTP for an email_otp enrollment. Only valid for
    email_otp method (TOTP users should use backup codes).

    The pending_token must be kind='two_factor_pending'.
    """
    # Validate pending_token
    token_row = db.execute(
        text("SELECT * FROM app.lookup_challenge_token(:hash, :kind)"),
        {
            "hash": hash_token(payload.pending_token),
            "kind": TokenKind.two_factor_pending.value,
        },
    ).first()

    if not token_row:
        raise pending_token_expired()

    user_id = token_row.user_id

    # Bind user to transaction
    set_current_user_id(db, user_id)

    # Check method is email_otp
    enrollment = db.execute(
        text("SELECT method FROM two_factor_enrollment WHERE user_id = :uid"),
        {"uid": user_id},
    ).first()

    if not enrollment or str(enrollment.method) != "email_otp":
        raise AppError(
            status_code=400,
            code="INVALID_METHOD",
            message="Resend is only available for email_otp method",
        )

    # Generate new OTP
    import secrets
    from app.auth.email import get_email_sender
    from app.auth.email_templates import two_factor_otp_email
    from app.auth.security import hash_token as hash_otp

    otp_code = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hash_otp(otp_code)

    # Get user email
    user_row = db.execute(
        text("SELECT email FROM app_user WHERE id = :uid"),
        {"uid": user_id},
    ).first()

    # Store OTP (revokes prior OTPs, inserts new one)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.execute(
        text("SELECT app.issue_email_otp(:uid, :hash, :expires)"),
        {"uid": user_id, "hash": otp_hash, "expires": expires_at},
    )

    # Send email
    subject, html = two_factor_otp_email(otp_code, expires_minutes=10)
    get_email_sender().send(user_row.email, subject, html)

    return {
        "sent_to": _mask_email(user_row.email),
        "expires_in": 600,
    }


def verify_email(db: Session, payload) -> dict:
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
        # Check if token exists but is expired
        token_check = db.execute(
            text("""
                SELECT id, user_id, expires_at FROM auth_token
                WHERE token_hash = :hash AND kind = 'email_verify'
            """),
            {"hash": hash_token(payload.token)},
        ).first()

        if token_check and token_check.expires_at < datetime.now(timezone.utc):
            raise token_expired()
        else:
            raise invalid_token()

    user_id = result.user_id
    already_verified = result.already_verified

    # Bind user to transaction
    set_current_user_id(db, user_id)

    # Issue onboarding-scoped access_token
    access_token, expires_in = create_access_token(
        user_id,
        token_type="onboarding",
    )

    # Issue enrollment_token for 2FA
    settings = get_settings()
    enrollment_plain = issue_challenge_token(
        db,
        user_id,
        kind=TokenKind.two_factor_enrollment,
        ttl_seconds=settings.enrollment_token_ttl_seconds,
    )

    # Derive onboarding_state
    user_row = db.execute(
        text("SELECT * FROM app_user WHERE id = :uid"),
        {"uid": user_id},
    ).first()

    profile_row = None
    if str(user_row.role) == "student":
        profile_row = db.execute(
            text("SELECT board, class_level, student_group, medium, language_pref FROM student_profile WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()

    is_student = str(user_row.role) == "student"
    guardian_required = is_student and profile_row and profile_row.class_level in (9, 10)
    guardian_status = None
    if guardian_required:
        guardian_row = db.execute(
            text("SELECT status FROM guardian_link WHERE student_id = :uid AND status = 'verified'"),
            {"uid": user_id},
        ).first()
        guardian_status = "verified" if guardian_row else None

    # Check 2FA status
    two_factor_row = db.execute(
        text("SELECT status FROM two_factor_enrollment WHERE user_id = :uid"),
        {"uid": user_id},
    ).first()
    two_factor_active = two_factor_row and str(two_factor_row.status) == "active"

    subscription_status = None
    if is_student:
        sub_row = db.execute(
            text("SELECT status FROM subscription WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()
        subscription_status = str(sub_row.status) if sub_row else None

    onboarding_state = derive_onboarding_state(
        email_verified=True,
        two_factor_active=two_factor_active,
        is_student=is_student,
        guardian_required=guardian_required,
        guardian_status=guardian_status,
        subscription_status=subscription_status,
    )

    return {
        "email_verified": True,
        "onboarding_state": onboarding_state,
        "access_token": access_token,
        "expires_in": expires_in,
        "enrollment_token": enrollment_plain,
    }


def resend_email_verification(db: Session, payload) -> None:
    """
    POST /auth/email/resend

    Resends the email verification link. Constant-time whether or not the
    address exists (prevents enumeration).
    """
    # Look up user (constant-time: dummy hash if not found)
    user_row = db.execute(
        text("SELECT id, email, email_verified_at FROM app.lookup_user_for_login(:email)"),
        {"email": payload.email},
    ).first()

    # Dummy verify for constant-time (whether found or not)
    verify_password("dummy", _dummy_password_hash())

    if user_row and not user_row.email_verified_at:
        # Issue new email_verify token
        settings = get_settings()
        verify_plain = issue_challenge_token(
            db,
            user_row.id,
            kind=TokenKind.email_verify,
            ttl_seconds=3600,  # 1 hour
        )

        # Send email
        from app.auth.email import get_email_sender
        from app.auth.email_templates import build_verification_url, verification_email

        url = build_verification_url(verify_plain)
        subject, html = verification_email(url)
        get_email_sender().send(user_row.email, subject, html)


def forgot_password(db: Session, payload) -> None:
    """
    POST /auth/password/forgot

    Initiates password reset. Constant-time whether or not the address exists
    (prevents enumeration).
    """
    # Look up user (constant-time: dummy hash if not found)
    user_row = db.execute(
        text("SELECT id, email, email_verified_at FROM app.lookup_user_for_login(:email)"),
        {"email": payload.email},
    ).first()

    # Dummy verify for constant-time (whether found or not)
    verify_password("dummy", _dummy_password_hash())

    if user_row and user_row.email_verified_at:
        # Issue password_reset token
        reset_plain = issue_challenge_token(
            db,
            user_row.id,
            kind=TokenKind.password_reset,
            ttl_seconds=3600,  # 1 hour
        )

        # Send email
        from app.auth.email import get_email_sender
        from app.auth.email_templates import build_password_reset_url, password_reset_email

        url = build_password_reset_url(reset_plain)
        subject, html = password_reset_email(url)
        get_email_sender().send(user_row.email, subject, html)


def reset_password(db: Session, payload) -> None:
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
        # Check if token exists but is expired
        token_check = db.execute(
            text("""
                SELECT id FROM auth_token
                WHERE token_hash = :hash AND kind = 'password_reset'
            """),
            {"hash": hash_token(payload.token)},
        ).first()

        if token_check:
            token_row = db.execute(
                text("SELECT expires_at FROM auth_token WHERE id = :id"),
                {"id": token_check.id},
            ).first()
            if token_row.expires_at < datetime.now(timezone.utc):
                raise token_expired()

        raise invalid_token()


def two_factor_regenerate_backup_codes(db: Session, user_id: uuid.UUID) -> dict:
    """
    POST /auth/2fa/backup-codes

    Regenerates backup codes. Requires active 2FA enrollment. Invalidates
    the old set and generates 10 new codes.

    This endpoint is authenticated (requires access_token).
    """
    # Bind user to transaction
    set_current_user_id(db, user_id)

    # Check 2FA is active
    enrollment = db.execute(
        text("SELECT status FROM two_factor_enrollment WHERE user_id = :uid"),
        {"uid": user_id},
    ).first()

    if not enrollment or str(enrollment.status) != "active":
        raise forbidden_scope("2FA is not active; enroll first")

    # Generate 10 new backup codes
    from app.auth.backup_codes import generate_backup_codes, hash_backup_code
    codes = generate_backup_codes(10)
    code_hashes = [hash_backup_code(c) for c in codes]

    # Replace backup codes (deletes old set, inserts new set)
    db.execute(
        text("SELECT app.replace_backup_codes(:uid, :hashes)"),
        {"uid": user_id, "hashes": code_hashes},
    )

    # Audit log
    db.execute(
        text("""
            INSERT INTO audit_log (user_id, action, ip_address)
            VALUES (:uid, 'backup_codes_regenerated', :ip)
        """),
        {"uid": user_id, "ip": None},
    )

    return {"backup_codes": codes}
