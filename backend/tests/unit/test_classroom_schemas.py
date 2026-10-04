"""
Classroom request schemas — the bounds that turn a would-be database CHECK
violation (a 500) into a readable 400.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.classroom.schemas import JoinRequest, SpaceCreateRequest, SpaceUpdateRequest
from app.core.errors import AppError


class TestSpaceCreateRequest:
    def test_title_is_stripped(self):
        assert (
            SpaceCreateRequest(title="  Physics 11-A  ", subject_id=uuid4()).title == "Physics 11-A"
        )

    def test_whitespace_title_is_refused(self):
        # Passes min_length=1, and would otherwise reach ck_space_title as a 500.
        with pytest.raises(ValidationError):
            SpaceCreateRequest(title="   ", subject_id=uuid4())

    def test_title_is_bounded_like_the_check_constraint(self):
        with pytest.raises(ValidationError):
            SpaceCreateRequest(title="x" * 121, subject_id=uuid4())


class TestSpaceUpdateRequest:
    def test_empty_update_is_refused(self):
        with pytest.raises(AppError) as caught:
            SpaceUpdateRequest().validate_at_least_one_field()
        assert caught.value.code == "VALIDATION_ERROR"

    def test_status_alone_is_enough(self):
        SpaceUpdateRequest(status="archived").validate_at_least_one_field()

    def test_unknown_status_is_refused(self):
        with pytest.raises(ValidationError):
            SpaceUpdateRequest(status="deleted")


class TestJoinRequest:
    def test_code_is_bounded(self):
        with pytest.raises(ValidationError):
            JoinRequest(code="A" * 33)


class TestAnnouncementRequests:
    def test_body_is_stripped_and_blank_refused(self):
        from app.classroom.schemas import AnnouncementCreateRequest

        assert AnnouncementCreateRequest(body="  Test tomorrow  ").body == "Test tomorrow"
        with pytest.raises(ValidationError):
            AnnouncementCreateRequest(body="   ")

    def test_a_schedule_without_a_time_zone_is_refused(self):
        # "14:30" alone is ambiguous between the browser's zone and the server's.
        from app.classroom.schemas import AnnouncementCreateRequest

        with pytest.raises(ValidationError):
            AnnouncementCreateRequest(body="x", publish_at="2026-10-05T14:30:00")
        AnnouncementCreateRequest(body="x", publish_at="2026-10-05T14:30:00+05:00")

    def test_body_is_bounded_like_the_check_constraint(self):
        from app.classroom.schemas import AnnouncementCreateRequest

        with pytest.raises(ValidationError):
            AnnouncementCreateRequest(body="x" * 5001)

    def test_empty_update_is_refused(self):
        from app.classroom.schemas import AnnouncementUpdateRequest

        with pytest.raises(AppError):
            AnnouncementUpdateRequest().validate_at_least_one_field()
