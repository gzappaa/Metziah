"""
Core promo-loading logic.

PromoFull:
    - complete current-state snapshot
    - upsert promotions/groups/items
    - reconcile removals

Promo:
    - incremental/delta feed
    - upsert promotions/groups/items
    - NEVER reconcile removals

The scheduler is responsible for deciding which files are safe to load.
In particular, Promo files should only be loaded after a PromoFull for the
same store has successfully been loaded.

Diff logging:
    log_changes=False skips the pre-write SELECTs entirely.

Each store's PromoFull is an independent authoritative snapshot.
"""

import gzip
import json
import logging
from pathlib import Path
from datetime import datetime

from database.records import split_promotion
from database.repository import (
    ensure_chain,
    mark_files_loaded,
    reconcile_removed_promotions,
    reconcile_removed_promotion_groups,
    reconcile_removed_promotion_items,
    update_store_subchain,
    upsert_promotion_groups,
    upsert_promotion_items,
    upsert_promotions,
)
from parsers.xml import StoreXmlParser
from logging_config import setup_isolated_logging
from utils.file_tracking.parser_file_tracking import parse_filename
from utils.xml_source import iter_xml_from_path

logger = logging.getLogger(__name__)
change_logger = setup_isolated_logging("promo_changes")


BASE_DIR = Path(__file__).resolve().parents[1]

CHAINS_FILE = BASE_DIR / "data" / "reference" / "chains.json"
CHAINS_EXTRA_FILE = (
    BASE_DIR / "data" / "reference" / "chains_extra.json"
)


def _load_chain_metadata():
    """
    Load chain metadata from the main and extra chain registries.

    Same convention as update_products._load_chain_metadata():
    chains_extra.json entries take precedence over chains.json.

    Needed here because ensure_chain() now requires the chain's
    normalized names, not just its id.
    """
    with CHAINS_FILE.open("r", encoding="utf-8") as f:
        chains = json.load(f)

    if CHAINS_EXTRA_FILE.exists():
        with CHAINS_EXTRA_FILE.open("r", encoding="utf-8") as f:
            extra_chains = json.load(f)

        chains.update(extra_chains)

    return chains


def _fetch_item_names(conn, chain_id, store_id_text, item_codes):
    """
    Resolve item_code -> name for logging, preferring the store-specific
    name and falling back to the global product name. Mirrors the
    store_products / products precedence used in update_prices.py.
    """
    if not item_codes:
        return {}

    item_codes = list(item_codes)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT item_code, name
            FROM store_products
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = ANY(%s)
            """,
            (chain_id, store_id_text, item_codes),
        )
        names = dict(cur.fetchall())

    missing = [code for code in item_codes if code not in names]

    if missing:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_code, name FROM products WHERE item_code = ANY(%s)",
                (missing,),
            )
            names.update(dict(cur.fetchall()))

    return names


def _fetch_existing_promotions(
    conn,
    chain_id,
    store_id_text,
    promotion_ids,
):
    if not promotion_ids:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                promotion_id,
                description,
                end_datetime
            FROM promotions
            WHERE chain_id = %s
              AND store_id = %s
              AND promotion_id = ANY(%s)
            """,
            (
                chain_id,
                store_id_text,
                list(promotion_ids),
            ),
        )

        return {
            row[0]: row[1:]
            for row in cur.fetchall()
        }


def _fetch_existing_promotion_items(
    conn,
    chain_id,
    store_id_text,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                promotion_id,
                group_id,
                item_code,
                discounted_price,
                discount_rate
            FROM promotion_items
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (
                chain_id,
                store_id_text,
            ),
        )

        return {
            (row[0], row[1], row[2]): (row[3], row[4])
            for row in cur.fetchall()
        }


def _normalize_datetime_for_diff(dt: datetime | None):
    if dt is None:
        return None

    return dt.replace(tzinfo=None)


