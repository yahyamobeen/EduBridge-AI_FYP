"""
Keyset cursors for the classroom feeds. A malformed cursor is the client's bad
input and must be a 400 VALIDATION_ERROR — never a 500 from a decode error.
"""

import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.classroom.pagination import decode_cursor, encode_cursor
from app.core.errors import AppError


def _b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode()


class TestCursor:
    def test_round_trip(self):
        at, row_id = datetime(2026, 10, 4, 12, 30, 15, 123456, tzinfo=UTC), uuid4()
        assert decode_cursor(encode_cursor(at, row_id)) == (at, row_id)

    @pytest.mark.parametrize(
        "cursor",
        [
            "not base64 !!",
            _b64("no-separator"),
            _b64("2026-10-04T12:00:00+00:00|not-a-uuid"),
            _b64(f"yesterday|{uuid4()}"),
            # A naive timestamp would compare against `publish_at` in the
            # SERVER's zone — refused rather than guessed.
            _b64(f"2026-10-04T12:00:00|{uuid4()}"),
        ],
    )
    def test_malformed_cursor_is_a_validation_error(self, cursor):
        with pytest.raises(AppError) as caught:
            decode_cursor(cursor)
        assert caught.value.code == "VALIDATION_ERROR"
        assert "cursor" in caught.value.details["fields"]
