
"""
utils/processing/delete_suspicious_products.py

Delete global products classified as "delete" or "ultra_high"
by the product data-quality rules.

Runs after feed ingestion and removes dependent records before
deleting global products.
"""

import logging
import re

from db import get_connection

logger = logging.getLogger(__name__)

DELETE_SEVERITIES = {"delete", "ultra_high"}

NAME_PLACEHOLDERS = {
    "לא ידוע",
    "לא ידוע.",
    "unknown",
    "unk",
    "n/a",
    "na",
    "none",
    "null",
    "לא זמין",
    "ללא שם",
}


def normalize(value):
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def is_placeholder_name(value):
    normalized = normalize(value)

    if normalized is None:
        return False

    return normalized.lower() in {
        placeholder.lower()
        for placeholder in NAME_PLACEHOLDERS
    }


def determine_severity(
    *,
    appear_once,
    zero_price,
    all_prices_zero,
    missing_name,
    placeholder_name,
    completely_unused,
    only_null_prices,
    short_name,
    numeric_only_name,
):
    if appear_once and zero_price and missing_name:
        return "delete"

    if appear_once and zero_price:
        return "ultra_high"

    if all_prices_zero and not appear_once:
        return "very_high"

    if appear_once and missing_name:
        return "high"

    if placeholder_name:
        return "high"

    if missing_name:
        return "medium"

    if (
        only_null_prices
        or short_name
        or numeric_only_name
        or appear_once
        or completely_unused
    ):
        return "medium"

    return None


def find_products_to_delete(conn, item_codes=None):
    """Return item codes classified as delete or ultra_high.

    Products from products and pharmacy_products are evaluated as
    one catalog. Prices and promotions are checked in their shared
    tables. Duplicate item codes are evaluated only once.
    """

    scope = ""
    params = ()

    if item_codes is not None:
        scope = "WHERE item_code = ANY(%s)"
        params = (list(item_codes),)

    with conn.cursor() as cur:
        # Combine the two catalogs, preferring the global product name
        # when the same item code exists in both tables.
        cur.execute(
            f"""
            SELECT item_code, name
            FROM products
            {scope}
            ORDER BY item_code
            """,
            params,
        )
        products = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            f"""
            SELECT item_code, name
            FROM pharmacy_products
            {scope}
            ORDER BY item_code
            """,
            params,
        )
        for item_code, name in cur.fetchall():
            products.setdefault(item_code, name)

        # Shared price records for supermarket and pharmacy products.
        cur.execute(
            f"""
            SELECT
                item_code,
                COUNT(*) AS price_rows,
                COUNT(DISTINCT (chain_id, store_id)) AS price_stores,
                COUNT(*) FILTER (WHERE price IS NULL) AS null_price_rows,
                COUNT(*) FILTER (WHERE price = 0) AS zero_price_rows,
                COUNT(*) FILTER (WHERE price > 0) AS positive_price_rows
            FROM prices
            {scope}
            GROUP BY item_code
            """,
            params,
        )

        usage = {
            row[0]: {
                "price_rows": row[1],
                "price_stores": row[2],
                "null_price_rows": row[3],
                "zero_price_rows": row[4],
                "positive_price_rows": row[5],
                "promotion_rows": 0,
            }
            for row in cur.fetchall()
        }

        cur.execute(
            f"""
            SELECT item_code, COUNT(*)
            FROM promotion_items
            {scope}
            GROUP BY item_code
            """,
            params,
        )

        for item_code, promotion_rows in cur.fetchall():
            stats = usage.setdefault(
                item_code,
                {
                    "price_rows": 0,
                    "price_stores": 0,
                    "null_price_rows": 0,
                    "zero_price_rows": 0,
                    "positive_price_rows": 0,
                    "promotion_rows": 0,
                },
            )
            stats["promotion_rows"] = promotion_rows

    to_delete = []

    for item_code, name in products.items():
        stats = usage.get(
            item_code,
            {
                "price_rows": 0,
                "price_stores": 0,
                "null_price_rows": 0,
                "zero_price_rows": 0,
                "positive_price_rows": 0,
                "promotion_rows": 0,
            },
        )

        normalized_name = normalize(name)
        missing_name = normalized_name is None
        placeholder_name = is_placeholder_name(name)

        price_rows = stats["price_rows"]
        zero_price_rows = stats["zero_price_rows"]
        null_price_rows = stats["null_price_rows"]
        positive_price_rows = stats["positive_price_rows"]

        appear_once = price_rows == 1
        zero_price = zero_price_rows > 0

        all_prices_zero = (
            price_rows > 0
            and zero_price_rows == price_rows
        )

        only_null_prices = (
            price_rows > 0
            and null_price_rows == price_rows
            and zero_price_rows == 0
            and positive_price_rows == 0
        )

        completely_unused = (
            price_rows == 0
            and stats["promotion_rows"] == 0
        )

        short_name = (
            normalized_name is not None
            and len(normalized_name) <= 2
        )

        numeric_only_name = (
            normalized_name is not None
            and bool(re.fullmatch(r"\d+", normalized_name))
        )

        severity = determine_severity(
            appear_once=appear_once,
            zero_price=zero_price,
            all_prices_zero=all_prices_zero,
            missing_name=missing_name,
            placeholder_name=placeholder_name,
            completely_unused=completely_unused,
            only_null_prices=only_null_prices,
            short_name=short_name,
            numeric_only_name=numeric_only_name,
        )

        if severity in DELETE_SEVERITIES:
            to_delete.append(item_code)

    return to_delete


def delete_products(conn, item_codes):
    """Delete dependent rows before deleting global products."""

    if not item_codes:
        logger.info("No products eligible for deletion")
        return 0

    dependent_tables = (
        "promotion_items",
        "prices",
        "store_products",
        "pharmacy_store_products",
        "product_enrichment",
    )

    with conn.cursor() as cur:
        for table in dependent_tables:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = %s
                )
                """,
                (table,),
            )

            if not cur.fetchone()[0]:
                continue

            cur.execute(
                f"DELETE FROM {table} WHERE item_code = ANY(%s)",
                (item_codes,),
            )

            logger.info(
                "Deleted %s rows from %s",
                f"{cur.rowcount:,}",
                table,
            )

        cur.execute(
            "DELETE FROM products WHERE item_code = ANY(%s)",
            (item_codes,),
        )

        return cur.rowcount


def main():
    logger.info("Starting suspicious product cleanup")

    with get_connection() as conn:
        item_codes = find_products_to_delete(conn)

        logger.info(
            "Products eligible for deletion: %s",
            f"{len(item_codes):,}",
        )

        deleted = delete_products(conn, item_codes)

        logger.info(
            "Deleted %s global products",
            f"{deleted:,}",
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()