def _log_changes(
    chain_id,
    store_id_text,
    file_type,
    promotions,
    item_keys_in_file,
    existing_promotions,
    existing_items,
    item_names,
):
    """
    Log additions/changes.

    Only PromoFull can produce REMOVED events because only it represents
    the complete current state.
    """

    for promotion in promotions:

        old = existing_promotions.get(
            promotion.promotion_id
        )

        if old is None:
            change_logger.info(
                "PROMOTION ADDED "
                "chain_id=%s store_id=%s "
                "promotion_id=%s description=%s",
                chain_id,
                store_id_text,
                promotion.promotion_id,
                promotion.description,
            )

        else:
            old_description, old_end = old

            old_end_normalized = _normalize_datetime_for_diff(old_end)
            new_end_normalized = _normalize_datetime_for_diff(
                promotion.end_datetime
            )

            if (
                old_description != promotion.description
                or old_end_normalized != new_end_normalized
            ):
                change_logger.info(
                    "PROMOTION CHANGED "
                    "chain_id=%s store_id=%s "
                    "promotion_id=%s "
                    "old_description=%s "
                    "new_description=%s "
                    "old_end=%s "
                    "new_end=%s",
                    chain_id,
                    store_id_text,
                    promotion.promotion_id,
                    old_description,
                    promotion.description,
                    old_end,
                    promotion.end_datetime,
                )

        # Items must also be logged when the whole promotion is new.
        for group in promotion.groups:

            for item in group.items:

                key = (
                    promotion.promotion_id,
                    group.group_id,
                    item.item_code,
                )

                old_item = existing_items.get(key)
                name = item_names.get(item.item_code)

                if old_item is None:

                    change_logger.info(
                        "PROMO ITEM ADDED "
                        "chain_id=%s store_id=%s "
                        "promotion_id=%s group_id=%s "
                        "item_code=%s name=%s discounted_price=%s",
                        chain_id,
                        store_id_text,
                        promotion.promotion_id,
                        group.group_id,
                        item.item_code,
                        name,
                        item.discounted_price,
                    )

                elif old_item != (
                    item.discounted_price,
                    item.discount_rate,
                ):

                    change_logger.info(
                        "PROMO ITEM CHANGED "
                        "chain_id=%s store_id=%s "
                        "promotion_id=%s group_id=%s "
                        "item_code=%s name=%s old=%s new=%s",
                        chain_id,
                        store_id_text,
                        promotion.promotion_id,
                        group.group_id,
                        item.item_code,
                        name,
                        old_item,
                        (
                            item.discounted_price,
                            item.discount_rate,
                        ),
                    )

    if file_type == "PromoFull":

        removed_keys = (
            set(existing_items)
            - item_keys_in_file
        )

        for (
            promotion_id,
            group_id,
            item_code,
        ) in removed_keys:

            change_logger.info(
                "PROMO ITEM REMOVED "
                "chain_id=%s store_id=%s "
                "promotion_id=%s group_id=%s item_code=%s name=%s",
                chain_id,
                store_id_text,
                promotion_id,
                group_id,
                item_code,
                item_names.get(item_code),
            )


