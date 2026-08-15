# utils/update_promos.py
"""
Core promo-loading logic, shared by both entry points:
  - scripts/load_promos.py  (manual/backfill CLI, log_changes=False)
  - cron's run_promos_and_load()  (live runs, log_changes=True by default)

Only for PromoFull files (full current-state snapshots) -- do NOT call
the reconcile_removed_* functions against promo.xml delta files, since
a delta only ever adds/confirms, it never represents "everything
active right now."

Diff logging mirrors update_prices.py's log_changes flag: when False,
pre-write snapshot queries are skipped entirely, not just the log
calls, so backfill runs don't pay for SELECTs nobody reads, and
promo_changes.log stays exclusively a record of live cron activity.

chain_id/store_id come from parsed XML content here (ChainID/StoreID
tags), same as everywhere else in Promotion/PromotionGroup/
PromotionItem -- not overridden from the file path. Path is used for directory-derived 
sub_chain_id and store_id.

promotions is now store-scoped, same identity shape as
promotion_groups/promotion_items -- PK is (chain_id, promotion_id,
store_id). Each store's PromoFull is treated as a fully independent,
authoritative snapshot: no cross-store awareness, no chain-wide
reconciliation pass needed.

Reconciliation runs top-down in three passes, in this exact order:
  1. reconcile_removed_promotions       -- promotion_id not in file -> delete
  2. reconcile_removed_promotion_groups -- group_id not in file -> delete
  3. reconcile_removed_promotion_items  -- item not in file -> delete
Both promotion_groups and promotion_items have ON DELETE CASCADE on
their parent FK, so pass 1 alone clears out every group/item under a
removed promotion, and pass 2 clears out every item under a removed
group -- no manual child cleanup needed anywhere. Passes 2 and 3 only
ever act on what pass 1 (and 2) left behind.
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
            SELECT promotion_id, description, end_datetime
            FROM promotions
            WHERE chain_id = %s
              AND store_id = %s
              AND promotion_id = ANY(%s)
            """,
            (chain_id, store_id_text, promotion_ids),
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
            SELECT promotion_id, group_id, item_code,
                   discounted_price, discount_rate
            FROM promotion_items
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id_text),
        )
        return {
            (row[0], row[1], row[2]): (row[3], row[4])
            for row in cur.fetchall()
        }


def _log_changes(
    chain_id,
    store_id_text,
    promotions,
    item_keys_in_file,
    existing_promotions,
    existing_items,
):
    for p in promotions:
        old = existing_promotions.get(p.promotion_id)

        if old is None:
            change_logger.info(
                "PROMOTION ADDED promotion_id=%s description=%s chain_id=%s store_id=%s",
                p.promotion_id, p.description, chain_id, store_id_text,
            )
            continue

        old_description, old_end = old
        if old_description != p.description or old_end != p.end_datetime:
            change_logger.info(
                "PROMOTION CHANGED promotion_id=%s old_description=%s new_description=%s "
                "old_end=%s new_end=%s",
                p.promotion_id, old_description, p.description, old_end, p.end_datetime,
            )

        for group in p.groups:
            for item in group.items:
                key = (p.promotion_id, group.group_id, item.item_code)
                old_item = existing_items.get(key)

                if old_item is None:
                    change_logger.info(
                        "PROMO ITEM ADDED chain_id=%s store_id=%s promotion_id=%s "
                        "item_code=%s discounted_price=%s",
                        chain_id, store_id_text, p.promotion_id,
                        item.item_code, item.discounted_price,
                    )
                elif old_item != (item.discounted_price, item.discount_rate):
                    change_logger.info(
                        "PROMO ITEM CHANGED chain_id=%s store_id=%s promotion_id=%s "
                        "item_code=%s old=%s new=%s",
                        chain_id, store_id_text, p.promotion_id, item.item_code,
                        old_item, (item.discounted_price, item.discount_rate),
                    )

    removed_keys = set(existing_items) - item_keys_in_file
    for promotion_id, group_id, item_code in removed_keys:
        change_logger.info(
            "PROMO ITEM REMOVED chain_id=%s store_id=%s promotion_id=%s "
            "group_id=%s item_code=%s",
            chain_id, store_id_text, promotion_id, group_id, item_code,
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

    promotions = parser.parse_promo_file(xml_content)

    if not promotions:
        logger.warning("No promotions parsed from %s", filepath)
        return

    # Path is used for chain/sub-chain metadata.
    # store_id is the actual retailer/feed store identifier.
    path_chain_id, path_sub_chain_id, path_store_id = (
        filepath.relative_to(feeds_dir).parts[:3]
    )

    ensure_chain(conn, path_chain_id)

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
        _, groups, items = split_promotion(promotion)
        all_groups.extend(groups)
        all_items.extend(items)

        promotion_ids_in_file.add(promotion.promotion_id)
        for group in groups:
            group_keys_in_file.add((group.promotion_id, group.group_id))
        for item in items:
            item_keys_in_file.add(
                (item.promotion_id, item.group_id, item.item_code)
            )

    existing_promotions = {}
    existing_items = {}

    if log_changes:
        existing_promotions = _fetch_existing_promotions(
            conn,
            path_chain_id,
            path_store_id,
            promotion_ids_in_file,
        )

        existing_items = _fetch_existing_promotion_items(
            conn,
            path_chain_id,
            path_store_id,
        )

        _log_changes(
            path_chain_id,
            path_store_id,
            promotions,
            item_keys_in_file,
            existing_promotions,
            existing_items,
        )

    upsert_promotions(conn, promotions)
    upsert_promotion_groups(conn, all_groups)
    upsert_promotion_items(conn, all_items)

    # Top-down: promotions -> groups -> items. CASCADE handles the
    # children of anything deleted at each step -- see module docstring.
    removed_promotions = reconcile_removed_promotions(
        conn, path_chain_id, path_store_id, promotion_ids_in_file
    )
    removed_groups = reconcile_removed_promotion_groups(
        conn, path_chain_id, path_store_id, group_keys_in_file
    )
    removed_items = reconcile_removed_promotion_items(
        conn, path_chain_id, path_store_id, item_keys_in_file
    )

    conn.commit()

    # Summary always logs, regardless of log_changes -- goes to the
    # general logger, never to promo_changes.log.
    logger.info(
        "%s: chain_id=%s store_id=%s promotions=%d items=%d "
        "removed_promotions=%d removed_groups=%d removed_items=%d",
        filepath.name,
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
    filepaths: list[Path],
    feeds_dir: Path,
    log_changes: bool = True,
) -> None:
    """
    Call right after a PromoFull download finishes (cron), passing
    exactly the files it just wrote -- or call from
    scripts/load_promos.py with a full glob for manual/backfill runs,
    passing log_changes=False to keep promo_changes.log exclusive to
    live cron activity.
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