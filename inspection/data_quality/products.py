"""
inspection/data_quality/products.py

Inspect global products for data-quality issues.

This module is read-only and generates a JSON report.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from db import get_connection


REPORT_DIR = Path("inspection/data_quality/reports")

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


def normalize_lower(value):
    value = normalize(value)

    return value.lower() if value else None


def is_placeholder_name(value):
    normalized = normalize_lower(value)

    if normalized is None:
        return False

    return normalized in {
        placeholder.lower()
        for placeholder in NAME_PLACEHOLDERS
    }


def load_products(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                item_code,
                name,
                manufacturer,
                manufacturer_country,
                item_type,
                updated_at
            FROM products
            ORDER BY item_code
            """
        )

        return cur.fetchall()


def load_product_usage(conn):
    """
    Collect price and promotion usage for every global product.

    Missing store_products rows are intentionally not inspected here.
    """

    usage = {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                item_code,
                COUNT(*) AS price_rows,
                COUNT(DISTINCT (chain_id, store_id)) AS price_stores,
                COUNT(*) FILTER (WHERE price IS NULL) AS null_price_rows,
                COUNT(*) FILTER (WHERE price = 0) AS zero_price_rows,
                COUNT(*) FILTER (WHERE price > 0) AS positive_price_rows
            FROM prices
            GROUP BY item_code
            """
        )

        for row in cur.fetchall():
            (
                item_code,
                price_rows,
                price_stores,
                null_price_rows,
                zero_price_rows,
                positive_price_rows,
            ) = row

            usage[item_code] = {
                "price_rows": price_rows,
                "price_stores": price_stores,
                "null_price_rows": null_price_rows,
                "zero_price_rows": zero_price_rows,
                "positive_price_rows": positive_price_rows,
                "promotion_rows": 0,
            }

        cur.execute(
            """
            SELECT
                item_code,
                COUNT(*) AS promotion_rows
            FROM promotion_items
            GROUP BY item_code
            """
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

    return usage


def load_zero_price_details(conn):
    """
    Load the actual regular-price rows where price = 0.
    """

    result = {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                item_code,
                chain_id,
                store_id,
                price,
                status,
                price_update_time,
                last_sale_datetime
            FROM prices
            WHERE price = 0
            ORDER BY item_code, chain_id, store_id
            """
        )

        for row in cur.fetchall():
            (
                item_code,
                chain_id,
                store_id,
                price,
                status,
                price_update_time,
                last_sale_datetime,
            ) = row

            result.setdefault(item_code, []).append(
                {
                    "chain_id": chain_id,
                    "store_id": store_id,
                    "price": price,
                    "status": status,
                    "price_update_time": price_update_time,
                    "last_sale_datetime": last_sale_datetime,
                }
            )

    return result


