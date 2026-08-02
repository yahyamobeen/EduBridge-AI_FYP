from uuid import uuid4

from sqlalchemy import text

from app.core.db import engine, set_current_user_id


def test_rls_fail_closed_unset_user_id():
    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM board")).scalar()
        assert count == 0


def test_rls_sees_rows_with_user_id_set():
    with engine.connect() as conn:
        conn.execute(text("BEGIN"))
        set_current_user_id(conn, uuid4())
        count = conn.execute(text("SELECT count(*) FROM board")).scalar()
        conn.execute(text("COMMIT"))
        assert count == 2


def test_rls_own_row_only():
    fake = str(uuid4())
    with engine.connect() as conn:
        conn.execute(text("BEGIN"))
        set_current_user_id(conn, fake)
        rows = conn.execute(text("SELECT id FROM app_user")).fetchall()
        conn.execute(text("COMMIT"))
        assert all(str(r[0]) == fake for r in rows)


def test_app_backend_has_no_bypass():
    with engine.connect() as conn:
        role = conn.execute(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar()
        assert role is False
