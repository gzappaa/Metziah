
"""Analyze image coverage for product enrichment records."""

from pathlib import Path

from db import get_connection


ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = ROOT / "data" / "images"


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT item_code, source
                FROM product_enrichment
                WHERE item_code IS NOT NULL
                  AND source IS NOT NULL
                """
            )
            rows = cur.fetchall()

    found = {
        item_code
        for item_code, source in rows
        if (
            IMAGES_DIR / source.strip().lower() / f"{item_code}_001.jpg"
        ).is_file()
    }

    print(f"Product enrichment item codes: {len({item_code for item_code, _ in rows})}")
    print(f"Found images (_001.jpg): {len(found)}")


if __name__ == "__main__":
    main()