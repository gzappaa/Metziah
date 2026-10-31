import json

from db import get_connection
from utils.products import load_store_products_categories as loader


def cleanup_test_categories():
    """Remove test categories and their subcategories from the database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM store_product_subcategories
                WHERE category_id IN (
                    SELECT id
                    FROM store_product_categories
                    WHERE name IN (%s, %s)
                )
                """,
                ("TEST_CATEGORY_A", "TEST_CATEGORY_B"),
            )
            cur.execute(
                """
                DELETE FROM store_product_categories
                WHERE name IN (%s, %s)
                """,
                ("TEST_CATEGORY_A", "TEST_CATEGORY_B"),
            )
        conn.commit()


def test_load_store_product_categories_inserts_reference_data(monkeypatch, tmp_path):
    reference = {
        "TEST_CATEGORY_A": [
            "TEST_SUBCATEGORY_A1",
            "TEST_SUBCATEGORY_A2",
        ],
        "TEST_CATEGORY_B": ["TEST_SUBCATEGORY_B1"],
    }
    reference_file = tmp_path / "store_products.json"
    reference_file.write_text(json.dumps(reference), encoding="utf-8")
    monkeypatch.setattr(loader, "REFERENCE_FILE", reference_file)

    # Remove leftovers from any previous failed test run.
    cleanup_test_categories()

    try:
        loader.load_store_product_categories()

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.name,
                        c.sort_order,
                        s.name,
                        s.sort_order
                    FROM store_product_categories AS c
                    JOIN store_product_subcategories AS s
                        ON s.category_id = c.id
                    WHERE c.name IN (%s, %s)
                    ORDER BY c.sort_order, s.sort_order
                    """,
                    ("TEST_CATEGORY_A", "TEST_CATEGORY_B"),
                )
                rows = cur.fetchall()

        assert rows == [
            ("TEST_CATEGORY_A", 1, "TEST_SUBCATEGORY_A1", 1),
            ("TEST_CATEGORY_A", 1, "TEST_SUBCATEGORY_A2", 2),
            ("TEST_CATEGORY_B", 2, "TEST_SUBCATEGORY_B1", 1),
        ]
    finally:
        # The loader commits to the real database, so explicitly remove test data.
        cleanup_test_categories()