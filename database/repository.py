"""
DB write logic for the price-loading pipeline.

Operations per store's price file:
    1. upsert_products       -- add/update barcode item metadata
    2. upsert_store_products -- add/update non-barcode (internal-code)
                                 item metadata, scoped to
                                 (chain_id, store_id, item_code)
    3. upsert_prices          -- add changed prices only, no-op on unchanged rows
    4. reconcile_removed_items -- hard-delete (store_id, item_code) rows
       that exist in the DB but are no longer present in the current file

NAME RESOLUTION (products.name / store_products.name):
    A simple vote counter (`name_count`), not a full history table.
    - Incoming name matches current name -> name_count += 1
    - Incoming name differs -> name_count -= 1; if it hits 0, the name
      SWITCHES to the incoming value and name_count resets to 1
    - Blank/empty incoming name never participates (skipped entirely)
    This self-stabilizes: whichever name is reported most often across
    loads eventually wins and stays won, without needing a separate
    vote-history table or a scheduled reconciliation job.

MANUFACTURER / MANUFACTURER_COUNTRY:
    Fill-only. Once a field is non-blank, it's never overwritten --
    regardless of what other stores report. An incoming blank never
    overwrites an existing filled value; an incoming filled value only
    gets written if the existing value is currently blank/null.

store_products is scoped to (chain_id, store_id, item_code), NOT just
(chain_id, item_code) -- different branches of the same chain can
report different names for the same internal (non-barcode) code, so
store_id is part of identity here, not just metadata.
"""

import logging
from collections import defaultdict

from database.records import PriceRecord, ProductRecord, StoreProductRecord

logger = logging.getLogger(__name__)

# In-memory cache: (chain_id, store_id_text) -> stores.id
_store_id_cache: dict[tuple[str, str], int] = {}


def _resolve_name(existing_name, existing_count, incoming_name):
    """
    Vote-based name resolution. See module docstring.
    Returns (new_name, new_count).
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
    blank/null. See module docstring.
    """
    if existing_value:
        return existing_value
    return incoming_value or existing_value


def upsert_stores(conn, stores: list) -> None:
    """
    Batch upsert into `stores` from the geocoded JSON seed file. Takes
    models.store.Store instances directly -- their fields already match
    the JSON shape 1:1.

    Empty strings from the JSON (address/city/zip_code sometimes come
    through as "" rather than missing) are normalized to NULL, so a
    blank field reads as "unknown" consistently rather than mixing ""
    and NULL for the same meaning.

    sub_chain_id is intentionally NOT set here -- it's populated later,
    opportunistically, from the feed's own folder structure in
    update_store_subchain(), which is treated as the source of truth.

    ON CONFLICT (chain_id, store_id) DO UPDATE lets you re-run this
    safely after a DROP DATABASE or a re-geocode without duplicating
    rows.
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
                chain_id, store_id, store_name, address, city, zip_code,
                latitude, longitude
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, store_id) DO UPDATE SET
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
    Idempotently makes sure a `chains` row exists before anything that
    FKs to it (stores, store_products, prices) gets inserted.

    No in-memory cache here on purpose: caching "already inserted" before
    the transaction actually commits caused a real bug -- if a later step
    in the same file's processing failed and the transaction got rolled
    back, the cache still believed the chain existed, so it was skipped
    on the next file and the FK violation resurfaced. The insert itself
    is cheap against a ~50-row table, so it's not worth the risk.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chains (chain_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (chain_id,),
        )


def get_store_id(conn, chain_id: str, store_id_text: str) -> int:
    """
    Resolves (chain_id, store_id_text) -> stores.id, the serial PK that
    prices.store_id (and now store_products.store_id) actually reference.
    Cached in memory since a single load run touches the same store
    repeatedly.

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


