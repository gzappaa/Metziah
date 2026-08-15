"""
DB write logic for the price-loading pipeline.

Operations per store's price file:
    1. upsert_products       -- add/update barcode item metadata
    2. upsert_store_products -- add/update non-barcode (internal-code)
                                 item metadata, scoped to
                                 (chain_id, store_id, item_code)
    3. upsert_prices         -- add changed prices only, no-op on unchanged rows
    4. reconcile_removed_items -- hard-delete (store_id, item_code) rows
                                 that exist in the DB but are no longer
                                 present in the current file

NAME RESOLUTION (products.name / store_products.name):
    A simple vote counter (`name_count`), not a full history table.
    - Incoming name matches current name -> name_count += 1
    - Incoming name differs -> name_count -= 1; if it hits 0, the name
      SWITCHES to the incoming value and name_count resets to 1
    - Blank/empty incoming name never participates (skipped entirely)

MANUFACTURER / MANUFACTURER_COUNTRY:
    Fill-only. Once a field is non-blank, it's never overwritten.
"""

import logging
from collections import defaultdict

from models.promo import Promotion, PromotionGroup, PromotionItem
from database.records import PriceRecord, ProductRecord, StoreProductRecord

logger = logging.getLogger(__name__)


def _resolve_name(existing_name, existing_count, incoming_name):
    """
    Vote-based name resolution.
    """
    if not incoming_name:
        return existing_name, existing_count

    if existing_name is None:
        return incoming_name, 1

    if incoming_name == existing_name:
        return existing_name, existing_count + 1

    new_count = existing_count - 1

    if new_count <= 0:
        return incoming_name, 1

    return existing_name, new_count


def _resolve_fill_only(existing_value, incoming_value):
    """
    Keep whatever's already filled. Only accept incoming if existing is
    blank/null.
    """
    if existing_value:
        return existing_value

    return incoming_value or existing_value


