from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
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
from app.models.enums import BoardCode, ContentStrategy, StudentGroup

# ⚠️ `BoardCode` ADDED FIRST — `_pg_enum` looks its argument up here and raises
#    `KeyError` otherwise, so registering the mapping is a prerequisite for the
#    `Board.code` change below rather than a tidy-up alongside it.
_PG_ENUM_NAMES: dict[type, str] = {
    BoardCode: "board_code",
    ContentStrategy: "content_strategy",
    StudentGroup: "student_group",
}


def _pg_enum(py_enum: type) -> SAEnum:
    return SAEnum(
        py_enum,
        name=_PG_ENUM_NAMES[py_enum],
        values_callable=lambda e: [m.value for m in e],
    )


class Board(Base):
    __tablename__ = "board"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    # ⚠️ FINDING D14. Declared `Text` while the applied column is the `board_code`
    #    ENUM ('PCTB', 'STBB'). `StudentProfile.board` in `identity.py` already
    #    maps the same database type correctly, so the two models described one
    #    enum two different ways — and the `Text` one silently accepts any string
    #    the database would refuse.
    #
    #    The mismatch is invisible today because nothing queries this model:
    #    everything that runs is SQLAlchemy Core with hand-written `text()`.
    #    That is exactly why it is worth fixing now — the first ORM query written
    #    against `Board` would inherit a type that disagrees with the schema, and
    #    the failure would arrive far from this line.
    code: Mapped[BoardCode] = mapped_column(_pg_enum(BoardCode), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class ClassLevel(Base):
    __tablename__ = "class_level"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    board_id: Mapped[UUID] = mapped_column(
        ForeignKey("board.id", ondelete="RESTRICT"), nullable=False
    )
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("level BETWEEN 9 AND 12", name="ck_class_level_range"),
        UniqueConstraint("board_id", "level", name="uq_class_level"),
    )


class Subject(Base):
    __tablename__ = "subject"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    class_level_id: Mapped[UUID] = mapped_column(
        ForeignKey("class_level.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    content_strategy: Mapped[ContentStrategy] = mapped_column(
        _pg_enum(ContentStrategy), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("class_level_id", "name", name="uq_subject"),
        Index("ix_subject_class", "class_level_id"),
        Index("ix_subject_strategy", "content_strategy"),
    )


class SubjectGroup(Base):
    __tablename__ = "subject_group"

    subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("subject.id", ondelete="CASCADE"), primary_key=True
    )
    student_group: Mapped[StudentGroup] = mapped_column(_pg_enum(StudentGroup), primary_key=True)

    __table_args__ = (Index("ix_subject_group_grp", "student_group"),)


class Chapter(Base):
    __tablename__ = "chapter"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("subject.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("subject_id", "number", name="uq_chapter"),
        Index("ix_chapter_subject", "subject_id"),
    )


class Slo(Base):
    __tablename__ = "slo"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    chapter_id: Mapped[UUID] = mapped_column(
        ForeignKey("chapter.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from_year: Mapped[int | None] = mapped_column(SmallInteger)
    retired_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("chapter_id", "code", name="uq_slo"),
        Index(
            "ix_slo_chapter_active",
            "chapter_id",
            postgresql_where=text("retired_at IS NULL"),
        ),
    )


class TeacherSubjectScope(Base):
    __tablename__ = "teacher_subject_scope"

    teacher_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("subject.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_tss_subject", "subject_id"),)
