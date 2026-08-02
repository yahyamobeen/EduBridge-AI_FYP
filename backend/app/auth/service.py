from datetime import UTC, datetime
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.schemas import GROUP_LABELS, LoginRequest, RegisterRequest
from app.auth.security import create_access_token, hash_password, verify_password
from app.auth.tokens import issue_pending_token, revoke_user_tokens, rotate_refresh_token
from app.core.config import get_settings
from app.core.db import set_current_user_id
from app.core.errors import (
    email_already_registered,
    invalid_class_group,
    two_factor_locked,
    unauthenticated,
)
from app.models.enums import UserRole


def register(db: Session, payload: RegisterRequest) -> dict:
    try:
        payload.validate_student_group_for_class()
    except ValueError:
        raise invalid_class_group() from None

    new_id = uuid4()
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
    boards = db.execute(text("SELECT code, name FROM board ORDER BY code")).mappings().all()
    class_levels = (
        db.execute(text("SELECT DISTINCT level FROM class_level ORDER BY level")).scalars().all()
    )

    groups_by_class = {
        "9": [{"code": g, "label": GROUP_LABELS[g]} for g in ("science", "computer")],
        "10": [{"code": g, "label": GROUP_LABELS[g]} for g in ("science", "computer")],
        "11": [
            {"code": g, "label": GROUP_LABELS[g]} for g in ("pre_medical", "pre_engineering", "ics")
        ],
        "12": [
            {"code": g, "label": GROUP_LABELS[g]} for g in ("pre_medical", "pre_engineering", "ics")
        ],
    }

    return {
        "boards": [{"code": b.code, "name": b.name} for b in boards],
        "class_levels": list(class_levels),
        "groups_by_class": groups_by_class,
        "mediums": ["en", "ur"],
        "languages": ["en", "ur", "roman_ur"],
    }


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"{local[0]}***@{domain}" if local else f"***@{domain}"
    return f"{local[0]}***@{domain}"


def login(db: Session, payload: LoginRequest) -> dict:
    row = (
        db.execute(
            text(
                "SELECT id, email, password_hash, role, email_verified_at, status "
                "FROM app_user WHERE email = :email AND deleted_at IS NULL"
            ),
            {"email": str(payload.email).lower()},
        )
        .mappings()
        .one_or_none()
    )

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise unauthenticated("Incorrect email or password.")
    if row["status"] != "active":
        raise unauthenticated("Incorrect email or password.")

    twofa = (
        db.execute(
            text(
                "SELECT method, status, locked_until FROM two_factor_enrollment "
                "WHERE user_id = :uid"
            ),
            {"uid": row["id"]},
        )
        .mappings()
        .one_or_none()
    )

    if twofa is not None and twofa["locked_until"] is not None:
        locked_until = twofa["locked_until"]
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
        if locked_until > datetime.now(UTC):
            raise two_factor_locked(locked_until.isoformat())

    if row["email_verified_at"] is None:
        return {"status": "email_verification_required", "email": _mask_email(row["email"])}

    settings = get_settings()
    if twofa is None or twofa["status"] != "active":
        token, _ = issue_pending_token(
            db, row["id"], ttl_seconds=settings.enrollment_token_ttl_seconds
        )
        return {
            "status": "two_factor_enrollment_required",
            "enrollment_token": token,
            "expires_in": settings.enrollment_token_ttl_seconds,
        }

    token, _ = issue_pending_token(db, row["id"], ttl_seconds=settings.pending_token_ttl_seconds)
    return {
        "status": "two_factor_required",
        "pending_token": token,
        "method": twofa["method"],
        "expires_in": settings.pending_token_ttl_seconds,
    }


def refresh(db: Session, refresh_token: str) -> dict:
    rotated = rotate_refresh_token(db, refresh_token)
    if rotated is None:
        raise unauthenticated("Invalid or expired refresh token.")
    new_plain, new_row = rotated
    access_token, expires_in = create_access_token(new_row.user_id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "refresh_token": new_plain,
    }


def logout(db: Session, user_id: UUID) -> None:
    revoke_user_tokens(db, user_id, kind="refresh")


def me(db: Session, user_id: UUID) -> dict:
    row = (
        db.execute(
            text(
                "SELECT id, email, full_name, role, email_verified_at "
                "FROM app_user WHERE id = :uid AND deleted_at IS NULL"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise unauthenticated()

    profile = None
    if row["role"] == "student":
        profile = (
            db.execute(
                text(
                    "SELECT board, class_level, student_group, medium, language_pref "
                    "FROM student_profile WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            .mappings()
            .one_or_none()
        )

    twofa = (
        db.execute(
            text("SELECT method, status FROM two_factor_enrollment WHERE user_id = :uid"),
            {"uid": user_id},
        )
        .mappings()
        .one_or_none()
    )

    guardian_required = False
    guardian_status: str = "none"
    if profile is not None and profile["class_level"] in (9, 10):
        guardian_required = True
        glink = (
            db.execute(
                text(
                    "SELECT status FROM guardian_link WHERE student_id = :uid "
                    "AND status IN ('pending','verified')"
                ),
                {"uid": user_id},
            )
            .scalars()
            .first()
        )
        guardian_status = glink or "none"

    if row["email_verified_at"] is None:
        onboarding_state = "email_verification_pending"
    elif twofa is None or twofa["status"] != "active":
        onboarding_state = "two_factor_enrollment_pending"
    elif guardian_required and guardian_status != "verified":
        onboarding_state = "guardian_link_pending"
    else:
        onboarding_state = "active"

    return {
        "user_id": str(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "onboarding_state": onboarding_state,
        "email_verified": row["email_verified_at"] is not None,
        "two_factor": {
            "enabled": twofa is not None and twofa["status"] == "active",
            "method": (
                twofa["method"] if twofa is not None and twofa["status"] == "active" else None
            ),
        },
        "profile": dict(profile) if profile else None,
        "guardian": {"required": guardian_required, "status": guardian_status},
    }
