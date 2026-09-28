import pytest
import psycopg
from pathlib import Path

from config import settings
import utils.prices.update_prices as update_prices
import utils.promos.update_promos as update_promos
import utils.products.update_products as update_products

from datetime import date



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
def test_price_partitions(conn):
    chain_ids = ("9999999999999", "8888888888888")

    with conn.cursor() as cur:
        for chain_id in chain_ids:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS prices_{chain_id}
                PARTITION OF prices
                FOR VALUES IN ('{chain_id}')
                """
            )

    conn.commit()

    yield

    with conn.cursor() as cur:
        for chain_id in chain_ids:
            cur.execute(
                f"DROP TABLE IF EXISTS prices_{chain_id}"
            )

    conn.commit()


@pytest.fixture
def test_promo_partitions(conn):
    chain_ids = ("9999999999999", "8888888888888")

    with conn.cursor() as cur:
        for chain_id in chain_ids:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS promotion_items_{chain_id}
                PARTITION OF promotion_items
                FOR VALUES IN ('{chain_id}')
                """
            )

    conn.commit()

    yield

    with conn.cursor() as cur:
        for chain_id in chain_ids:
            cur.execute(
                f"DROP TABLE IF EXISTS promotion_items_{chain_id}"
            )

    conn.commit()

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


@pytest.fixture
def pipeline_test_data(conn, cleanup_test_chains):
    test_data = [
        {
            "chain_id": "9999999999999",
            "sub_chain_id": "001",
            "store_id": "001",
            "files": [
                ("PromoFull", "PromoFull9999999999999-001-001-20260101-000000.xml"),
                ("PriceFull", "PriceFull9999999999999-001-001-20260101-000000.xml"),
                ("Promo", "Promo9999999999999-001-001-20260101-000001.xml"),
                ("Price", "Price9999999999999-001-001-20260101-000001.xml"),
            ],
        },
        {
            "chain_id": "8888888888888",
            "sub_chain_id": "001",
            "store_id": "001",
            "files": [
                ("PriceFull", "PriceFull8888888888888-001-001-20260101-000000.xml"),
                ("Price", "Price8888888888888-001-001-20260101-000001.xml"),
            ],
        },
    ]

    with conn.cursor() as cur:
        for data in test_data:
            chain_id = data["chain_id"]
            sub_chain_id = data["sub_chain_id"]
            store_id = data["store_id"]

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
                (chain_id, "test chain", "test chain"),
            )

            cur.execute(
                """
                INSERT INTO sub_chains (
                    chain_id,
                    sub_chain_id
                )
                VALUES (%s, %s)
                ON CONFLICT (chain_id, sub_chain_id) DO NOTHING
                """,
                (chain_id, sub_chain_id),
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

            for file_type, filename in data["files"]:
                cur.execute(
                    """
                    INSERT INTO file_tracking (
                        chain_id,
                        sub_chain_id,
                        store_id,
                        source,
                        file_type,
                        filename,
                        file_date,
                        downloaded,
                        loaded
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, true, false)
                    ON CONFLICT (chain_id, filename) DO NOTHING
                    """,
                    (
                        chain_id,
                        sub_chain_id,
                        store_id,
                        "test",
                        file_type,
                        filename,
                        date.today(),
                    ),
                )

    conn.commit()

    yield test_data


@pytest.fixture
def cleanup_test_chains(conn):
    yield

    with conn.cursor() as cur:
        for chain_id in ("9999999999999", "8888888888888"):
            cur.execute(
                "DELETE FROM prices WHERE chain_id = %s",
                (chain_id,),
            )
            cur.execute(
                "DELETE FROM promotions WHERE chain_id = %s",
                (chain_id,),
            )
            cur.execute(
                "DELETE FROM store_products WHERE chain_id = %s",
                (chain_id,),
            )
            cur.execute(
                "DELETE FROM file_tracking WHERE chain_id = %s",
                (chain_id,),
            )
            cur.execute(
                "DELETE FROM stores WHERE chain_id = %s",
                (chain_id,),
            )
            cur.execute(
                "DELETE FROM sub_chains WHERE chain_id = %s",
                (chain_id,),
            )
            cur.execute(
                "DELETE FROM chains WHERE chain_id = %s",
                (chain_id,),
            )

    conn.commit()


# ---------------------------------------------------------------------------
# Added for update_products / update_prices / update_promos integration tests
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# 9999999999999 / 8888888888888 are test-only chain IDs and deliberately do
# NOT exist in the real chains.json / chains_extra.json. Each update_*
# module's own _load_chain_metadata() is monkeypatched per-test instead of
# touching production reference data.
TEST_CHAIN_METADATA = {
    "9999999999999": {
        "name_he_normalized": "רשת בדיקה",
        "name_en_normalized": "test chain 9999",
    },
    "8888888888888": {
        "name_he_normalized": "רשת בדיקה 2",
        "name_en_normalized": "test chain 8888",
    },
}


@pytest.fixture
def feeds_dir():
    return FIXTURES_DIR


@pytest.fixture
def mock_chain_metadata(monkeypatch):


    for module in (update_prices, update_promos, update_products):
        monkeypatch.setattr(
            module,
            "_load_chain_metadata",
            lambda: TEST_CHAIN_METADATA,
        )

    return TEST_CHAIN_METADATA