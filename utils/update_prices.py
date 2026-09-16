# utils/update_prices.py
"""
Core price-loading logic, shared by both entry points:
  - utils/load_prices.py  (manual/backfill CLI, log_changes=False)
  - cron's run_prices_and_load()  (live runs, log_changes=True by default)

This module is intentionally PRICE-ONLY.

Product identity, product names, and product metadata are handled
entirely by update_products.py. This module never creates products or
store_products and never resolves names -- it only reads/writes the
`prices` table.

This mirrors the file-discovery/parsing conventions used by
update_products.py so both modules agree on what a feed file's
chain_id/store_id/sub_chain_id actually are:

    - chain metadata comes from chains.json / chains_extra.json, the
      same as update_products.py, since ensure_chain() now requires
      the chain's normalized names rather than just its id
    - filenames are parsed via utils.file_tracking.parser_file_tracking
      instead of an ad-hoc regex
    - iter_xml_from_path() is used instead of a bare gzip.open(), so
      container files that hold more than one store's XML document
      (e.g. a zip) are handled the same way product loading handles
      them

This module:
  - parses price feeds 
  - deduplicates repeated item codes within a document
  - optionally logs price changes
  - upserts prices
  - reconciles items removed from the current store snapshot
  - marks successfully loaded files

It does NOT:
  - create products
  - create store_products
  - resolve product names
  - modify product metadata
"""

import json
import logging
from pathlib import Path

from database.repository import (
    ensure_chain,
    mark_files_loaded,
    reconcile_removed_items,
    update_store_subchain,
    upsert_prices,
)
from parsers.xml import StoreXmlParser
from utils.file_tracking.parser_file_tracking import parse_filename
from utils.xml_source import iter_xml_from_path
from logging_config import setup_isolated_logging
from database.records import split_product

logger = logging.getLogger(__name__)

change_logger = setup_isolated_logging(
    "price_changes"
)


BASE_DIR = Path(__file__).resolve().parents[1]

CHAINS_FILE = BASE_DIR / "data" / "reference" / "chains.json"
CHAINS_EXTRA_FILE = (
    BASE_DIR / "data" / "reference" / "chains_extra.json"
)


def _load_chain_metadata():
    """
    Load chain metadata from the main and extra chain registries.

    chains.json is the primary registry.
    chains_extra.json extends it with additional chains.

    If the same chain_id exists in both files, the entry from
    chains_extra.json takes precedence.

    Identical to update_products._load_chain_metadata() -- kept as a
    separate copy so this module has no import-time dependency on
    update_products.py.
    """
    with CHAINS_FILE.open("r", encoding="utf-8") as f:
        chains = json.load(f)

    if CHAINS_EXTRA_FILE.exists():
        with CHAINS_EXTRA_FILE.open("r", encoding="utf-8") as f:
            extra_chains = json.load(f)

        chains.update(extra_chains)

    return chains


# ---------------------------------------------------------------------------
# Price deduplication
# ---------------------------------------------------------------------------

def _dedupe_price_records(records):
    """
    A single feed document can contain more than one <Item> block for
    the same item_code.

    This has been confirmed empirically in the real feed data.

    Policy:
        keep the record with the latest price_update_time.

    Records without a price_update_time do not replace a record that
    already has a timestamp.

    This guarantees that:

        - diff logging
        - upsert_prices()
        - database state

    all operate on the same final record for each item_code.
    """
    best = {}

    for record in records:
        current = best.get(record.item_code)

        if current is None:
            best[record.item_code] = record
            continue

        if record.price_update_time is None:
            continue

        if (
            current.price_update_time is None
            or record.price_update_time > current.price_update_time
        ):
            best[record.item_code] = record

    return list(best.values())


# ---------------------------------------------------------------------------
# Existing prices
# ---------------------------------------------------------------------------

