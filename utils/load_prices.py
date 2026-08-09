"""
Standalone loader: walks data/feeds/{chain_id}/{sub_chain_id}/{store_id}/prices/,
gzip-decompresses each *.gz price file, parses it, and upserts into Postgres.

Decoupled from the live download step on purpose -- run this manually or
via its own cron entry, pointed at whatever's already on disk.

Usage:
    python scripts/load_prices.py
    python scripts/load_prices.py --feeds-dir data/feeds
"""

import argparse
import gzip
import logging
from pathlib import Path

from db import get_connection
from parsers.xml import MachseneiXmlParser
from database.records import split_product
from database.repository import (
    ensure_chain,
    reconcile_removed_items,
    update_store_subchain,
    upsert_prices,
    upsert_products,
    upsert_store_products,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_FEEDS_DIR = Path("data/feeds")


def find_price_files(feeds_dir: Path):
    """
    Yields every *.gz file under data/feeds/{chain}/{subchain}/{store}/prices/.
    Doesn't assume anything about filenames -- chain/subchain/store come
    from parsing the XML content itself, not the path, since that's the
    authoritative source.
    """
    yield from feeds_dir.glob("*/*/*/prices/*.gz")


def load_one_file(conn, parser: MachseneiXmlParser, filepath: Path, feeds_dir: Path) -> None:
    with gzip.open(filepath, "rb") as f:
        xml_content = f.read()

    products = parser.parse_price_file(xml_content)

    if not products:
        logger.warning("No items parsed from %s", filepath)
        return

    chain_id = products[0].chain_id
    store_id_text = products[0].store_id

    # Path is data/feeds/{chain_id}/{sub_chain_id}/{store_id}/prices/file.gz --
    # the path itself is the source of truth for sub_chain_id, regenerated
    # fresh on every download, so it's trusted over whatever a one-time
    # store seed said.
    path_chain_id, path_sub_chain_id, path_store_id = filepath.relative_to(feeds_dir).parts[:3]

    ensure_chain(conn, path_chain_id)
    update_store_subchain(conn, path_chain_id, path_store_id, path_sub_chain_id)

    product_records = []
    store_product_records = []
    price_records = []
    item_codes_in_file = set()

    for product in products:
        product_record, store_product_record, price_record = split_product(product)
        if product_record is not None:
            product_records.append(product_record)
        if store_product_record is not None:
            store_product_records.append(store_product_record)
        price_records.append(price_record)
        item_codes_in_file.add(product.item_code)

    upsert_products(conn, product_records)
    upsert_store_products(conn, store_product_records)
    upsert_prices(conn, price_records)
    deleted = reconcile_removed_items(conn, chain_id, store_id_text, item_codes_in_file)

    conn.commit()

    logger.info(
        "%s: chain_id=%s store_id=%s items=%d removed=%d",
        filepath.name,
        chain_id,
        store_id_text,
        len(products),
        deleted,
    )


def main():
    parser_args = argparse.ArgumentParser()
    parser_args.add_argument(
        "--feeds-dir",
        type=Path,
        default=DEFAULT_FEEDS_DIR,
        help="Root of the feeds tree (default: data/feeds)",
    )
    args = parser_args.parse_args()

    xml_parser = MachseneiXmlParser()

    files = list(find_price_files(args.feeds_dir))
    logger.info("Found %d price file(s) under %s", len(files), args.feeds_dir)

    if not files:
        return

    with get_connection() as conn:
        processed = 0
        failed = 0

        for filepath in files:
            try:
                load_one_file(conn, xml_parser, filepath, args.feeds_dir)
                processed += 1
            except KeyError as e:
                # Store not seeded yet -- skip, don't crash the whole run
                logger.error("Skipping %s: %s", filepath, e)
                conn.rollback()
                failed += 1
            except Exception:
                logger.exception("Failed to load %s", filepath)
                conn.rollback()
                failed += 1

    logger.info("Done. processed=%d failed=%d", processed, failed)


if __name__ == "__main__":
    main()