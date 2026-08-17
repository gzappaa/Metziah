# tests/integration/test_update_prices.py

import gzip
from pathlib import Path

from parsers.xml import MachseneiXmlParser
from utils.update_prices import load_one_file


def test_load_one_file(conn):
    feeds_dir = Path("data/test_feeds")
    filepath = next(feeds_dir.glob("*/*/*/prices/*.gz"))

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )

    chain_id, _, store_id = filepath.relative_to(feeds_dir).parts[:3]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )
        price_count = cur.fetchone()[0]

    assert price_count > 0


def test_load_one_file_updates_store_subchain(conn):
    feeds_dir = Path("data/test_feeds")
    filepath = next(feeds_dir.glob("*/*/*/prices/*.gz"))

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )

    chain_id, sub_chain_id, store_id = (
        filepath.relative_to(feeds_dir).parts[:3]
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
    assert row[0] == sub_chain_id


def test_load_one_file_empty_xml_does_nothing(conn, tmp_path):
    feeds_dir = tmp_path

    filepath = (
        feeds_dir
        / "TEST_CHAIN"
        / "001"
        / "TEST_STORE"
        / "prices"
        / "empty.gz"
    )

    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )