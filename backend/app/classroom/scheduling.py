"""
Scheduled publishing — the one check shared by announcements (Phase 3) and
assignments (Phase 4).

Hiding a scheduled post is the DATABASE's job (`publish_at <= now()` in each
member read policy; database.md invariant 10). What is left for the service is
refusing a time that makes no sense: the past, or further ahead than a year.

Compared against the DATABASE clock, never Python's — the 2026-08-17 session
work measured the two 1.1 s apart, and "is this in the future?" is exactly the
boundary that drifts.
"""

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import validation_error

MAX_SCHEDULE_AHEAD = timedelta(days=365)


def db_now(db: Session) -> datetime:
    return db.execute(text("SELECT now()")).scalar_one()


def check_schedule(db: Session, publish_at: datetime | None) -> None:
    """None means "publish now" and always passes."""
    if publish_at is None:
        return
    now = db_now(db)
    if publish_at <= now or publish_at > now + MAX_SCHEDULE_AHEAD:
        raise validation_error(
            message="Choose a future time within the next year.",
            details={"fields": {"publish_at": "Choose a future time within the next year."}},
        )
