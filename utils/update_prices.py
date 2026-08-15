# utils/update_prices.py
"""
Core price-loading logic, shared by both entry points:
  - scripts/load_prices.py  (manual/backfill CLI, log_changes=False)
  - cron's run_prices_and_load()  (live runs, log_changes=True by default)

Diff logging (item added/changed/removed, price changed) is opt-in via
log_changes. When False, the pre-write snapshot queries are skipped
entirely too -- not just the log calls -- so backfill runs don't pay
for SELECTs nobody reads, and price_changes.log stays exclusively a
record of live cron activity, not backfill noise.

Product name and name_count are NOT treated as mutable metadata here.
They are finalized during the initial product-loading process.
"""

import gzip
import logging
from pathlib import Path

from database.records import split_product
from database.repository import (
    ensure_chain,
    reconcile_removed_items,
    update_store_subchain,
    upsert_prices,
    upsert_products,
    upsert_store_products,
    _resolve_fill_only,
)
from parsers.xml import MachseneiXmlParser
from logging_config import setup_isolated_logging

logger = logging.getLogger(__name__)
change_logger = setup_isolated_logging("price_changes")


def _fetch_existing_prices(conn, chain_id, store_id_text):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_code, price, unit_price FROM prices "
            "WHERE chain_id = %s AND store_id = %s",
            (chain_id, store_id_text),
        )
        return {
            row[0]: (row[1], row[2])
            for row in cur.fetchall()
        }


def _fetch_existing_products(conn, item_codes):
    if not item_codes:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT item_code,
                   name,
                   manufacturer,
                   manufacturer_country,
                   item_type
            FROM products
            WHERE item_code = ANY(%s)
            """,
            (item_codes,),
        )
        return {
            row[0]: row[1:]
            for row in cur.fetchall()
        }


def _fetch_existing_store_products(
    conn,
    chain_id,
    store_id_int,
    item_codes,
):
    if not item_codes:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT item_code,
                   name,
                   manufacturer,
                   manufacturer_country,
                   item_type
            FROM store_products
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = ANY(%s)
            """,
            (
                chain_id,
                store_id_int,
                item_codes,
            ),
        )
        return {
            row[0]: row[1:]
            for row in cur.fetchall()
        }


def _log_changes(
    chain_id,
    store_id_text,
    product_records,
    store_product_records,
    price_records,
    existing_products,
    existing_store_products,
    existing_prices,
):
    # Product metadata:
    # name/name_count are intentionally ignored here.
    # The canonical name is finalized during the initial loading process.
    for r in product_records:
        old = existing_products.get(r.item_code)

        if old is None:
            change_logger.info(
                "ITEM ADDED item_code=%s name=%s chain_id=%s",
                r.item_code,
                r.name,
                chain_id,
            )
            continue

        (
            old_name,
            old_manufacturer,
            old_country,
            old_type,
        ) = old

        new_manufacturer = _resolve_fill_only(
            old_manufacturer,
            r.manufacturer,
        )

        new_country = _resolve_fill_only(
            old_country,
            r.manufacturer_country,
        )

        old_resolved = (
            old_name,
            old_manufacturer,
            old_country,
            old_type,
        )

        new_resolved = (
            old_name,
            new_manufacturer,
            new_country,
            r.item_type,
        )

        if old_resolved != new_resolved:
            change_logger.info(
                "ITEM METADATA CHANGED item_code=%s name=%s old=%s new=%s",
                r.item_code,
                old_name,
                old_resolved,
                new_resolved,
            )

    # Store-specific product metadata:
    # name/name_count are intentionally ignored here as well.
    for r in store_product_records:
        old = existing_store_products.get(r.item_code)

        if old is None:
            change_logger.info(
                "ITEM ADDED item_code=%s name=%s chain_id=%s store_id=%s",
                r.item_code,
                r.name,
                chain_id,
                store_id_text,
            )
            continue

        (
            old_name,
            old_manufacturer,
            old_country,
            old_type,
        ) = old

        new_manufacturer = _resolve_fill_only(
            old_manufacturer,
            r.manufacturer,
        )

        new_country = _resolve_fill_only(
            old_country,
            r.manufacturer_country,
        )

        old_resolved = (
            old_name,
            old_manufacturer,
            old_country,
            old_type,
        )

        new_resolved = (
            old_name,
            new_manufacturer,
            new_country,
            r.item_type,
        )

        if old_resolved != new_resolved:
            change_logger.info(
                "ITEM METADATA CHANGED item_code=%s name=%s old=%s new=%s",
                r.item_code,
                old_name,
                old_resolved,
                new_resolved,
            )

    # Prices are allowed to change on every price-file load.
    name_lookup = {r.item_code: r.name for r in product_records}
    name_lookup.update({r.item_code: r.name for r in store_product_records})
    for r in price_records:
        old = existing_prices.get(r.item_code)

        if old is None:
            change_logger.info(
                "PRICE ADDED chain_id=%s store_id=%s item_code=%s price=%s name=%s",
                chain_id,
                store_id_text,
                r.item_code,
                r.price,
                name_lookup.get(r.item_code),
            )

        elif old[0] != r.price or old[1] != r.unit_price:
            change_logger.info(
                "PRICE CHANGED chain_id=%s store_id=%s item_code=%s "
                "old_price=%s new_price=%s " "name=%s",
                chain_id,
                store_id_text,
                r.item_code,
                old[0],
                r.price,
                name_lookup.get(r.item_code),
            )


