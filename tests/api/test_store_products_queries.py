"""Tests for store-product category and search queries."""

import pytest

from api import queries


def test_get_store_product_categories_returns_list() -> None:
    result = queries.get_store_product_categories()

    assert isinstance(result, list)
    if result:
        assert {"id", "name", "sort_order"} <= result[0].keys()


def test_get_store_product_subcategories_returns_list() -> None:
    result = queries.get_store_product_subcategories()

    assert isinstance(result, list)
    if result:
        assert {
            "id",
            "category_id",
            "category",
            "name",
            "sort_order",
        } <= result[0].keys()


def test_get_store_product_subcategories_filters_by_category() -> None:
    categories = queries.get_store_product_categories()

    if not categories:
        pytest.skip("No store-product categories are seeded")

    category_id = categories[0]["id"]
    result = queries.get_store_product_subcategories(category_id)

    assert all(row["category_id"] == category_id for row in result)


def test_get_store_products_by_subcategory_validates_pagination() -> None:
    with pytest.raises(ValueError):
        queries.get_store_products_by_subcategory(1, limit=0)

    with pytest.raises(ValueError):
        queries.get_store_products_by_subcategory(1, offset=-1)


def test_search_store_products_empty_query() -> None:
    result = queries.search_store_products("")

    assert result == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }


def test_search_store_products_validates_pagination() -> None:
    with pytest.raises(ValueError):
        queries.search_store_products("חזה עוף", limit=101)

    with pytest.raises(ValueError):
        queries.search_store_products("חזה עוף", offset=-1)