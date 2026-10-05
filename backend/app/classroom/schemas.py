from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.classroom.status import WorkStatus
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


class FileMeta(BaseModel):
    """A stored file (classroom Phase 6). The object key never leaves the server."""

    id: UUID
    # Sanitised, with the extension forced to the detected type (files.py).
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class LinkMeta(BaseModel):
    """A link on a student's work (classroom Phase 6b). Always https (ck_sublink_url)."""

    id: UUID
    url: str
    created_at: datetime


class ViewLink(BaseModel):
    """
    A short-lived link that shows a file in the browser (classroom Phase 6b). A
    bearer pass until `expires_at`: handed out only after the file's row is read
    under RLS, and never logged.
    """

    url: str
    expires_at: datetime


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
    # Teacher attachments (Phase 6); a member sees them once the post is live.
    attachments: list[FileMeta] = []


class AnnouncementPage(BaseModel):
    items: list[Announcement]
    # Opaque; pass back as ?cursor= for the next (older) page. None at the end.
    next_cursor: str | None


# ── Phase 4: assignments, submissions and grades ───────────────────────────


class ChapterRef(BaseModel):
    id: UUID
    number: int
    title: str


class ChaptersResponse(BaseModel):
    chapters: list[ChapterRef]


class AssignmentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=10000)
    # Both must carry a time zone, for the reason given on AnnouncementCreateRequest.
    due_at: AwareDatetime | None = None
    points: int | None = Field(default=None, ge=1, le=1000)
    # Must belong to the classroom's subject — checked by the service, and held
    # by a composite foreign key in the database regardless.
    chapter_id: UUID | None = None
    publish_at: AwareDatetime | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return _strip_nonempty(value)

    @field_validator("instructions")
    @classmethod
    def strip_instructions(cls, value: str) -> str:
        return value.strip()


# The fields a PATCH may clear by sending null. Sending null for any other
# field is a 400: there is no such thing as an assignment without a title.
_CLEARABLE = frozenset({"due_at", "points", "chapter_id"})


class AssignmentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=10000)
    due_at: AwareDatetime | None = None
    points: int | None = Field(default=None, ge=1, le=1000)
    chapter_id: UUID | None = None
    publish_at: AwareDatetime | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        return None if value is None else _strip_nonempty(value)

    @field_validator("instructions")
    @classmethod
    def strip_instructions(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()

    def changes(self) -> dict[str, Any]:
        """
        Only the fields the client SENT (`model_fields_set`), so `{"due_at": null}`
        clears the due date while omitting `due_at` leaves it alone.
        """
        sent = {name: getattr(self, name) for name in self.model_fields_set}
        if not sent:
            raise validation_error(
                message="Provide at least one field to update.",
                details={"fields": {"title": "Provide at least one field."}},
            )
        for name, value in sent.items():
            if value is None and name not in _CLEARABLE:
                raise validation_error(
                    message="This field cannot be empty.",
                    details={"fields": {name: "This field cannot be empty."}},
                )
        return sent


class MySubmission(BaseModel):
    """The calling student's own work. `grade` and `feedback` only once returned."""

    body: str
    turned_in_at: datetime | None
    status: WorkStatus
    grade: float | None
    feedback: str | None
    returned_at: datetime | None
    # The student's own uploaded files (Phase 6) and links (Phase 6b).
    files: list[FileMeta] = []
    links: list[LinkMeta] = []


class AssignmentSummary(BaseModel):
    id: UUID
    title: str
    due_at: datetime | None
    points: int | None
    chapter: ChapterRef | None
    publish_at: datetime
    # True only in the owner's view, as for announcements.
    scheduled: bool
    # Member view only (None for the owner).
    my_status: WorkStatus | None = None
    my_grade: float | None = None
    # Owner view only (None for a member): turned-in work of ACTIVE members.
    turned_in_count: int | None = None


class AssignmentPage(BaseModel):
    items: list[AssignmentSummary]
    next_cursor: str | None


class AssignmentDetail(AssignmentSummary):
    space_id: UUID
    instructions: str
    created_at: datetime
    updated_at: datetime
    # Member view only.
    my_submission: MySubmission | None = None
    # Teacher attachments (Phase 6).
    attachments: list[FileMeta] = []


class SubmissionDraftRequest(BaseModel):
    # Links are their own rows since Phase 6b (`LinkRequest`); a stale client's
    # `link_url` is ignored, never stored.
    body: str = Field(default="", max_length=20000)


class LinkRequest(BaseModel):
    url: str = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def https_only(cls, value: str) -> str:
        """
        `https://` and nothing else — never `javascript:`, never `http:`. The
        database repeats the rule (ck_sublink_url), and the client renders the
        link with rel="noopener noreferrer".
        """
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.netloc or any(ch.isspace() for ch in value):
            raise ValueError("must be a full https:// link")
        return value


class GradeRequest(BaseModel):
    # None = feedback only. Bounded above by the assignment's points, which only
    # the database knows at the moment of saving (app.save_grade).
    grade: Decimal | None = Field(default=None, ge=0, le=1000, max_digits=6, decimal_places=2)
    feedback: str = Field(default="", max_length=5000)
    # Returning is one-way: once a student can see a grade, they always can.
    return_to_student: bool = False

    @field_validator("feedback")
    @classmethod
    def strip_feedback(cls, value: str) -> str:
        return value.strip()


class SubmissionRow(BaseModel):
    """One row of the teacher's table — every ACTIVE member, submitted or not."""

    student_id: UUID
    full_name: str | None
    status: WorkStatus
    turned_in_at: datetime | None
    grade: float | None
    returned_at: datetime | None
    # A grade row exists — saved as a draft or returned. Locks the student's work.
    graded: bool


class SubmissionsResponse(BaseModel):
    rows: list[SubmissionRow]


class StudentWork(SubmissionRow):
    # None until the student turns the work in: a draft is theirs alone.
    body: str | None
    feedback: str
    # Empty until turned in, for the same reason (subfile_teacher_read,
    # link_teacher_read).
    files: list[FileMeta] = []
    links: list[LinkMeta] = []


# ── Phase 5: the calendar ───────────────────────────────────────────────────


class CalendarItem(BaseModel):
    kind: Literal["due", "scheduled_assignment", "scheduled_announcement"]
    # The deadline for `due`; the moment it goes live for a scheduled post.
    at: datetime
    space_id: UUID
    space_title: str
    # The assignment or announcement this entry is about.
    ref_id: UUID
    # An announcement's first 80 characters, whitespace collapsed.
    title: str
    # A student's own derived status, on `due` entries only.
    my_status: WorkStatus | None = None


class CalendarResponse(BaseModel):
    items: list[CalendarItem]
    # True when the range held more than the 500-entry cap.
    truncated: bool
