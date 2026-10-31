"""
utils/products/load_store_products_categories.py

Load store-product categories and subcategories from the reference JSON.
"""

import json
from pathlib import Path

import db


REFERENCE_FILE = Path("data/reference/store_products.json")


def load_store_product_categories():
    """
    Load store-product categories and subcategories into PostgreSQL.

    The JSON structure is:

        {
            "category": [
                "subcategory",
                ...
            ]
        }

    Existing categories and subcategories are preserved.
    New entries are inserted.
    """

    with REFERENCE_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            for category_sort_order, (category_name, subcategories) in enumerate(
                data.items(), start=1
            ):
                cur.execute(
                    """
                    INSERT INTO store_product_categories (
                        name,
                        sort_order
                    )
                    VALUES (%s, %s)
                    ON CONFLICT (name)
                    DO UPDATE SET sort_order = EXCLUDED.sort_order
                    RETURNING id
                    """,
                    (category_name, category_sort_order),
                )

                category_id = cur.fetchone()[0]

                for subcategory_sort_order, subcategory_name in enumerate(
                    subcategories, start=1
                ):
                    cur.execute(
                        """
                        INSERT INTO store_product_subcategories (
                            category_id,
                            name,
                            sort_order
                        )
                        VALUES (%s, %s, %s)
                        ON CONFLICT (category_id, name)
                        DO UPDATE SET sort_order = EXCLUDED.sort_order
                        """,
                        (
                            category_id,
                            subcategory_name,
                            subcategory_sort_order,
                        ),
                    )

        conn.commit()


if __name__ == "__main__":
    load_store_product_categories()