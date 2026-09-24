# tests/integration/test_update_products.py

import gzip
from pathlib import Path

from utils.products.update_products import load_files


def get_pricefull_file():
    feeds_dir = Path("data/test_feeds")

    candidates = list(
        feeds_dir.glob("*/*/pricesfull/*.gz")
    )

    if not candidates:
        candidates = list(
            feeds_dir.glob("*/*/pricesfull/*.xml")
        )

    assert candidates, "No PriceFull test feed found"

    return feeds_dir, candidates[0]


def test_load_files_inserts_products(conn):
    feeds_dir, filepath = get_pricefull_file()

    loaded = load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert filepath in loaded

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM products
            """
        )
        product_count = cur.fetchone()[0]

    assert product_count > 0


def test_load_files_inserts_store_products(conn):
    feeds_dir, filepath = get_pricefull_file()

    loaded = load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert filepath in loaded

    chain_id, store_id = (
        filepath.relative_to(feeds_dir).parts[:2]
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM store_products
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )

        store_product_count = cur.fetchone()[0]

    assert store_product_count > 0


def test_load_files_stores_product_names(conn):
    feeds_dir, filepath = get_pricefull_file()

    loaded = load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert filepath in loaded

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM products
            WHERE name IS NOT NULL
              AND name <> ''
            """
        )

        named_product_count = cur.fetchone()[0]

    assert named_product_count > 0


def test_load_files_updates_store_subchain(conn):
    feeds_dir, filepath = get_pricefull_file()

    loaded = load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert filepath in loaded

    chain_id, store_id = (
        filepath.relative_to(feeds_dir).parts[:2]
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sub_chain_id
            FROM stores
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )

        row = cur.fetchone()

    assert row is not None
    assert row[0] is not None


def test_load_files_empty_xml_does_nothing(conn, tmp_path):
    feeds_dir = tmp_path

    filepath = (
        feeds_dir
        / "TEST_CHAIN"
        / "001"
        / "pricesfull"
        / "empty.gz"
    )

    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE
                prices,
                store_products,
                products
            CASCADE
            """
        )

    conn.commit()

    loaded = load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert filepath not in loaded

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM products"
        )
        product_count = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM store_products"
        )
        store_product_count = cur.fetchone()[0]

    assert product_count == 0
    assert store_product_count == 0