def update_store_subchain(conn, chain_id: str, store_id_text: str, sub_chain_id: str) -> None:
    """
    Keeps stores.sub_chain_id in sync with what the feed's own directory
    structure says. No-op if the value already matches.
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
            (sub_chain_id, chain_id, store_id_text, sub_chain_id),
        )


def upsert_products(conn, records: list[ProductRecord]) -> None:
    """
    Upsert into `products` (real barcodes only). Reads current state
    first, resolves name via vote-count and manufacturer/country via
    fill-only, then writes only rows that actually changed.
    """
    if not records:
        return

    item_codes = [r.item_code for r in records]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_code, name, name_count, manufacturer, "
            "manufacturer_country, item_type FROM products "
            "WHERE item_code = ANY(%s)",
            (item_codes,),
        )
        existing = {row[0]: row[1:] for row in cur.fetchall()}

    insert_rows = []
    update_rows = []

    for r in records:
        current = existing.get(r.item_code)

        if current is None:
            name = r.name or None
            name_count = 1 if name else 0
            insert_rows.append((
                r.item_code,
                name,
                name_count,
                r.manufacturer or None,
                r.manufacturer_country or None,
                r.item_type,
            ))
            continue

        existing_name, existing_count, existing_mfr, existing_country, existing_type = current

        name, name_count = _resolve_name(existing_name, existing_count, r.name)
        manufacturer = _resolve_fill_only(existing_mfr, r.manufacturer)
        manufacturer_country = _resolve_fill_only(existing_country, r.manufacturer_country)

        if (
            name != existing_name
            or name_count != existing_count
            or manufacturer != existing_mfr
            or manufacturer_country != existing_country
            or r.item_type != existing_type
        ):
            update_rows.append((
                name, name_count, manufacturer, manufacturer_country,
                r.item_type, r.item_code,
            ))

    if insert_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO products (
                    item_code, name, name_count, manufacturer,
                    manufacturer_country, item_type
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
                SET name = %s,
                    name_count = %s,
                    manufacturer = %s,
                    manufacturer_country = %s,
                    item_type = %s,
                    updated_at = now()
                WHERE item_code = %s
                """,
                update_rows,
            )


def upsert_store_products(conn, records: list[StoreProductRecord]) -> None:
    """
    Upsert into `store_products` (non-barcode, chain-internal item
    codes), scoped to (chain_id, store_id, item_code). Same
    read-resolve-write pattern as upsert_products, grouped per chain
    for batched fetching since store_id needs resolving via
    get_store_id first.
    """
    if not records:
        return

    by_chain: dict[str, list[tuple[StoreProductRecord, int]]] = defaultdict(list)
    for r in records:
        store_id_int = get_store_id(conn, r.chain_id, r.store_id)
        by_chain[r.chain_id].append((r, store_id_int))

    insert_rows = []
    update_rows = []

    for chain_id, chain_records in by_chain.items():
        item_codes = [r.item_code for r, _ in chain_records]
        store_ids = [sid for _, sid in chain_records]

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT store_id, item_code, name, name_count,
                       manufacturer, manufacturer_country, item_type
                FROM store_products
                WHERE chain_id = %s
                  AND item_code = ANY(%s)
                  AND store_id = ANY(%s)
                """,
                (chain_id, item_codes, store_ids),
            )
            existing = {(row[0], row[1]): row[2:] for row in cur.fetchall()}

        for r, store_id_int in chain_records:
            current = existing.get((store_id_int, r.item_code))

            if current is None:
                name = r.name or None
                name_count = 1 if name else 0
                insert_rows.append((
                    chain_id, store_id_int, r.item_code,
                    name, name_count,
                    r.manufacturer or None,
                    r.manufacturer_country or None,
                    r.item_type,
                ))
                continue

            existing_name, existing_count, existing_mfr, existing_country, existing_type = current

            name, name_count = _resolve_name(existing_name, existing_count, r.name)
            manufacturer = _resolve_fill_only(existing_mfr, r.manufacturer)
            manufacturer_country = _resolve_fill_only(existing_country, r.manufacturer_country)

            if (
                name != existing_name
                or name_count != existing_count
                or manufacturer != existing_mfr
                or manufacturer_country != existing_country
                or r.item_type != existing_type
            ):
                update_rows.append((
                    name, name_count, manufacturer, manufacturer_country,
                    r.item_type, chain_id, store_id_int, r.item_code,
                ))

    if insert_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO store_products (
                    chain_id, store_id, item_code, name, name_count,
                    manufacturer, manufacturer_country, item_type
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chain_id, store_id, item_code) DO NOTHING
                """,
                insert_rows,
            )

    if update_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE store_products
                SET name = %s,
                    name_count = %s,
                    manufacturer = %s,
                    manufacturer_country = %s,
                    item_type = %s,
                    updated_at = now()
                WHERE chain_id = %s AND store_id = %s AND item_code = %s
                """,
                update_rows,
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
    sold there. Does NOT touch `products`/`store_products`.
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