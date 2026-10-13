"""
Keyset pagination for classroom feeds (tdd.md §7.1: "pagination via limit/cursor").

The cursor is the (timestamp, id) of the last row a page returned, opaque to
the client. Keyset rather than OFFSET because a feed that receives new posts
while someone pages through it would skip or repeat rows under an offset.

Pure: no database or settings imports, so it is unit-testable.
"""

import base64
import binascii
from datetime import datetime
from uuid import UUID

from app.core.errors import validation_error


def encode_cursor(at: datetime, row_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{at.isoformat()}|{row_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """A malformed cursor is the caller's bad input: 400, never a 500."""
    try:
        at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        parsed = datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            raise ValueError("cursor timestamp has no time zone")
        return parsed, UUID(row_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise validation_error(
            message="Invalid cursor.", details={"fields": {"cursor": "Invalid cursor."}}
        ) from None
