"""
Core product-loading logic.

Responsibilities:

    PriceFull feeds
        ↓
    parse product observations
        ↓
    separate:
        - real barcodes -> global products
        - internal/store codes -> store_products
        ↓
    aggregate barcode names across chains/stores
        ↓
    resolve_canonical_name()
        ↓
    upsert products
    upsert store_products

This module does NOT load prices.

Product identity is decided here so that the canonical name can be based
on evidence from the entire set of available feeds rather than whichever
file happened to be processed first.
"""

import json
import logging
from collections import defaultdict
from pathlib import Path

from database.records import split_product
from database.repository import (
    ensure_chain,
    update_store_subchain,
    upsert_products,
    upsert_store_products,
)
from parsers.xml import StoreXmlParser
from utils.file_tracking.parser_file_tracking import parse_filename
from utils.resolve_canonical_name import resolve_canonical_name
from utils.xml_source import iter_xml_from_path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]

CHAINS_FILE = BASE_DIR / "data" / "reference" / "chains.json"
CHAINS_EXTRA_FILE = (
    BASE_DIR / "data" / "reference" / "chains_extra.json"
)

UNKNOWN_METADATA_VALUES = {
    "לא יודע",
}


def normalize_metadata_value(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()

    if value in UNKNOWN_METADATA_VALUES:
        return None

    return value


def _load_chain_metadata():
    """
    Load chain metadata from the main and extra chain registries.

    chains.json is the primary registry.
    chains_extra.json extends it with additional chains.

    If the same chain_id exists in both files, the entry from
    chains_extra.json takes precedence.
    """
    with CHAINS_FILE.open("r", encoding="utf-8") as f:
        chains = json.load(f)

    if CHAINS_EXTRA_FILE.exists():
        with CHAINS_EXTRA_FILE.open("r", encoding="utf-8") as f:
            extra_chains = json.load(f)

        chains.update(extra_chains)

    return chains


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _add_product_observation(
    observations,
    product_record,
    chain_id,
):
    """
    Add one real-barcode product observation.

    ProductRecord represents global product identity and therefore does not
    contain chain/store information. Chain identity belongs to the
    observation and is supplied separately.

    Structure:

        observations[item_code][raw_name][chain_id] += 1

    The count represents the number of stores from that chain that observed
    the name.
    """
    if product_record is None:
        return

    item_code = product_record.item_code
    name = product_record.name

    if not name:
        return

    observations[item_code][name][chain_id] += 1


def _merge_product_metadata(
    existing,
    incoming,
):
    """
    Keep the existing product record while filling metadata from a later
    observation when the existing value is missing.

    Name is deliberately NOT resolved here.
    """
    manufacturer = (
        existing.manufacturer
        or incoming.manufacturer
    )

    manufacturer_country = (
        existing.manufacturer_country
        or incoming.manufacturer_country
    )

    item_type = (
        incoming.item_type
        if incoming.item_type is not None
        else existing.item_type
    )

    return existing.__class__(
        item_code=existing.item_code,
        name=existing.name,
        manufacturer=manufacturer,
        manufacturer_country=manufacturer_country,
        item_type=item_type,
    )


def _resolve_product_records(
    observations,
    product_metadata,
):
    """
    Convert aggregated observations into ProductRecord objects with their
    final canonical names.

    product_metadata keeps the non-name metadata collected while scanning
    the feeds.
    """
    resolved_records = []

    for item_code, name_chain_counts in observations.items():
        canonical_name = resolve_canonical_name(
            name_chain_counts
        )

        metadata = product_metadata[item_code]

        if not canonical_name:
            canonical_name = metadata["fallback_name"]

        if not canonical_name:
            logger.warning(
                "No usable canonical name for item_code=%s",
                item_code,
            )

        record = metadata["record"]

        record = record.__class__(
            item_code=record.item_code,
            name=canonical_name,
            manufacturer=record.manufacturer,
            manufacturer_country=record.manufacturer_country,
            item_type=record.item_type,
        )

        resolved_records.append(record)

    return resolved_records


# ---------------------------------------------------------------------------
# Main loading function
# ---------------------------------------------------------------------------


def load_files(
    conn,
    filepaths: list[Path],
    feeds_dir: Path,
) -> list[Path]:
    """
    Load product information from the supplied PriceFull files.

    Files are scanned completely before products are written. This allows
    canonical names to be selected using evidence from multiple chains.

    iter_xml_from_path() yields complete XML documents as bytes. A container
    such as a ZIP may therefore produce more than one XML document for a
    single filepath.

    Price data is intentionally ignored here.

    Returns successfully processed files.
    """
    parser = StoreXmlParser()
    chain_metadata = _load_chain_metadata()

    observations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(int)
        )
    )

    product_metadata = {}
    store_product_records = []
    successful_files = []
    scanned_files = 0


    for filepath in filepaths:
        file_had_products = False

        try:
            for xml_content in iter_xml_from_path(filepath):
                products = parser.parse_price_file(xml_content)

                if not products:
                    logger.warning(
                        "No items parsed from %s",
                        filepath,
                    )
                    continue

                file_had_products = True

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
                xml_store_id = products[0].store_id

                xml_chain_id = (
                    xml_chain_id.strip()
                    if xml_chain_id
                    else None
                )

                xml_store_id = (
                    xml_store_id.strip()
                    if xml_store_id
                    else None
                )

                chain_id = xml_chain_id or path_chain_id

                # Store directories are now canonicalized when files are
                # written, so the directory name is the DB store_id.
                store_id_text = path_store_id.strip()

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

                # The filename may contain the upstream store ID with
                # leading zeroes (004), while the canonical directory and
                # database store ID are unpadded (4). They are intentionally
                # not compared here.

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

                for product in products:
                    # Treat empty/unknown metadata as missing so that
                    # existing real metadata is never overwritten.
                    product.manufacturer = normalize_metadata_value(
                        product.manufacturer
                    )
                    product.manufacturer_country = (
                        normalize_metadata_value(
                            product.manufacturer_country
                        )
                    )

                    (
                        product_record,
                        store_product_record,
                        _price_record,
                    ) = split_product(
                        product,
                        chain_id,
                        store_id_text,
                    )

                    if product_record is not None:
                        item_code = product_record.item_code

                        _add_product_observation(
                            observations,
                            product_record,
                            chain_id,
                        )

                        existing = product_metadata.get(
                            item_code
                        )

                        if existing is None:
                            product_metadata[item_code] = {
                                "record": product_record,
                                "fallback_name": product_record.name,
                            }

                        else:
                            product_metadata[item_code] = {
                                "record": _merge_product_metadata(
                                    existing["record"],
                                    product_record,
                                ),
                                "fallback_name": (
                                    existing["fallback_name"]
                                    or product_record.name
                                ),
                            }

                    if store_product_record is not None:
                        store_product_record = (
                            store_product_record.__class__(
                                chain_id=chain_id,
                                store_id=store_id_text,
                                item_code=store_product_record.item_code,
                                name=store_product_record.name,
                                manufacturer=(
                                    store_product_record.manufacturer
                                ),
                                manufacturer_country=(
                                    store_product_record.manufacturer_country
                                ),
                                item_type=store_product_record.item_type,
                            )
                        )

                        store_product_records.append(
                            store_product_record
                        )

                logger.debug(
                    "Scanned products: %s chain_id=%s store_id=%s items=%d",
                    filepath.name,
                    chain_id,
                    store_id_text,
                    len(products),
                )

            if file_had_products:
                successful_files.append(filepath)
            else:
                logger.warning(
                    "No products found in %s",
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
                "Failed to scan %s",
                filepath,
            )
            conn.rollback()

        scanned_files += 1

        if scanned_files % 50 == 0 or scanned_files == len(filepaths):
            logger.info(
                "Product loading progress: %d/%d files scanned",
                scanned_files,
                len(filepaths),
            )

    logger.info(
        "Resolving canonical names for %d barcode products",
        len(observations),
    )

    product_records = _resolve_product_records(
        observations,
        product_metadata,
    )

    if product_records:
        upsert_products(
            conn,
            product_records,
        )

    if store_product_records:
        upsert_store_products(
            conn,
            store_product_records,
        )

    conn.commit()

    # file_tracking.loaded currently means PRICE data has been loaded.
    # Product processing therefore deliberately does not call
    # mark_files_loaded() here. The caller decides how product processing
    # should be tracked separately.

    logger.info(
        "Product loading complete: products=%d store_products=%d files=%d",
        len(product_records),
        len(store_product_records),
        len(successful_files),
    )

    return successful_files


