from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    BoardCode,
    GuardianStatus,
    LanguageCode,
    MediumCode,
    StudentGroup,
    TokenKind,
    TwoFactorMethod,
    TwoFactorStatus,
    UserRole,
    UserStatus,
)

_PG_ENUM_NAMES: dict[type, str] = {
    BoardCode: "board_code",
    GuardianStatus: "guardian_status",
    LanguageCode: "language_code",
    MediumCode: "medium_code",
    StudentGroup: "student_group",
    TokenKind: "token_kind",
    TwoFactorMethod: "two_factor_method",
    TwoFactorStatus: "two_factor_status",
    UserRole: "user_role",
    UserStatus: "user_status",
}


def _pg_enum(py_enum: type) -> SAEnum:
    return SAEnum(
        py_enum,
        name=_PG_ENUM_NAMES[py_enum],
        values_callable=lambda e: [m.value for m in e],
    )


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(_pg_enum(UserRole), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        _pg_enum(UserStatus), nullable=False, default=UserStatus.active
    )
    full_name: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("ix_app_user_role", "role", postgresql_where=text("deleted_at IS NULL")),
    )


class StudentProfile(Base):
    __tablename__ = "student_profile"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    board: Mapped[BoardCode] = mapped_column(_pg_enum(BoardCode), nullable=False)
    class_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    student_group: Mapped[StudentGroup] = mapped_column(_pg_enum(StudentGroup), nullable=False)
    medium: Mapped[MediumCode] = mapped_column(_pg_enum(MediumCode), nullable=False)
    language_pref: Mapped[LanguageCode] = mapped_column(
        _pg_enum(LanguageCode), nullable=False, default=LanguageCode.en
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "class_level BETWEEN 9 AND 12",
            name="ck_student_class_range",
        ),
        CheckConstraint(
            "(class_level IN (9,10) AND student_group IN ('science','computer'))"
            " OR (class_level IN (11,12) AND student_group IN "
            "('pre_medical','pre_engineering','ics'))",
            name="ck_group_matches_class",
        ),
        Index("ix_student_board_class", "board", "class_level", "student_group"),
    )


class TeacherProfile(Base):
    __tablename__ = "teacher_profile"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    institution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class ParentProfile(Base):
    __tablename__ = "parent_profile"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class AdminProfile(Base):
    __tablename__ = "admin_profile"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class GuardianLink(Base):
    __tablename__ = "guardian_link"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    parent_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[GuardianStatus] = mapped_column(
        _pg_enum(GuardianStatus), nullable=False, default=GuardianStatus.pending
    )
    verification_method: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("parent_id <> student_id", name="ck_guardian_not_self"),
        CheckConstraint(
            "status <> 'verified' OR verified_at IS NOT NULL",
            name="ck_guardian_verified_has_ts",
        ),
        UniqueConstraint("parent_id", "student_id", name="uq_guardian_pair"),
        Index("ix_guardian_parent", "parent_id"),
        Index(
            "ix_guardian_student_verified",
            "student_id",
            postgresql_where=text("status = 'verified'"),
        ),
    )


class AuthToken(Base):
    __tablename__ = "auth_token"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TokenKind] = mapped_column(_pg_enum(TokenKind), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index(
            "ix_auth_token_user_kind",
            "user_id",
            "kind",
            postgresql_where=text("revoked = false"),
        ),
    )


class TwoFactorEnrollment(Base):
    __tablename__ = "two_factor_enrollment"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    method: Mapped[TwoFactorMethod] = mapped_column(_pg_enum(TwoFactorMethod), nullable=False)
    status: Mapped[TwoFactorStatus] = mapped_column(
        _pg_enum(TwoFactorStatus), nullable=False, default=TwoFactorStatus.pending
    )
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_used_counter: Mapped[int | None] = mapped_column(BigInteger)
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("failed_attempts >= 0", name="ck_failed_attempts_nonneg"),
        CheckConstraint(
            "method <> 'totp' OR totp_secret_encrypted IS NOT NULL",
            name="ck_totp_requires_secret",
        ),
        CheckConstraint(
            "method <> 'email_otp' OR totp_secret_encrypted IS NULL",
            name="ck_email_otp_has_no_secret",
        ),
        CheckConstraint(
            "status <> 'active' OR confirmed_at IS NOT NULL",
            name="ck_active_is_confirmed",
        ),
        Index(
            "ix_2fa_locked",
            "locked_until",
            postgresql_where=text("locked_until IS NOT NULL"),
        ),
    )


class TwoFactorBackupCode(Base):
    __tablename__ = "two_factor_backup_code"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("user_id", "code_hash", name="uq_backup_code"),
        Index(
            "ix_backup_code_unused",
            "user_id",
            postgresql_where=text("used_at IS NULL"),
        ),
    )