def _fetch_existing_prices(
    conn,
    chain_id,
    store_id_text,
):
    """
    Fetch the current prices for one chain/store.

    Used only when price-change logging is enabled.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                item_code,
                price,
                unit_price
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (
                chain_id,
                store_id_text,
            ),
        )

        return {
            row[0]: (
                row[1],
                row[2],
            )
            for row in cur.fetchall()
        }


# ---------------------------------------------------------------------------
# Price change logging
# ---------------------------------------------------------------------------

def _log_price_changes(
    chain_id,
    store_id_text,
    price_records,
    existing_prices,
):
    """
    Log additions and price changes.

    Product names are intentionally not fetched here.

    Price logging should not depend on product metadata.
    """
    for record in price_records:
        old = existing_prices.get(
            record.item_code
        )

        if old is None:
            change_logger.info(
                "PRICE ADDED "
                "chain_id=%s "
                "store_id=%s "
                "item_code=%s "
                "price=%s",
                chain_id,
                store_id_text,
                record.item_code,
                record.price,
            )

        elif (
            old[0] != record.price
            or old[1] != record.unit_price
        ):
            change_logger.info(
                "PRICE CHANGED "
                "chain_id=%s "
                "store_id=%s "
                "item_code=%s "
                "old_price=%s "
                "new_price=%s "
                "old_unit_price=%s "
                "new_unit_price=%s",
                chain_id,
                store_id_text,
                record.item_code,
                old[0],
                record.price,
                old[1],
                record.unit_price,
            )


# ---------------------------------------------------------------------------
# Single file
# ---------------------------------------------------------------------------

def load_one_file(
    conn,
    parser: StoreXmlParser,
    filepath: Path,
    feeds_dir: Path,
    chain_metadata: dict,
    log_changes: bool = True,
) -> bool:
    """
    Load prices from one feed file.

    iter_xml_from_path() yields complete XML documents as bytes. A
    container such as a zip may therefore produce more than one XML
    document for a single filepath -- each document is a distinct
    store snapshot and is loaded (dedup/log/upsert/reconcile/commit)
    independently, the same way update_products.py treats each
    document independently while scanning.

    Product information is deliberately ignored.

    Returns True if at least one document in this file produced price
    records, False otherwise.
    """
    file_had_prices = False

    for xml_content in iter_xml_from_path(filepath):
        products = parser.parse_price_file(
            xml_content
        )

        if not products:
            logger.warning(
                "No items parsed from %s",
                filepath,
            )
            continue

        file_had_prices = True

        # ---------------------------------------------------------------
        # Path metadata
        #
        # data/feeds/{chain_id}/{store_id}/pricesfull/file
        #
        # The path is the source of truth for chain_id/store_id -- store
        # directories are canonicalized when files are written, so the
        # directory name is the DB store_id. sub_chain_id comes from the
        # filename instead, via parse_filename().
        # ---------------------------------------------------------------

        relative_parts = filepath.relative_to(
            feeds_dir
        ).parts

        if len(relative_parts) < 2:
            raise ValueError(
                f"Unexpected feed path structure: {filepath}"
            )

        path_chain_id = relative_parts[0]
        path_store_id = relative_parts[1]

        xml_chain_id = products[0].chain_id
        xml_chain_id = (
            xml_chain_id.strip()
            if xml_chain_id
            else None
        )

        xml_store_id = products[0].store_id
        xml_store_id = (
            xml_store_id.strip()
            if xml_store_id
            else None
        )

        chain_id = path_chain_id
        store_id_text = path_store_id

        if xml_store_id:
            normalized_xml_store_id = (
                str(int(xml_store_id))
                if xml_store_id.isdigit()
                else xml_store_id
            )

            if normalized_xml_store_id != store_id_text:
                logger.warning(
                    "Path store_id=%s differs from XML store_id=%s: %s",
                    store_id_text,
                    normalized_xml_store_id,
                    filepath,
                )

        filename_info = parse_filename(
            filepath.name
        )

        filename_chain_id = filename_info["chain_id"]
        filename_sub_chain_id = (
            filename_info["sub_chain_id"]
        )

        if (
            xml_chain_id
            and path_chain_id != xml_chain_id
        ):
            logger.warning(
                "Path chain_id=%s differs from XML chain_id=%s: %s",
                path_chain_id,
                xml_chain_id,
                filepath,
            )

        if (
            filename_chain_id
            and filename_chain_id != chain_id
        ):
            logger.warning(
                "Filename chain_id=%s differs from resolved chain_id=%s: %s",
                filename_chain_id,
                chain_id,
                filepath,
            )

        # The filename may contain the upstream store ID with leading
        # zeroes (004), while the canonical directory and database
        # store ID are unpadded (4). They are intentionally not
        # compared here -- same convention as update_products.py.

        chain = chain_metadata.get(
            str(chain_id)
        )

        if chain is None:
            raise KeyError(
                f"Chain {chain_id} not found in "
                f"{CHAINS_FILE} or {CHAINS_EXTRA_FILE}"
            )

        ensure_chain(
            conn,
            chain_id,
            chain["name_he_normalized"],
            chain["name_en_normalized"],
        )

        update_store_subchain(
            conn,
            chain_id,
            store_id_text,
            filename_sub_chain_id,
        )

        # -----------------------------------------------------------
        # Extract prices only
        # -----------------------------------------------------------

        price_records = []
        item_codes_in_file = set()

        for product in products:
            _, _, price_record = split_product(
                product,
                chain_id,
                store_id_text,
            )

            price_records.append(
                price_record
            )

            item_codes_in_file.add(
                product.item_code
            )

        # -----------------------------------------------------------
        # Deduplicate repeated item codes.
        #
        # The latest price_update_time wins.
        # -----------------------------------------------------------

        price_records = _dedupe_price_records(
            price_records
        )

        # The dedupe result is the authoritative set used for both
        # database writing and reconciliation.
        item_codes_in_file = {
            record.item_code
            for record in price_records
        }

        # -----------------------------------------------------------
        # Existing prices
        #
        # Only fetched when live diff logging is requested.
        # -----------------------------------------------------------

        existing_prices = {}

        if log_changes:
            existing_prices = _fetch_existing_prices(
                conn,
                chain_id,
                store_id_text,
            )

            _log_price_changes(
                chain_id,
                store_id_text,
                price_records,
                existing_prices,
            )

        # -----------------------------------------------------------
        # Write prices
        # -----------------------------------------------------------

        upsert_prices(
            conn,
            price_records,
        )

        # -----------------------------------------------------------
        # Remove prices that disappeared from the current snapshot
        # -----------------------------------------------------------

        deleted = reconcile_removed_items(
            conn,
            chain_id,
            store_id_text,
            item_codes_in_file,
        )

        # -----------------------------------------------------------
        # Log removed items
        # -----------------------------------------------------------

        if log_changes:
            removed_codes = (
                set(existing_prices)
                - item_codes_in_file
            )

            for item_code in removed_codes:
                old_price = existing_prices[
                    item_code
                ][0]

                change_logger.info(
                    "ITEM REMOVED "
                    "chain_id=%s "
                    "store_id=%s "
                    "item_code=%s "
                    "(was price=%s)",
                    chain_id,
                    store_id_text,
                    item_code,
                    old_price,
                )

        conn.commit()

        # -----------------------------------------------------------
        # General summary
        # -----------------------------------------------------------

        logger.info(
            "%s: chain_id=%s store_id=%s "
            "items=%d removed=%d",
            filepath.name,
            chain_id,
            store_id_text,
            len(price_records),
            deleted,
        )

    return file_had_prices

# ---------------------------------------------------------------------------
# Multiple files
# ---------------------------------------------------------------------------

def load_files(
    conn,
    filepaths: list[Path],
    feeds_dir: Path,
    log_changes: bool = True,
) -> list[Path]:
    """
    Load all supplied PriceFull files.

    Successfully loaded files are marked as loaded in file_tracking.

    Failed files remain loaded = false.
    """
    parser = StoreXmlParser()
    chain_metadata = _load_chain_metadata()

    loaded_files = []

    for filepath in filepaths:
        try:
            file_had_prices = load_one_file(
                conn,
                parser,
                filepath,
                feeds_dir,
                chain_metadata,
                log_changes=log_changes,
            )

            if file_had_prices:
                mark_files_loaded(
                    conn,
                    [filepath.name],
                )

                conn.commit()

                loaded_files.append(
                    filepath
                )
            else:
                logger.warning(
                    "No prices found in %s",
                    filepath,
                )

        except KeyError as e:
            logger.error(
                "Skipping %s: %s",
                filepath,
                e,
            )

            conn.rollback()

        except Exception:
            logger.exception(
                "Failed to load %s",
                filepath,
            )

            conn.rollback()

    return loaded_files