# ---------------------------------------------------------------------------
# Real-time new-product discovery (no canonical resolution)
# ---------------------------------------------------------------------------


def discover_new_products(
    conn,
    filepaths: list[Path],
    feeds_dir: Path,
) -> None:
    """
    Insert-only discovery for products/store_products.

    Runs on every Price and PriceFull load throughout the day, so a
    brand-new item_code is visible immediately instead of waiting for
    the once-daily full canonical-name resolution (load_products.py).

    - products: whatever name this batch has is used as-is (messy,
      temporary). Only item_codes not already in the table are
      inserted -- existing rows, including anything the canonical
      resolver decided, are never touched.
    - store_products: no canonical concept exists for this table, so
      every record is upserted normally via the existing
      upsert_store_products() -- last file wins, as usual.
    """
    parser = StoreXmlParser()

    candidate_products = {}
    store_product_records = []

    for filepath in filepaths:
        try:
            relative_parts = filepath.relative_to(feeds_dir).parts

            if len(relative_parts) < 2:
                raise ValueError(
                    f"Unexpected feed path structure: {filepath}"
                )

            path_chain_id = relative_parts[0]
            store_id_text = relative_parts[1].strip()

            for xml_content in iter_xml_from_path(filepath):
                products = parser.parse_price_file(xml_content)

                if not products:
                    continue

                xml_chain_id = products[0].chain_id
                xml_chain_id = xml_chain_id.strip() if xml_chain_id else None
                chain_id = xml_chain_id or path_chain_id

                for product in products:
                    product.manufacturer = normalize_metadata_value(
                        product.manufacturer
                    )
                    product.manufacturer_country = normalize_metadata_value(
                        product.manufacturer_country
                    )

                    (
                        product_record,
                        store_product_record,
                        _price_record,
                    ) = split_product(
                        product,
                        chain_id,
                        store_id_text,
                    )

                    if (
                        product_record is not None
                        and product_record.item_code not in candidate_products
                    ):
                        candidate_products[product_record.item_code] = (
                            product_record
                        )

                    if store_product_record is not None:
                        store_product_records.append(store_product_record)

        except Exception:
            logger.exception(
                "Failed scanning %s for new-product discovery",
                filepath,
            )

    # -----------------------------------------------------------------
    # products: filter to item_codes not already present, then insert
    # via the existing upsert_products() -- ON CONFLICT can't fire for
    # these since nothing to conflict with exists yet.
    # -----------------------------------------------------------------

    new_products = []

    if candidate_products:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_code FROM products WHERE item_code = ANY(%s)",
                (list(candidate_products.keys()),),
            )
            existing_codes = {row[0] for row in cur.fetchall()}

        new_products = [
            record
            for item_code, record in candidate_products.items()
            if item_code not in existing_codes
        ]

    if new_products:
        upsert_products(conn, new_products)

    # -----------------------------------------------------------------
    # store_products: no canonical concept -- upsert normally.
    # -----------------------------------------------------------------

    if store_product_records:
        upsert_store_products(conn, store_product_records)

    conn.commit()

    logger.info(
        "New-product discovery: %d new product(s), %d store_product "
        "record(s) from %d file(s) (%d candidate item_code(s) already "
        "existed)",
        len(new_products),
        len(store_product_records),
        len(filepaths),
        len(candidate_products) - len(new_products),
    )