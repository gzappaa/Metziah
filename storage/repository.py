"""
DB write logic for the price-loading pipeline.

Operations per store's price file:
    1. upsert_products       -- add/update barcode item metadata
    2. upsert_store_products -- add/update non-barcode (internal-code)
                                 item metadata, scoped to (chain_id, item_code)
    3. upsert_prices         -- add changed prices only, no-op on unchanged rows
    4. reconcile_removed_items -- hard-delete (store_id, item_code) rows
       that exist in the DB but are no longer present in the current file

NOTE: upsert_prices/upsert_products/upsert_store_products reference an
`updated_at` column that is not yet in the schema.sql you shared. Add it
to all three tables before running this (see the migration note at the
bottom of this file).
"""

import logging

from storage.records import PriceRecord, ProductRecord, StoreProductRecord

logger = logging.getLogger(__name__)

# In-memory cache: (chain_id, store_id_text) -> stores.id
_store_id_cache: dict[tuple[str, str], int] = {}


def get_store_id(conn, chain_id: str, store_id_text: str) -> int:
    """
    Resolves (chain_id, store_id_text) -> stores.id, the serial PK that
    prices.store_id actually references. Cached in memory since a single
    load run touches the same store repeatedly (once per file, but a
    process may loop over many files for the same store).

    Raises KeyError if the store hasn't been seeded into `stores` yet --
    this is intentional: prices should never silently create a store.
    """
    cache_key = (chain_id, store_id_text)

    if cache_key in _store_id_cache:
        return _store_id_cache[cache_key]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM stores WHERE chain_id = %s AND store_id = %s",
            (chain_id, store_id_text),
        )
        row = cur.fetchone()

    if row is None:
        raise KeyError(
            f"Store not found: chain_id={chain_id!r} store_id={store_id_text!r}. "
            "Seed stores before loading prices."
        )

    _store_id_cache[cache_key] = row[0]
    return row[0]


def upsert_products(conn, records: list[ProductRecord]) -> None:
    """
    Batch upsert into `products` (real barcodes only). No-ops on unchanged
    rows (IS DISTINCT FROM guard) so repeated, unchanged item metadata
    doesn't generate dead tuples.
    """
    if not records:
        return

    rows = [
        (r.item_code, r.name, r.manufacturer, r.manufacturer_country, r.item_type)
        for r in records
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO products (
                item_code, name, manufacturer, manufacturer_country, item_type
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (item_code) DO UPDATE SET
                name = EXCLUDED.name,
                manufacturer = EXCLUDED.manufacturer,
                manufacturer_country = EXCLUDED.manufacturer_country,
                item_type = EXCLUDED.item_type,
                updated_at = now()
            WHERE
                products.name IS DISTINCT FROM EXCLUDED.name
                OR products.manufacturer IS DISTINCT FROM EXCLUDED.manufacturer
                OR products.manufacturer_country IS DISTINCT FROM EXCLUDED.manufacturer_country
                OR products.item_type IS DISTINCT FROM EXCLUDED.item_type
            """,
            rows,
        )


def upsert_store_products(conn, records: list[StoreProductRecord]) -> None:
    """
    Batch upsert into `store_products` (non-barcode, chain-internal item
    codes). Scoped to (chain_id, item_code) since these codes collide
    across chains. Same no-op guard as upsert_products.
    """
    if not records:
        return

    rows = [
        (
            r.chain_id,
            r.item_code,
            r.name,
            r.manufacturer,
            r.manufacturer_country,
            r.item_type,
        )
        for r in records
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO store_products (
                chain_id, item_code, name, manufacturer, manufacturer_country, item_type
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, item_code) DO UPDATE SET
                name = EXCLUDED.name,
                manufacturer = EXCLUDED.manufacturer,
                manufacturer_country = EXCLUDED.manufacturer_country,
                item_type = EXCLUDED.item_type,
                updated_at = now()
            WHERE
                store_products.name IS DISTINCT FROM EXCLUDED.name
                OR store_products.manufacturer IS DISTINCT FROM EXCLUDED.manufacturer
                OR store_products.manufacturer_country IS DISTINCT FROM EXCLUDED.manufacturer_country
                OR store_products.item_type IS DISTINCT FROM EXCLUDED.item_type
            """,
            rows,
        )


def upsert_prices(conn, records: list[PriceRecord]) -> None:
    """
    Batch upsert into `prices`. Resolves store_id (text) -> stores.id (int)
    per record, then upserts with an IS DISTINCT FROM guard so unchanged
    prices are true no-ops (no new row version, updated_at stays put).
    """
    if not records:
        return

    rows = []
    for r in records:
        store_id_int = get_store_id(conn, r.chain_id, r.store_id)
        rows.append(
            (
                r.chain_id,
                store_id_int,
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
                chain_id, store_id, item_code, price, unit_price, quantity,
                unit_qty, unit_measure, weighted, package_quantity,
                allow_discount, status, price_update_time, last_sale_datetime
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, store_id, item_code) DO UPDATE SET
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
    conn, chain_id: str, store_id_text: str, item_codes_in_file: set[str]
) -> int:
    """
    Hard-deletes (store_id, item_code) rows that exist in `prices` for this
    store but are absent from the current file -- i.e. items no longer
    sold there. Does NOT touch `products`; another store may still sell
    the item, and an item with zero sellers left is allowed to just sit
    in `products` unreferenced (acceptable per your call).

    Returns the number of rows deleted.
    """
    store_id_int = get_store_id(conn, chain_id, store_id_text)

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM prices
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code <> ALL(%s)
            """,
            (chain_id, store_id_int, list(item_codes_in_file)),
        )
        deleted = cur.rowcount

    if deleted:
        logger.info(
            "Removed %d item(s) no longer sold at chain_id=%s store_id=%s",
            deleted,
            chain_id,
            store_id_text,
        )

    return deleted


# ----------------------------------------------------------------------
# MIGRATION NEEDED before this module works as-is:
#
#   ALTER TABLE prices         ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now();
#   ALTER TABLE products       ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now();
#   ALTER TABLE store_products ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now();
#
# store_products doesn't exist yet -- see schema changes below. prices
# also needs unit_qty/unit_measure/weighted/package_quantity columns
# added (moved here from products), and its old
# `item_code TEXT NOT NULL REFERENCES products(item_code)` FK dropped --
# item_code can now point at either products or store_products depending
# on whether it's a real barcode, so a single FK can't cover both.
#
# On an empty/near-empty table these are metadata-only and instant. On a
# table already holding real rows, DEFAULT now() forces a full rewrite
# (see earlier discussion) -- so run this now, before prices fills up.
#
#   CREATE TABLE store_products (
#       chain_id              TEXT NOT NULL REFERENCES chains(chain_id),
#       item_code             TEXT NOT NULL,
#       name                  TEXT,
#       manufacturer          TEXT,
#       manufacturer_country  TEXT,
#       item_type             INTEGER,
#       updated_at            TIMESTAMPTZ DEFAULT now(),
#       PRIMARY KEY (chain_id, item_code)
#   );
#
#   ALTER TABLE prices
#       ADD COLUMN unit_qty TEXT,
#       ADD COLUMN unit_measure TEXT,
#       ADD COLUMN weighted BOOLEAN,
#       ADD COLUMN package_quantity INTEGER;
#
#   ALTER TABLE prices
#       DROP CONSTRAINT prices_item_code_fkey;  -- name may differ; check \d prices
# ----------------------------------------------------------------------