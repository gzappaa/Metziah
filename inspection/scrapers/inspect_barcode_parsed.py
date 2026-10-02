"""
inspection/scrapers/inspect_barcode_parsed.py

Inspect parsed product barcodes against the products database.
"""

import json
from pathlib import Path

from db import get_connection


PARSED_DIR = Path("data/parsed")
REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
REPORT_PATH = REPORT_DIR / "barcode_parsed.json"


def get_product_name(record: dict) -> str:
    """Return the best available product name."""
    return record.get("name_he") or record.get("local_name") or ""


def get_category(record: dict) -> str:
    """Return the most specific available category."""
    category_path = record.get("category_path_he") or []

    if category_path:
        return " > ".join(
            str(category)
            for category in category_path
            if category
        )

    return record.get("department_name") or ""


def main() -> None:
    products: dict[str, dict] = {}
    records = 0
    files = 0

    for path in sorted(PARSED_DIR.glob("*/products_parsed.json")):
        files += 1

        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if not line:
                    continue

                record = json.loads(line)
                records += 1

                barcode = record.get("barcode")

                if not barcode:
                    continue

                barcode = str(barcode)

                if barcode not in products:
                    products[barcode] = {
                        "barcode": barcode,
                        "name": get_product_name(record),
                        "department": record.get("department_name") or "",
                        "family": record.get("family_name_he") or "",
                        "category": get_category(record),
                        "source": str(path),
                    }

    barcodes = set(products)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_code
                FROM products
                WHERE item_code = ANY(%s)
                """,
                (list(barcodes),),
            )

            existing_barcodes = {
                str(row[0])
                for row in cur.fetchall()
            }

    missing_barcodes = sorted(barcodes - existing_barcodes)

    total = len(barcodes)
    existing = len(existing_barcodes)
    missing = len(missing_barcodes)

    percentage = existing / total * 100 if total else 0

    report = {
        "summary": {
            "files": files,
            "total_records": records,
            "distinct_barcodes": total,
            "already_in_products": existing,
            "missing_from_products": missing,
            "existing_percentage": round(percentage, 2),
        },
        "missing_products": [
            products[barcode]
            for barcode in missing_barcodes
        ],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()