def load_one_file(
    conn,
    parser: MachseneiXmlParser,
    filepath: Path,
    feeds_dir: Path,
    log_changes: bool = True,
) -> None:
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
    path_chain_id, path_sub_chain_id, path_store_id = (
        filepath.relative_to(feeds_dir).parts[:3]
    )

    ensure_chain(conn, chain_id)

    update_store_subchain(
        conn,
        chain_id,
        store_id_text,
        path_sub_chain_id,
    )


    product_records = []
    store_product_records = []
    price_records = []
    item_codes_in_file = set()

    for product in products:
        (
            product_record,
            store_product_record,
            price_record,
        ) = split_product(product)

        if product_record is not None:
            product_records.append(product_record)

        if store_product_record is not None:
            store_product_records.append(store_product_record)

        price_records.append(price_record)
        item_codes_in_file.add(product.item_code)

    existing_prices = {}
    removed_item_names = {}

    if log_changes:
        # Snapshot BEFORE writing -- this is what makes the log show real
        # diffs. Only fetched when actually needed, so backfill runs skip
        # these SELECTs entirely rather than doing the work and discarding it.
        existing_prices = _fetch_existing_prices(
            conn,
            chain_id,
            store_id_text,
        )

        all_relevant_codes = item_codes_in_file | set(existing_prices)

        existing_products = _fetch_existing_products(
            conn,
            list(all_relevant_codes),
        )

        existing_store_products = _fetch_existing_store_products(
            conn,
            chain_id,
            store_id_text,
            list(all_relevant_codes),
        )

        # item_code -> name, used only for logging ITEM REMOVED
        # (existing_prices itself has no name column to draw from).
        removed_item_names = {**existing_products, **existing_store_products}

        _log_changes(
            chain_id,
            store_id_text,
            product_records,
            store_product_records,
            price_records,
            existing_products,
            existing_store_products,
            existing_prices,
        )

    upsert_products(conn, product_records)
    upsert_store_products(conn, store_product_records)
    upsert_prices(conn, price_records)

    deleted = reconcile_removed_items(
        conn,
        chain_id,
        store_id_text,
        item_codes_in_file,
    )

    if log_changes:
        removed_codes = set(existing_prices) - item_codes_in_file

        for code in removed_codes:
            name_tuple = removed_item_names.get(code)
            removed_name = name_tuple[0] if name_tuple else None

            change_logger.info(
                "ITEM REMOVED chain_id=%s store_id=%s item_code=%s name=%s (was price=%s)",
                chain_id,
                store_id_text,
                code,
                removed_name,
                existing_prices[code][0],
            )

    conn.commit()

    # Summary always logs, regardless of log_changes -- goes to the
    # general logger, never to price_changes.log.
    logger.info(
        "%s: chain_id=%s store_id=%s items=%d removed=%d",
        filepath.name,
        chain_id,
        store_id_text,
        len(products),
        deleted,
    )


def load_files(
    conn,
    filepaths: list[Path],
    feeds_dir: Path,
    log_changes: bool = True,
) -> None:
    """
    Call right after download finishes (cron), passing exactly the files
    it just wrote -- or call from scripts/load_prices.py with a full glob
    for manual/backfill runs, passing log_changes=False to keep
    price_changes.log exclusive to live cron activity.
    """
    parser = MachseneiXmlParser()

    for filepath in filepaths:
        try:
            load_one_file(
                conn,
                parser,
                filepath,
                feeds_dir,
                log_changes=log_changes,
            )

        except KeyError as e:
            logger.error("Skipping %s: %s", filepath, e)
            conn.rollback()

        except Exception:
            logger.exception("Failed to load %s", filepath)
            conn.rollback()