def upsert_stores(conn, stores: list) -> None:
    """
    Batch upsert into `stores` from the geocoded JSON seed file.

    store_id is the actual external/feed store identifier.
    There is no separate internal stores.id.
    """

    if not stores:
        return

    def clean(value):
        return value or None

    rows = [
        (
            s.chain_id,
            s.store_id,
            s.name,
            clean(s.address),
            clean(s.city),
            clean(s.zip_code),
            s.latitude,
            s.longitude,
        )
        for s in stores
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stores (
                chain_id,
                store_id,
                store_name,
                address,
                city,
                zip_code,
                latitude,
                longitude
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)

            ON CONFLICT (chain_id, store_id)
            DO UPDATE SET
                store_name = EXCLUDED.store_name,
                address = EXCLUDED.address,
                city = EXCLUDED.city,
                zip_code = EXCLUDED.zip_code,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude

            WHERE
                stores.store_name IS DISTINCT FROM EXCLUDED.store_name
                OR stores.address IS DISTINCT FROM EXCLUDED.address
                OR stores.city IS DISTINCT FROM EXCLUDED.city
                OR stores.zip_code IS DISTINCT FROM EXCLUDED.zip_code
                OR stores.latitude IS DISTINCT FROM EXCLUDED.latitude
                OR stores.longitude IS DISTINCT FROM EXCLUDED.longitude
            """,
            rows,
        )


def ensure_chain(conn, chain_id: str) -> None:
    """
    Makes sure the chain exists before inserting rows that reference it.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chains (chain_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            """,
            (chain_id,),
        )


def update_store_subchain(
    conn,
    chain_id: str,
    store_id_text: str,
    sub_chain_id: str,
) -> None:
    """
    Keeps stores.sub_chain_id in sync with the feed directory structure.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE stores
            SET sub_chain_id = %s
            WHERE chain_id = %s
              AND store_id = %s
              AND sub_chain_id IS DISTINCT FROM %s
            """,
            (
                sub_chain_id,
                chain_id,
                store_id_text,
                sub_chain_id,
            ),
        )


def upsert_products(conn, records: list[ProductRecord]) -> None:
    """
    Upsert into `products` (real barcodes only).
    """

    if not records:
        return

    item_codes = [r.item_code for r in records]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                item_code,
                name,
                name_count,
                manufacturer,
                manufacturer_country,
                item_type
            FROM products
            WHERE item_code = ANY(%s)
            """,
            (item_codes,),
        )

        existing = {
            row[0]: row[1:]
            for row in cur.fetchall()
        }

    insert_rows = []
    update_rows = []

    for r in records:
        current = existing.get(r.item_code)

        if current is None:
            name = r.name or None
            name_count = 1 if name else 0

            insert_rows.append(
                (
                    r.item_code,
                    name,
                    name_count,
                    r.manufacturer or None,
                    r.manufacturer_country or None,
                    r.item_type,
                )
            )

            continue

        (
            existing_name,
            existing_count,
            existing_mfr,
            existing_country,
            existing_type,
        ) = current

        name, name_count = _resolve_name(
            existing_name,
            existing_count,
            r.name,
        )

        manufacturer = _resolve_fill_only(
            existing_mfr,
            r.manufacturer,
        )

        manufacturer_country = _resolve_fill_only(
            existing_country,
            r.manufacturer_country,
        )

        if (
            name != existing_name
            or name_count != existing_count
            or manufacturer != existing_mfr
            or manufacturer_country != existing_country
            or r.item_type != existing_type
        ):
            update_rows.append(
                (
                    name,
                    name_count,
                    manufacturer,
                    manufacturer_country,
                    r.item_type,
                    r.item_code,
                )
            )

    if insert_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO products (
                    item_code,
                    name,
                    name_count,
                    manufacturer,
                    manufacturer_country,
                    item_type
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (item_code) DO NOTHING
                """,
                insert_rows,
            )

    if update_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE products
                SET
                    name = %s,
                    name_count = %s,
                    manufacturer = %s,
                    manufacturer_country = %s,
                    item_type = %s,
                    updated_at = now()
                WHERE item_code = %s
                """,
                update_rows,
            )


def upsert_store_products(
    conn,
    records: list[StoreProductRecord],
) -> None:
    """
    Upsert non-barcode/internal products.

    store_id is the actual feed store_id TEXT.
    No stores.id resolution is performed.
    """

    if not records:
        return

    by_chain: dict[str, list[StoreProductRecord]] = defaultdict(list)

    for r in records:
        by_chain[r.chain_id].append(r)

    insert_rows = []
    update_rows = []

    for chain_id, chain_records in by_chain.items():

        item_codes = [r.item_code for r in chain_records]
        store_ids = [r.store_id for r in chain_records]

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    store_id,
                    item_code,
                    name,
                    name_count,
                    manufacturer,
                    manufacturer_country,
                    item_type
                FROM store_products
                WHERE chain_id = %s
                  AND item_code = ANY(%s)
                  AND store_id = ANY(%s)
                """,
                (
                    chain_id,
                    item_codes,
                    store_ids,
                ),
            )

            existing = {
                (row[0], row[1]): row[2:]
                for row in cur.fetchall()
            }

        for r in chain_records:

            current = existing.get(
                (r.store_id, r.item_code)
            )

            if current is None:

                name = r.name or None
                name_count = 1 if name else 0

                insert_rows.append(
                    (
                        chain_id,
                        r.store_id,
                        r.item_code,
                        name,
                        name_count,
                        r.manufacturer or None,
                        r.manufacturer_country or None,
                        r.item_type,
                    )
                )

                continue

            (
                existing_name,
                existing_count,
                existing_mfr,
                existing_country,
                existing_type,
            ) = current

            name, name_count = _resolve_name(
                existing_name,
                existing_count,
                r.name,
            )

            manufacturer = _resolve_fill_only(
                existing_mfr,
                r.manufacturer,
            )

            manufacturer_country = _resolve_fill_only(
                existing_country,
                r.manufacturer_country,
            )

            if (
                name != existing_name
                or name_count != existing_count
                or manufacturer != existing_mfr
                or manufacturer_country != existing_country
                or r.item_type != existing_type
            ):
                update_rows.append(
                    (
                        name,
                        name_count,
                        manufacturer,
                        manufacturer_country,
                        r.item_type,
                        chain_id,
                        r.store_id,
                        r.item_code,
                    )
                )

    if insert_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO store_products (
                    chain_id,
                    store_id,
                    item_code,
                    name,
                    name_count,
                    manufacturer,
                    manufacturer_country,
                    item_type
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chain_id, store_id, item_code)
                DO NOTHING
                """,
                insert_rows,
            )

    if update_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE store_products
                SET
                    name = %s,
                    name_count = %s,
                    manufacturer = %s,
                    manufacturer_country = %s,
                    item_type = %s,
                    updated_at = now()
                WHERE chain_id = %s
                  AND store_id = %s
                  AND item_code = %s
                """,
                update_rows,
            )


def upsert_prices(
    conn,
    records: list[PriceRecord],
) -> None:
    """
    Batch upsert into `prices`.

    store_id is stored directly as the feed's store_id TEXT.
    """

    if not records:
        return

    rows = []

    for r in records:
        rows.append(
            (
                r.chain_id,
                r.store_id,
                r.item_code,
                r.price,
                r.unit_price,
                r.quantity,
                r.unit_qty,
                r.unit_measure,
                r.weighted,
                r.package_quantity,
                r.allow_discount,
                r.status,
                r.price_update_time,
                r.last_sale_datetime,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO prices (
                chain_id,
                store_id,
                item_code,
                price,
                unit_price,
                quantity,
                unit_qty,
                unit_measure,
                weighted,
                package_quantity,
                allow_discount,
                status,
                price_update_time,
                last_sale_datetime
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )

            ON CONFLICT (chain_id, store_id, item_code)
            DO UPDATE SET
                price = EXCLUDED.price,
                unit_price = EXCLUDED.unit_price,
                quantity = EXCLUDED.quantity,
                unit_qty = EXCLUDED.unit_qty,
                unit_measure = EXCLUDED.unit_measure,
                weighted = EXCLUDED.weighted,
                package_quantity = EXCLUDED.package_quantity,
                allow_discount = EXCLUDED.allow_discount,
                status = EXCLUDED.status,
                price_update_time = EXCLUDED.price_update_time,
                last_sale_datetime = EXCLUDED.last_sale_datetime,
                updated_at = now()

            WHERE
                prices.price IS DISTINCT FROM EXCLUDED.price
                OR prices.unit_price IS DISTINCT FROM EXCLUDED.unit_price
                OR prices.quantity IS DISTINCT FROM EXCLUDED.quantity
                OR prices.unit_qty IS DISTINCT FROM EXCLUDED.unit_qty
                OR prices.unit_measure IS DISTINCT FROM EXCLUDED.unit_measure
                OR prices.weighted IS DISTINCT FROM EXCLUDED.weighted
                OR prices.package_quantity IS DISTINCT FROM EXCLUDED.package_quantity
                OR prices.allow_discount IS DISTINCT FROM EXCLUDED.allow_discount
                OR prices.status IS DISTINCT FROM EXCLUDED.status
                OR prices.price_update_time IS DISTINCT FROM EXCLUDED.price_update_time
                OR prices.last_sale_datetime IS DISTINCT FROM EXCLUDED.last_sale_datetime
            """,
            rows,
        )