def load_one_file(
    conn,
    parser: StoreXmlParser,
    filepath: Path,
    feeds_dir: Path,
    file_type: str,
    chain_metadata: dict,
    log_changes: bool = True,
) -> None:

    if file_type not in ("Promo", "PromoFull"):
        raise ValueError(
            f"Unsupported promo file type: {file_type}"
        )

    xml_documents = list(iter_xml_from_path(filepath))

    promotions = []

    for xml_content in xml_documents:
        promotions.extend(
            parser.parse_promo_file(xml_content)
        )

    if not promotions:
        logger.warning(
            "No promotions parsed from %s",
            filepath,
        )
        return

    valid_promotions = []

    for promotion in promotions:
        if promotion.promotion_id is None:
            logger.warning(
                "Skipping promotion with null promotion_id: "
                "chain_id=%s store_id=%s description=%s file=%s",
                filepath.relative_to(feeds_dir).parts[0],
                filepath.relative_to(feeds_dir).parts[1],
                promotion.description,
                filepath,
            )
            continue

        valid_promotions.append(promotion)

    promotions = valid_promotions

    if not promotions:
        logger.warning(
            "No valid promotions with promotion_id found in %s",
            filepath,
        )
        return

    relative_parts = filepath.relative_to(
        feeds_dir
    ).parts

    if len(relative_parts) < 2:
        raise ValueError(
            f"Unexpected feed path structure: {filepath}"
        )

    path_chain_id = relative_parts[0]
    path_store_id = relative_parts[1]

    # The feed path is the source of truth for database identity.
    chain_id = path_chain_id
    store_id = path_store_id

    filename_info = parse_filename(filepath.name)

    filename_chain_id = filename_info["chain_id"]
    filename_sub_chain_id = filename_info["sub_chain_id"]

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
        store_id,
        filename_sub_chain_id,
    )

    all_groups = []
    all_items = []

    promotion_ids_in_file = set()
    group_keys_in_file = set()
    item_keys_in_file = set()

    for promotion in promotions:

        _, groups, items = split_promotion(
            promotion,
            chain_id,
            store_id,
        )

        all_groups.extend(groups)
        all_items.extend(items)

        promotion_ids_in_file.add(
            promotion.promotion_id
        )

        for group in groups:
            group_keys_in_file.add(
                (
                    group.promotion_id,
                    group.group_id,
                )
            )

        for item in items:
            item_keys_in_file.add(
                (
                    item.promotion_id,
                    item.group_id,
                    item.item_code,
                )
            )

    existing_promotions = {}
    existing_items = {}
    item_names = {}

    if log_changes:

        existing_promotions = (
            _fetch_existing_promotions(
                conn,
                chain_id,
                store_id,
                promotion_ids_in_file,
            )
        )

        existing_items = (
            _fetch_existing_promotion_items(
                conn,
                chain_id,
                store_id,
            )
        )

        all_relevant_codes = (
            {key[2] for key in item_keys_in_file}
            | {key[2] for key in existing_items}
        )

        item_names = _fetch_item_names(
            conn,
            chain_id,
            store_id,
            all_relevant_codes,
        )

        _log_changes(
            chain_id,
            store_id,
            file_type,
            promotions,
            item_keys_in_file,
            existing_promotions,
            existing_items,
            item_names,
        )

    # Both feed types modify the current state.
    upsert_promotions(
        conn,
        promotions,
    )

    upsert_promotion_groups(
        conn,
        all_groups,
    )

    upsert_promotion_items(
        conn,
        all_items,
    )

    removed_promotions = 0
    removed_groups = 0
    removed_items = 0

    # ONLY PromoFull represents the complete state.
    if file_type == "PromoFull":

        removed_promotions = (
            reconcile_removed_promotions(
                conn,
                chain_id,
                store_id,
                promotion_ids_in_file,
            )
        )

        removed_groups = (
            reconcile_removed_promotion_groups(
                conn,
                chain_id,
                store_id,
                group_keys_in_file,
            )
        )

        removed_items = (
            reconcile_removed_promotion_items(
                conn,
                chain_id,
                store_id,
                item_keys_in_file,
            )
        )

    # Promo is incremental.
    # Nothing is removed.

    conn.commit()

    logger.info(
        "%s: file_type=%s "
        "chain_id=%s store_id=%s "
        "promotions=%d items=%d "
        "removed_promotions=%d "
        "removed_groups=%d "
        "removed_items=%d",
        filepath.name,
        file_type,
        chain_id,
        store_id,
        len(promotions),
        len(all_items),
        removed_promotions,
        removed_groups,
        removed_items,
    )


def load_files(
    conn,
    files: list[tuple[Path, str]],
    feeds_dir: Path,
    log_changes: bool = True,
) -> list[Path]:
    """
    Load PromoFull and Promo files.

    PromoFull:
        upsert + reconciliation

    Promo:
        upsert only

    Returns only files that were successfully loaded.

    file_tracking.loaded is handled by the caller.
    """

    parser = StoreXmlParser()
    chain_metadata = _load_chain_metadata()
    loaded_files = []

    for filepath, file_type in files:

        try:

            load_one_file(
                conn,
                parser,
                filepath,
                feeds_dir,
                file_type,
                chain_metadata,
                log_changes=log_changes,
            )

            mark_files_loaded(
                conn,
                [filepath.name],
            )

            conn.commit()

            loaded_files.append(
                filepath
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