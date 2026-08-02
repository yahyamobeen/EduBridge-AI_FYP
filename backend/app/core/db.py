from collections.abc import Generator
from uuid import UUID

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

engine: Engine = create_engine(_settings.database_url, pool_pre_ping=True)
service_engine: Engine = create_engine(_settings.service_role_database_url, pool_pre_ping=True)

_session_options = {"autoflush": False, "expire_on_commit": False, "future": True}
SessionLocal = sessionmaker(bind=engine, **_session_options)
ServiceSessionLocal = sessionmaker(bind=service_engine, **_session_options)


def set_current_user_id(session: Session, user_id: UUID | str | None) -> None:
    if user_id is None:
        return
    parsed = UUID(str(user_id))
    session.execute(text(f"SET LOCAL app.current_user_id = '{parsed}'"))


def get_db(request: Request) -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        user_id = getattr(request.state, "user_id", None)
        set_current_user_id(session, user_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_service_db() -> Generator[Session, None, None]:
    session = ServiceSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
