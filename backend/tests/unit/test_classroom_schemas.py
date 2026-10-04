"""
Classroom request schemas — the bounds that turn a would-be database CHECK
violation (a 500) into a readable 400.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.classroom.schemas import (
    AssignmentCreateRequest,
    AssignmentUpdateRequest,
    GradeRequest,
    JoinRequest,
    SpaceCreateRequest,
    SpaceUpdateRequest,
    SubmissionDraftRequest,
)
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


class TestAssignmentRequests:
    def test_title_is_stripped_and_blank_refused(self):
        assert AssignmentCreateRequest(title="  Lab 1 ").title == "Lab 1"
        with pytest.raises(ValidationError):
            AssignmentCreateRequest(title="   ")

    def test_points_are_bounded_like_the_check_constraint(self):
        for bad in (0, 1001):
            with pytest.raises(ValidationError):
                AssignmentCreateRequest(title="x", points=bad)

    def test_a_due_date_without_a_time_zone_is_refused(self):
        with pytest.raises(ValidationError):
            AssignmentCreateRequest(title="x", due_at="2026-10-10T17:00:00")

    def test_update_sends_only_what_the_client_sent(self):
        assert AssignmentUpdateRequest(title="New").changes() == {"title": "New"}

    def test_update_may_clear_the_optional_fields(self):
        sent = AssignmentUpdateRequest(due_at=None, points=None, chapter_id=None).changes()
        assert sent == {"due_at": None, "points": None, "chapter_id": None}

    @pytest.mark.parametrize("field", ["title", "instructions", "publish_at"])
    def test_update_may_not_clear_a_required_field(self, field):
        with pytest.raises(AppError) as caught:
            AssignmentUpdateRequest(**{field: None}).changes()
        assert caught.value.details["fields"] == {field: "This field cannot be empty."}

    def test_empty_update_is_refused(self):
        with pytest.raises(AppError):
            AssignmentUpdateRequest().changes()


class TestSubmissionDraftRequest:
    def test_an_https_link_is_kept(self):
        link = "https://example.com/my-work?id=1"
        assert SubmissionDraftRequest(link_url=f"  {link} ").link_url == link

    def test_a_blank_link_means_none(self):
        assert SubmissionDraftRequest(link_url="  ").link_url is None

    @pytest.mark.parametrize(
        "bad",
        [
            "http://example.com",  # not https
            "javascript:alert(1)",  # the reason this check exists
            "https://",  # no host
            "https://exa mple.com",  # whitespace
            "example.com",  # no scheme
        ],
    )
    def test_anything_but_a_full_https_link_is_refused(self, bad):
        with pytest.raises(ValidationError):
            SubmissionDraftRequest(link_url=bad)


class TestGradeRequest:
    def test_two_decimal_places(self):
        assert GradeRequest(grade="9.5").grade == Decimal("9.5")
        with pytest.raises(ValidationError):
            GradeRequest(grade="9.555")

    def test_negative_is_refused(self):
        with pytest.raises(ValidationError):
            GradeRequest(grade=-1)

    def test_feedback_alone_is_allowed(self):
        assert GradeRequest(feedback=" Good start ").model_dump() == {
            "grade": None,
            "feedback": "Good start",
            "return_to_student": False,
        }