def reconcile_removed_items(
    conn,
    chain_id: str,
    store_id_text: str,
    item_codes_in_file: set[str],
) -> int:
    """
    Hard-delete price rows that are no longer present in the current file.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM prices
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code <> ALL(%s)
            """,
            (
                chain_id,
                store_id_text,
                list(item_codes_in_file),
            ),
        )

        deleted = cur.rowcount

    if deleted:
        logger.info(
            "Removed %d item(s) no longer sold at "
            "chain_id=%s store_id=%s",
            deleted,
            chain_id,
            store_id_text,
        )

    return deleted


def upsert_promotions(
    conn,
    records: list[Promotion],
) -> None:
    """
    Batch upsert store-scoped promotions.

    store_id is the actual feed store_id TEXT.
    """

    if not records:
        return

    rows = []

    for r in records:
        rows.append(
            (
                r.chain_id,
                r.promotion_id,
                r.store_id,
                r.description,
                r.start_datetime,
                r.end_datetime,
                r.start_hour,
                r.end_hour,
                r.promotion_days,
                r.update_time,
                r.club_id,
                r.is_gift_item,
                r.additional_is_coupon,
                r.allow_multiple_discounts,
                r.redemption_limit,
                r.min_no_of_items_offered,
                r.additional_restrictions,
                r.remarks,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO promotions (
                chain_id,
                promotion_id,
                store_id,
                description,
                start_datetime,
                end_datetime,
                start_hour,
                end_hour,
                promotion_days,
                update_time,
                club_id,
                is_gift_item,
                additional_is_coupon,
                allow_multiple_discounts,
                redemption_limit,
                min_no_of_items_offered,
                additional_restrictions,
                remarks
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s
            )

            ON CONFLICT (chain_id, promotion_id, store_id)
            DO UPDATE SET
                description = EXCLUDED.description,
                start_datetime = EXCLUDED.start_datetime,
                end_datetime = EXCLUDED.end_datetime,
                start_hour = EXCLUDED.start_hour,
                end_hour = EXCLUDED.end_hour,
                promotion_days = EXCLUDED.promotion_days,
                update_time = EXCLUDED.update_time,
                club_id = EXCLUDED.club_id,
                is_gift_item = EXCLUDED.is_gift_item,
                additional_is_coupon = EXCLUDED.additional_is_coupon,
                allow_multiple_discounts = EXCLUDED.allow_multiple_discounts,
                redemption_limit = EXCLUDED.redemption_limit,
                min_no_of_items_offered = EXCLUDED.min_no_of_items_offered,
                additional_restrictions = EXCLUDED.additional_restrictions,
                remarks = EXCLUDED.remarks,
                updated_at = now()

            WHERE
                promotions.description IS DISTINCT FROM EXCLUDED.description
                OR promotions.start_datetime IS DISTINCT FROM EXCLUDED.start_datetime
                OR promotions.end_datetime IS DISTINCT FROM EXCLUDED.end_datetime
                OR promotions.start_hour IS DISTINCT FROM EXCLUDED.start_hour
                OR promotions.end_hour IS DISTINCT FROM EXCLUDED.end_hour
                OR promotions.promotion_days IS DISTINCT FROM EXCLUDED.promotion_days
                OR promotions.update_time IS DISTINCT FROM EXCLUDED.update_time
                OR promotions.club_id IS DISTINCT FROM EXCLUDED.club_id
                OR promotions.is_gift_item IS DISTINCT FROM EXCLUDED.is_gift_item
                OR promotions.additional_is_coupon IS DISTINCT FROM EXCLUDED.additional_is_coupon
                OR promotions.allow_multiple_discounts IS DISTINCT FROM EXCLUDED.allow_multiple_discounts
                OR promotions.redemption_limit IS DISTINCT FROM EXCLUDED.redemption_limit
                OR promotions.min_no_of_items_offered IS DISTINCT FROM EXCLUDED.min_no_of_items_offered
                OR promotions.additional_restrictions IS DISTINCT FROM EXCLUDED.additional_restrictions
                OR promotions.remarks IS DISTINCT FROM EXCLUDED.remarks
            """,
            rows,
        )


def upsert_promotion_groups(
    conn,
    records: list[PromotionGroup],
) -> None:
    """
    Batch upsert promotion groups.

    store_id is the actual feed store_id TEXT.
    """

    if not records:
        return

    rows = []

    for r in records:
        rows.append(
            (
                r.chain_id,
                r.promotion_id,
                r.store_id,
                r.group_id,
                r.min_purchase_amount,
                r.discount_type,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO promotion_groups (
                chain_id,
                promotion_id,
                store_id,
                group_id,
                min_purchase_amount,
                discount_type
            )
            VALUES (%s, %s, %s, %s, %s, %s)

            ON CONFLICT (
                chain_id,
                promotion_id,
                store_id,
                group_id
            )
            DO UPDATE SET
                min_purchase_amount = EXCLUDED.min_purchase_amount,
                discount_type = EXCLUDED.discount_type,
                updated_at = now()

            WHERE
                promotion_groups.min_purchase_amount
                    IS DISTINCT FROM EXCLUDED.min_purchase_amount
                OR promotion_groups.discount_type
                    IS DISTINCT FROM EXCLUDED.discount_type
            """,
            rows,
        )


def upsert_promotion_items(
    conn,
    records: list[PromotionItem],
) -> None:
    """
    Batch upsert promotion items.

    store_id is the actual feed store_id TEXT.
    """

    if not records:
        return

    rows = []

    for r in records:
        rows.append(
            (
                r.chain_id,
                r.promotion_id,
                r.store_id,
                r.group_id,
                r.item_code,
                r.item_type,
                r.reward_type,
                r.min_qty,
                r.max_qty,
                r.discount_rate,
                r.discounted_price,
                r.discounted_price_per_mida,
                r.is_weighted,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO promotion_items (
                chain_id,
                promotion_id,
                store_id,
                group_id,
                item_code,
                item_type,
                reward_type,
                min_qty,
                max_qty,
                discount_rate,
                discounted_price,
                discounted_price_per_mida,
                is_weighted
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )

            ON CONFLICT (
                chain_id,
                promotion_id,
                store_id,
                group_id,
                item_code
            )
            DO UPDATE SET
                item_type = EXCLUDED.item_type,
                reward_type = EXCLUDED.reward_type,
                min_qty = EXCLUDED.min_qty,
                max_qty = EXCLUDED.max_qty,
                discount_rate = EXCLUDED.discount_rate,
                discounted_price = EXCLUDED.discounted_price,
                discounted_price_per_mida =
                    EXCLUDED.discounted_price_per_mida,
                is_weighted = EXCLUDED.is_weighted,
                updated_at = now()

            WHERE
                promotion_items.item_type
                    IS DISTINCT FROM EXCLUDED.item_type
                OR promotion_items.reward_type
                    IS DISTINCT FROM EXCLUDED.reward_type
                OR promotion_items.min_qty
                    IS DISTINCT FROM EXCLUDED.min_qty
                OR promotion_items.max_qty
                    IS DISTINCT FROM EXCLUDED.max_qty
                OR promotion_items.discount_rate
                    IS DISTINCT FROM EXCLUDED.discount_rate
                OR promotion_items.discounted_price
                    IS DISTINCT FROM EXCLUDED.discounted_price
                OR promotion_items.discounted_price_per_mida
                    IS DISTINCT FROM EXCLUDED.discounted_price_per_mida
                OR promotion_items.is_weighted
                    IS DISTINCT FROM EXCLUDED.is_weighted
            """,
            rows,
        )


def reconcile_removed_promotion_items(
    conn,
    chain_id: str,
    store_id_text: str,
    current_keys: set[tuple[str, str, str]],
) -> int:
    """
    Removes promotion items for a store that aren't in the current
    PromoFull snapshot.
    """

    current_key_strings = [
        f"{promotion_id}:{group_id}:{item_code}"
        for promotion_id, group_id, item_code in current_keys
    ]

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM promotion_items
            WHERE chain_id = %s
              AND store_id = %s
              AND (
                    promotion_id || ':' ||
                    group_id || ':' ||
                    item_code
                  ) <> ALL(%s)
            """,
            (
                chain_id,
                store_id_text,
                current_key_strings,
            ),
        )

        deleted = cur.rowcount

        cur.execute(
            """
            DELETE FROM promotion_groups g
            WHERE g.chain_id = %s
              AND g.store_id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM promotion_items i
                  WHERE i.chain_id = g.chain_id
                    AND i.promotion_id = g.promotion_id
                    AND i.store_id = g.store_id
                    AND i.group_id = g.group_id
              )
            """,
            (
                chain_id,
                store_id_text,
            ),
        )

    if deleted:
        logger.info(
            "Removed %d promo item(s) no longer active at "
            "chain_id=%s store_id=%s",
            deleted,
            chain_id,
            store_id_text,
        )

    return deleted


def reconcile_removed_promotions(
    conn,
    chain_id: str,
    store_id_text: str,
    promotion_ids_in_file: set[str],
) -> int:
    """
    Removes promotions for a store that aren't in the current
    PromoFull snapshot.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM promotions
            WHERE chain_id = %s
              AND store_id = %s
              AND promotion_id <> ALL(%s)
            """,
            (
                chain_id,
                store_id_text,
                list(promotion_ids_in_file),
            ),
        )

        deleted = cur.rowcount

    if deleted:
        logger.info(
            "Removed %d promotion(s) no longer active at "
            "chain_id=%s store_id=%s",
            deleted,
            chain_id,
            store_id_text,
        )

    return deleted


def reconcile_removed_promotion_groups(
    conn,
    chain_id: str,
    store_id_text: str,
    current_keys: set[tuple[str, str]],
) -> int:
    """
    Removes promotion groups for a store that aren't in the current
    PromoFull snapshot.
    """

    current_key_strings = [
        f"{promotion_id}:{group_id}"
        for promotion_id, group_id in current_keys
    ]

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM promotion_groups
            WHERE chain_id = %s
              AND store_id = %s
              AND (
                    promotion_id || ':' || group_id
                  ) <> ALL(%s)
            """,
            (
                chain_id,
                store_id_text,
                current_key_strings,
            ),
        )

        deleted = cur.rowcount

    if deleted:
        logger.info(
            "Removed %d promo group(s) no longer active at "
            "chain_id=%s store_id=%s",
            deleted,
            chain_id,
            store_id_text,
        )

    return deleted


def insert_file_tracking(conn, files):
    """
    Insert newly discovered feed files.

    New files use the downloaded value determined by the local
    filesystem check.

    Existing files:
        - downloaded can change from false -> true if the file
          now exists locally.
        - downloaded=true is never reverted.
        - loaded is never modified.
    """

    if not files:
        return 0

    query = """
        INSERT INTO file_tracking (
            chain_id,
            sub_chain_id,
            store_id,
            file_type,
            filename,
            file_date,
            downloaded,
            loaded
        )
        VALUES (
            %(chain_id)s,
            %(sub_chain_id)s,
            %(store_id)s,
            %(file_type)s,
            %(filename)s,
            %(file_date)s,
            %(downloaded)s,
            false
        )
        ON CONFLICT (chain_id, filename)
        DO UPDATE SET
            downloaded =
                file_tracking.downloaded OR EXCLUDED.downloaded
    """

    with conn.cursor() as cur:
        cur.executemany(query, files)
        return cur.rowcount


def mark_files_downloaded(conn, filenames):
    """
    Mark feed files as downloaded.

    Files must already exist in file_tracking.
    """

    if not filenames:
        return 0

    query = """
        UPDATE file_tracking
        SET downloaded = true
        WHERE filename = ANY(%s)
          AND downloaded = false
    """

    with conn.cursor() as cur:
        cur.execute(query, (filenames,))
        return cur.rowcount


def get_latest_downloaded_price_files(conn):
    query = """
        SELECT DISTINCT ON (chain_id, store_id)
            chain_id,
            sub_chain_id,
            store_id,
            file_type,
            filename,
            file_date
        FROM file_tracking
        WHERE file_type IN ('Price', 'PriceFull')
          AND downloaded = true
        ORDER BY
            chain_id,
            store_id,
            filename DESC
    """

    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()