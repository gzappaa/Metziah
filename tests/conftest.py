# tests/conftest.py
import pytest
import psycopg

from config import settings


@pytest.fixture
def conn():
    """Real connection to the test DB, rolled back at teardown
    so nothing persists after a test runs."""
    connection = psycopg.connect(
        host=settings.PGHOST,
        port=settings.PGPORT,
        user=settings.PGUSER,
        password=settings.PGPASSWORD,
        dbname=settings.PGDATABASE,
    )
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def real_store(conn):
    """Grab whatever store is already loaded -- we don't care which
    one, just that chain_id/store_id are real and exist in the DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT chain_id, id, store_id FROM stores LIMIT 1")
        row = cur.fetchone()
        assert row is not None, "test DB has no stores loaded"
        return {
            "chain_id": row[0],
            "store_id_int": row[1],
            "store_id_text": row[2],
        }