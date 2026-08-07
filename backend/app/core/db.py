from collections.abc import Generator
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

engine: Engine = create_engine(_settings.database_url, pool_pre_ping=True)

# ----------------------------------------------------------------------------
# The service engine exists for BACKGROUND JOBS ONLY — the ETL, the trial
# sweeper, reconciliation (tdd.md §6.8). It connects as a role that bypasses
# Row Level Security, so anything using it runs with every one of the policies
# switched off.
#
# NOTHING IN A REQUEST PATH MAY DEPEND ON IT. The pre-authentication lookups
# that genuinely cannot satisfy owner-scoped RLS — login and refresh — go
# through the narrow SECURITY DEFINER functions added in migration
# 20260802140000, which expose only the columns those flows need rather than
# the whole database.
# ----------------------------------------------------------------------------
service_engine: Engine = create_engine(_settings.service_role_database_url, pool_pre_ping=True)

_session_options = {"autoflush": False, "expire_on_commit": False, "future": True}
SessionLocal = sessionmaker(bind=engine, **_session_options)
ServiceSessionLocal = sessionmaker(bind=service_engine, **_session_options)


def set_current_user_id(session: Session, user_id: UUID | str) -> None:
    """
    Bind the acting user for this TRANSACTION — what every RLS policy reads
    through `app.current_user_id()`.

    Two properties here are load-bearing:

    * `set_config(..., is_local => true)` is the parameterised equivalent of
      `SET LOCAL`, which cannot take a bind parameter and so has to be built as
      a string. This is the line every other module will copy; it should be the
      safe form.

    * It is scoped to the transaction. A `commit()` in the middle of a request
      ENDS that transaction and silently discards the setting; every query after
      it on the same session then runs with no user bound and returns zero rows,
      with no error raised anywhere. If you are ever chasing a "the query
      returns nothing but the row is definitely there" bug, look for a stray
      commit first.

    Never called with None. "Unset" is the fail-closed default and must stay
    reachable only by not calling this at all.
    """
    parsed = UUID(str(user_id))
    session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(parsed)},
    )


def get_db() -> Generator[Session, None, None]:
    """
    A session with NO user bound, so every owner-scoped policy denies.

    That is the correct default for an unauthenticated endpoint. Registration is
    the one caller that binds a user itself: the profile row it inserts is
    owner-scoped (`student_profile_write` is
    `WITH CHECK (user_id = app.current_user_id())`) and there is no session yet
    to bind from.

    Authenticated routes use `app.auth.dependencies.authenticated` instead,
    which binds the user from the verified token before yielding.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_service_db() -> Generator[Session, None, None]:
    """
    RLS-BYPASSING session. Background jobs only — see the note on
    `service_engine`. Reaching for this from a route almost always means the
    real answer is a narrow SECURITY DEFINER function instead.
    """
    session = ServiceSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class UnsafeDatabaseRoleError(RuntimeError):
    """The application is connected as a role that can bypass RLS."""


class DatabaseUnreachableError(RuntimeError):
    """
    The database could not be reached at startup.

    DISTINCT FROM `UnsafeDatabaseRoleError` on purpose. Both stop the app, but
    they mean opposite things: one is "the configuration is dangerous", the
    other is "nothing is wrong with the configuration, the network is down".
    Collapsing them into one traceback sent people looking for a credentials bug
    when their hotspot had dropped a DNS lookup.
    """


def assert_backend_role_cannot_bypass_rls() -> None:
    """
    Refuse to start if the primary connection can bypass Row Level Security.

    "Connect as app_backend, never as postgres" was a documented rule that
    nothing enforced — and it is a rule whose violation is invisible: the
    application works, every test passes, and the entire authorization layer is
    simply inert. A superuser, or any role with `rolbypassrls`, has that effect.
    Cheap to check once at boot; impossible to notice otherwise.

    Being unable to CHECK is also a refusal to start — an unverified role is not
    a safe one — but it is reported as its own error, because "cannot resolve
    the host" and "you are connected as postgres" need completely different
    responses from whoever is reading the log.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one_or_none()
    except OperationalError as exc:
        # The useful part is the driver's own message; the SQLAlchemy wrapper
        # around it adds five frames of pool internals and no information.
        detail = str(exc.orig or exc).strip().splitlines()[0]
        raise DatabaseUnreachableError(
            # ASCII only: this goes to a terminal, and the Windows console
            # renders an em dash as a replacement character under cp1252.
            f"Cannot reach the database: {detail}\n"
            "  This is a connectivity or DATABASE_URL problem, not a code problem.\n"
            "  Check the network first (a dropped DNS lookup looks exactly like this),\n"
            "  then that DATABASE_URL host and port are right, and that the Supabase\n"
            "  project is not paused."
        ) from exc

    if row is None:
        raise UnsafeDatabaseRoleError(
            "Could not determine the current database role; refusing to start."
        )

    is_super, bypasses_rls = row
    if is_super or bypasses_rls:
        raise UnsafeDatabaseRoleError(
            "DATABASE_URL connects as a role that bypasses Row Level Security "
            f"(rolsuper={is_super}, rolbypassrls={bypasses_rls}). Every policy "
            "would be inert. Connect as app_backend."
        )
