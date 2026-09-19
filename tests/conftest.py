import pytest
import psycopg

from config import settings


@pytest.fixture
def conn():
    """Real connection to the test DB, rolled back at teardown."""
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
def test_store(conn):
    chain_id = "7290661400001"
    store_id = "TEST_STORE"
    sub_chain_id = "TEST_SUBCHAIN"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chains (
                chain_id,
                name_he_normalized,
                name_en_normalized
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (chain_id) DO NOTHING
            """,
            (
                chain_id,
                "test chain",
                "test chain",
            ),
        )

        cur.execute(
            """
            INSERT INTO stores (
                chain_id,
                sub_chain_id,
                store_id,
                store_name
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chain_id, store_id) DO NOTHING
            """,
            (
                chain_id,
                sub_chain_id,
                store_id,
                "Test Store",
            ),
        )

    return {
        "chain_id": chain_id,
        "store_id_text": store_id,
    }


@pytest.fixture
def create_store(conn):
    def _create_store(
        chain_id,
        store_id,
        sub_chain_id="TEST_SUBCHAIN",
    ):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chains (
                    chain_id,
                    name_he_normalized,
                    name_en_normalized
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (chain_id) DO NOTHING
                """,
                (
                    chain_id,
                    "test chain",
                    "test chain",
                ),
            )

            cur.execute(
                """
                INSERT INTO stores (
                    chain_id,
                    sub_chain_id,
                    store_id,
                    store_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (chain_id, store_id) DO NOTHING
                """,
                (
                    chain_id,
                    sub_chain_id,
                    store_id,
                    "Test Store",
                ),
            )

    return _create_store