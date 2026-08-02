import pytest

from app.core.db import engine, service_engine


@pytest.fixture
def service_conn():
    conn = service_engine.connect()
    conn.begin()
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def app_backend_conn():
    conn = engine.connect()
    yield conn
    conn.rollback()
    conn.close()
