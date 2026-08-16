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
import logging
from pathlib import Path

from database.records import split_promotion
from database.repository import (
    ensure_chain,
    reconcile_removed_promotions,
    reconcile_removed_promotion_groups,
    reconcile_removed_promotion_items,
    update_store_subchain,
    upsert_promotion_groups,
    upsert_promotion_items,
    upsert_promotions,
)
from parsers.xml import MachseneiXmlParser
from logging_config import setup_isolated_logging


logger = logging.getLogger(__name__)
change_logger = setup_isolated_logging("promo_changes")


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


def _log_changes(
    chain_id,
    store_id_text,
    file_type,
    promotions,
    item_keys_in_file,
    existing_promotions,
    existing_items,
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
                "promotion_id=%s description=%s "
                "chain_id=%s store_id=%s",
                promotion.promotion_id,
                promotion.description,
                chain_id,
                store_id_text,
            )

        else:
            old_description, old_end = old

            if (
                old_description != promotion.description
                or old_end != promotion.end_datetime
            ):
                change_logger.info(
                    "PROMOTION CHANGED "
                    "promotion_id=%s "
                    "old_description=%s "
                    "new_description=%s "
                    "old_end=%s "
                    "new_end=%s",
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

                if old_item is None:

                    change_logger.info(
                        "PROMO ITEM ADDED "
                        "chain_id=%s store_id=%s "
                        "promotion_id=%s group_id=%s "
                        "item_code=%s discounted_price=%s",
                        chain_id,
                        store_id_text,
                        promotion.promotion_id,
                        group.group_id,
                        item.item_code,
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
                        "item_code=%s old=%s new=%s",
                        chain_id,
                        store_id_text,
                        promotion.promotion_id,
                        group.group_id,
                        item.item_code,
                        old_item,
                        (
                            item.discounted_price,
                            item.discount_rate,
                        ),
                    )

    # A Promo delta cannot tell us what disappeared.
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
                "promotion_id=%s group_id=%s item_code=%s",
                chain_id,
                store_id_text,
                promotion_id,
                group_id,
                item_code,
            )


def load_one_file(
    conn,
    parser: MachseneiXmlParser,
    filepath: Path,
    feeds_dir: Path,
    file_type: str,
    log_changes: bool = True,
) -> None:

    if file_type not in ("Promo", "PromoFull"):
        raise ValueError(
            f"Unsupported promo file type: {file_type}"
        )

    with gzip.open(filepath, "rb") as f:
        xml_content = f.read()

    promotions = parser.parse_promo_file(
        xml_content
    )

    if not promotions:
        logger.warning(
            "No promotions parsed from %s",
            filepath,
        )
        return

    path_chain_id, path_sub_chain_id, path_store_id = (
        filepath.relative_to(feeds_dir).parts[:3]
    )

    ensure_chain(
        conn,
        path_chain_id,
    )

    update_store_subchain(
        conn,
        path_chain_id,
        path_store_id,
        path_sub_chain_id,
    )

    all_groups = []
    all_items = []

    promotion_ids_in_file = set()
    group_keys_in_file = set()
    item_keys_in_file = set()

    for promotion in promotions:

        _, groups, items = split_promotion(
            promotion
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

    if log_changes:

        existing_promotions = (
            _fetch_existing_promotions(
                conn,
                path_chain_id,
                path_store_id,
                promotion_ids_in_file,
            )
        )

        existing_items = (
            _fetch_existing_promotion_items(
                conn,
                path_chain_id,
                path_store_id,
            )
        )

        _log_changes(
            path_chain_id,
            path_store_id,
            file_type,
            promotions,
            item_keys_in_file,
            existing_promotions,
            existing_items,
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
                path_chain_id,
                path_store_id,
                promotion_ids_in_file,
            )
        )

        removed_groups = (
            reconcile_removed_promotion_groups(
                conn,
                path_chain_id,
                path_store_id,
                group_keys_in_file,
            )
        )

        removed_items = (
            reconcile_removed_promotion_items(
                conn,
                path_chain_id,
                path_store_id,
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
        path_chain_id,
        path_store_id,
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

    parser = MachseneiXmlParser()
    loaded_files = []

    for filepath, file_type in files:

        try:

            load_one_file(
                conn,
                parser,
                filepath,
                feeds_dir,
                file_type,
                log_changes=log_changes,
            )

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