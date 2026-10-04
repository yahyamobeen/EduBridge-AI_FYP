from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.core.errors import validation_error
from app.models.enums import BoardCode, SpaceStatus


def _strip_nonempty(value: str) -> str:
    """
    `min_length` counts whitespace, so "   " passes it — and then hits the
    `ck_space_title` CHECK as a 500. Refused here as a readable 400 instead.
    """
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class SubjectRef(BaseModel):
    id: UUID
    name: str
    board: BoardCode
    class_level: int


class SpaceSummary(BaseModel):
    id: UUID
    title: str
    status: SpaceStatus
    subject: SubjectRef
    owner_name: str | None
    viewer_role: Literal["owner", "member"]
    # False for an owner whose subject scope an administrator revoked: the row
    # stays visible so the interface can explain why nothing else is.
    can_manage: bool
    member_count: int | None  # owner only
    joined_at: datetime | None  # member only


class SpaceListResponse(BaseModel):
    spaces: list[SpaceSummary]


class SpaceDetail(SpaceSummary):
    # The live code, for a scoped owner only. `join_code_owner_read` returns no
    # row to anyone else, so a member gets None from the DATABASE, not from a
    # check in this file.
    join_code: str | None


class SpaceCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    subject_id: UUID

    # Named WITHOUT a leading underscore: Pydantic treats `_name` class
    # attributes as private, and a validator registered that way can be skipped.
    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return _strip_nonempty(value)


class SpaceUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    status: SpaceStatus | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        return None if value is None else _strip_nonempty(value)

    def validate_at_least_one_field(self) -> None:
        """An empty PATCH is a 400, not a silent 200 (the MeUpdateRequest rule)."""
        if self.title is None and self.status is None:
            raise validation_error(
                message="Provide at least one field to update.",
                details={"fields": {"title": "Provide this or status."}},
            )


class JoinCodeRequest(BaseModel):
    action: Literal["rotate", "disable"]


class JoinCodeResponse(BaseModel):
    join_code: str | None


class JoinRequest(BaseModel):
    # Generous: the database normalises case, spaces and dashes, and a student
    # copying "ABCD-EFGH " off a board is not making a mistake.
    code: str = Field(min_length=1, max_length=32)


class JoinResponse(BaseModel):
    space_id: UUID
    already_member: bool


class Person(BaseModel):
    user_id: UUID
    full_name: str | None


class Member(Person):
    joined_at: datetime
    # Present only in the owner's view; None for members (app.space_people).
    muted: bool | None = None


class PeopleResponse(BaseModel):
    owner: Person
    members: list[Member]


class SubjectOption(BaseModel):
    id: UUID
    name: str
    groups: list[str]


class SubjectsResponse(BaseModel):
    subjects: list[SubjectOption]


# ── Phase 3: announcements ──────────────────────────────────────────────────


class AnnouncementCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    # None = publish now. A value must carry a time zone (AwareDatetime): a
    # naive "14:30" is ambiguous between the browser's zone and the server's.
    # The service checks it is in the future and at most a year ahead, against
    # the DATABASE clock.
    publish_at: AwareDatetime | None = None

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        return _strip_nonempty(value)


class AnnouncementUpdateRequest(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    publish_at: AwareDatetime | None = None

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str | None) -> str | None:
        return None if value is None else _strip_nonempty(value)

    def validate_at_least_one_field(self) -> None:
        if self.body is None and self.publish_at is None:
            raise validation_error(
                message="Provide at least one field to update.",
                details={"fields": {"body": "Provide this or publish_at."}},
            )


class Announcement(BaseModel):
    id: UUID
    body: str
    author_id: UUID
    publish_at: datetime
    # True only in the owner's view: a member can never read a scheduled post
    # (announcement_member_read), so for them this is always False.
    scheduled: bool
    created_at: datetime
    updated_at: datetime


class AnnouncementPage(BaseModel):
    items: list[Announcement]
    # Opaque; pass back as ?cursor= for the next (older) page. None at the end.
    next_cursor: str | None