def get_usage(usage, item_code):
    return usage.get(
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


def inspect_product(
    product,
    usage,
    zero_price_details,
):
    (
        item_code,
        name,
        manufacturer,
        manufacturer_country,
        item_type,
        updated_at,
    ) = product

    stats = get_usage(usage, item_code)

    normalized_name = normalize(name)

    missing_name = normalized_name is None
    placeholder_name = is_placeholder_name(name)

    price_rows = stats["price_rows"]
    zero_price_rows = stats["zero_price_rows"]
    positive_price_rows = stats["positive_price_rows"]
    null_price_rows = stats["null_price_rows"]

    appear_once = price_rows == 1

    all_prices_zero = (
        price_rows > 0
        and zero_price_rows == price_rows
    )

    zero_price = zero_price_rows > 0

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

    reasons = []

    if zero_price:
        reasons.append("zero_price")

    if all_prices_zero:
        reasons.append("all_prices_zero")

    if missing_name:
        reasons.append("missing_name")

    if placeholder_name:
        reasons.append("placeholder_name")

    if appear_once:
        reasons.append("appear_once")

    if only_null_prices:
        reasons.append("only_null_prices")

    if completely_unused:
        reasons.append("completely_unused")

    if short_name:
        reasons.append("short_name")

    if numeric_only_name:
        reasons.append("numeric_only_name")

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

    # Normal products do not enter the report.
    if severity is None:
        return None

    result = {
        "item_code": item_code,
        "name": name,
        "manufacturer": manufacturer,
        "manufacturer_country": manufacturer_country,
        "item_type": item_type,
        "updated_at": updated_at,
        "severity": severity,
        "reasons": reasons,
        "usage": {
            "price_rows": price_rows,
            "price_stores": stats["price_stores"],
            "null_price_rows": null_price_rows,
            "zero_price_rows": zero_price_rows,
            "positive_price_rows": positive_price_rows,
            "promotion_rows": stats["promotion_rows"],
        },
    }

    if item_code in zero_price_details:
        result["zero_price_locations"] = zero_price_details[item_code]

    return result


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
    # Appears once + zero price + no name:
    # strongest candidate for deletion.
    if appear_once and zero_price and missing_name:
        return "delete"

    # Appears once + zero price.
    if appear_once and zero_price:
        return "ultra_high"

    # Multiple appearances, but every regular price is 0.
    if all_prices_zero and not appear_once:
        return "very_high"

    # Appears once + missing name.
    if appear_once and missing_name:
        return "high"

    # Placeholder names are suspicious, but not as strong
    # as the zero-price combinations above.
    if placeholder_name:
        return "high"

    # Multiple appearances + missing name.
    if missing_name:
        return "medium"

    # Weak/secondary signals.
    if (
        only_null_prices
        or short_name
        or numeric_only_name
        or appear_once
        or completely_unused
    ):
        return "medium"

    # A zero price that is mixed with legitimate positive prices
    # is tracked, but is not suspicious enough to report by itself.
    return None


def build_summary(products, usage):
    total = len(products)

    without_price = 0
    without_name = 0
    placeholder_name = 0

    appear_once = 0
    appear_once_with_zero_price = 0

    zero_price = 0
    all_prices_zero = 0
    only_null_prices = 0

    completely_unused = 0
    short_name = 0
    numeric_only_name = 0

    # These are informational statistics only.
    without_manufacturer = 0

    price_coverage = {
        "0_stores": 0,
        "1_store": 0,
        "2_to_5_stores": 0,
        "6_to_10_stores": 0,
        "11_plus_stores": 0,
    }

    for product in products:
        item_code = product[0]
        name = product[1]
        manufacturer = product[2]

        stats = get_usage(usage, item_code)

        normalized_name = normalize(name)

        if stats["price_rows"] == 0:
            without_price += 1

        if normalized_name is None:
            without_name += 1

        if is_placeholder_name(name):
            placeholder_name += 1

        if normalize(manufacturer) is None:
            without_manufacturer += 1

        if stats["price_rows"] == 1:
            appear_once += 1

            if stats["zero_price_rows"] > 0:
                appear_once_with_zero_price += 1

        if stats["zero_price_rows"] > 0:
            zero_price += 1

        if (
            stats["price_rows"] > 0
            and stats["zero_price_rows"] == stats["price_rows"]
        ):
            all_prices_zero += 1

        if (
            stats["price_rows"] > 0
            and stats["null_price_rows"] == stats["price_rows"]
            and stats["zero_price_rows"] == 0
            and stats["positive_price_rows"] == 0
        ):
            only_null_prices += 1

        if (
            stats["price_rows"] == 0
            and stats["promotion_rows"] == 0
        ):
            completely_unused += 1

        if normalized_name is not None and len(normalized_name) <= 2:
            short_name += 1

        if (
            normalized_name is not None
            and bool(re.fullmatch(r"\d+", normalized_name))
        ):
            numeric_only_name += 1

        stores = stats["price_stores"]

        if stores == 0:
            price_coverage["0_stores"] += 1
        elif stores == 1:
            price_coverage["1_store"] += 1
        elif stores <= 5:
            price_coverage["2_to_5_stores"] += 1
        elif stores <= 10:
            price_coverage["6_to_10_stores"] += 1
        else:
            price_coverage["11_plus_stores"] += 1

    return {
        "total_global_products": total,
        "without_price": without_price,
        "without_name": without_name,
        "placeholder_name": placeholder_name,
        "without_manufacturer": without_manufacturer,
        "appear_once": appear_once,
        "appear_once_with_zero_price": appear_once_with_zero_price,
        "zero_price": zero_price,
        "all_prices_zero": all_prices_zero,
        "only_null_prices": only_null_prices,
        "completely_unused": completely_unused,
        "short_name": short_name,
        "numeric_only_name": numeric_only_name,
        "price_coverage": price_coverage,
    }


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    return str(value)


def write_report(report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = REPORT_DIR / "products.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
            default=json_default,
        )

    return output_path


def main():
    conn = get_connection()

    try:
        products = load_products(conn)
        usage = load_product_usage(conn)
        zero_price_details = load_zero_price_details(conn)

        suspicious_products = []

        for product in products:
            inspected = inspect_product(
                product=product,
                usage=usage,
                zero_price_details=zero_price_details,
            )

            if inspected is not None:
                suspicious_products.append(inspected)

        severity_order = {
            "delete": 0,
            "ultra_high": 1,
            "very_high": 2,
            "high": 3,
            "medium": 4,
        }

        suspicious_products.sort(
            key=lambda product: (
                severity_order.get(product["severity"], 99),
                product["item_code"],
            )
        )

        summary = build_summary(
            products=products,
            usage=usage,
        )

        report = {
            "summary": summary,
            "products": suspicious_products,
        }

        output_path = write_report(report)

        print(f"Global products inspected: {len(products):,}")
        print(
            f"Suspicious products reported: "
            f"{len(suspicious_products):,}"
        )
        print(f"Report written to: {output_path}")

        print()
        print("Severity:")

        for severity in (
            "delete",
            "ultra_high",
            "very_high",
            "high",
            "medium",
        ):
            count = sum(
                product["severity"] == severity
                for product in suspicious_products
            )

            print(f"  {severity}: {count:,}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()