"""Tests for shopper-facing API service logic."""

from unittest.mock import patch

import pytest

from api import service


def test_get_product_detail_returns_none_for_unknown_barcode() -> None:
    with patch.object(service.queries, "get_product", return_value=None):
        result = service.get_product_detail("0000000000000")

    assert result is None


def test_get_product_detail_returns_product_and_enrichment() -> None:
    product = {
        "item_code": "7290000000001",
        "name_he": "מוצר לבדיקה",
        "name_en": "Test product",
        "brand_he": "מותג",
        "brand_en": "Brand",
        "family_he": None,
        "family_en": None,
        "department_he": None,
        "category_he": None,
        "subcategory_he": None,
        "description_he": None,
        "description_en": None,
        "ingredients_he": None,
        "ingredients_en": None,
    }
    enrichment = {
        **product,
        "source": "test",
        "source_file": None,
        "local_name": "מוצר לבדיקה",
        "category_path_he": [],
        "category_path_en": [],
        "nutrition_raw": {},
        "created_at": None,
        "updated_at": None,
        "nutrition": [],
    }

    with (
        patch.object(service.queries, "get_product", return_value=product),
        patch.object(service.queries, "get_prices", return_value=[]),
        patch.object(service.queries, "get_promotions", return_value=[]),
        patch.object(
            service.queries,
            "get_enrichment",
            return_value=enrichment,
        ),
    ):
        result = service.get_product_detail("7290000000001")

    assert result is not None
    assert result.product.item_code == "7290000000001"
    assert result.enrichment is not None
    assert result.enrichment.source == "test"
    assert result.prices == []
    assert result.promotions == []


def test_get_product_detail_resolves_price_shopper_brand() -> None:
    product = {
        "item_code": "7290000000001",
        "name_he": "מוצר לבדיקה",
    }
    price = {
        "item_code": "7290000000001",
        "chain_id": "test-chain",
        "store_id": "1",
        "chain_name_he": "רשת בדיקה",
        "chain_name_en": "Test chain",
        "brands": ["מותג לצרכן"],
        "store_name": "סניף בדיקה",
        "address": None,
        "city": None,
        "latitude": None,
        "longitude": None,
        "price": 10,
        "unit_price": None,
        "quantity": None,
        "unit_qty": None,
        "unit_measure": None,
        "weighted": None,
        "package_quantity": None,
        "allow_discount": None,
        "status": None,
        "price_update_time": None,
        "last_sale_datetime": None,
        "updated_at": None,
    }

    with (
        patch.object(service.queries, "get_product", return_value=product),
        patch.object(service.queries, "get_prices", return_value=[price]),
        patch.object(service.queries, "get_promotions", return_value=[]),
        patch.object(service.queries, "get_enrichment", return_value=None),
        patch.object(
            service,
            "resolve_shopper_brand",
            return_value="מותג לצרכן",
        ) as resolve_brand,
    ):
        result = service.get_product_detail("7290000000001")

    assert result is not None
    assert len(result.prices) == 1
    assert result.prices[0].shopper_brand == "מותג לצרכן"
    resolve_brand.assert_called_once_with(
        "סניף בדיקה",
        ["מותג לצרכן"],
        "רשת בדיקה",
    )


def test_search_products_returns_valid_schema() -> None:
    query_result = {
        "items": [
            {
                "item_code": "7290000000001",
                "name_he": "מוצר לבדיקה",
                "name_en": "Test product",
            }
        ],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }

    with patch.object(service.queries, "search", return_value=query_result):
        result = service.search_products("מוצר")

    assert result.total == 1
    assert result.items[0].item_code == "7290000000001"


def test_get_store_product_categories_returns_valid_schemas() -> None:
    rows = [
        {"id": 1, "name": "ירקות ופירות", "sort_order": 1},
        {"id": 2, "name": "קצבייה", "sort_order": 2},
    ]

    with patch.object(
        service.queries,
        "get_store_product_categories",
        return_value=rows,
    ):
        result = service.get_store_product_categories()

    assert len(result) == 2
    assert result[0].name == "ירקות ופירות"
    assert result[1].id == 2


def test_get_store_product_subcategories_filters_by_category() -> None:
    rows = [
        {
            "id": 10,
            "category_id": 1,
            "category": "ירקות ופירות",
            "name": "אבוקדו",
            "sort_order": 1,
        }
    ]

    with patch.object(
        service.queries,
        "get_store_product_subcategories",
        return_value=rows,
    ) as get_subcategories:
        result = service.get_store_product_subcategories(category_id=1)

    get_subcategories.assert_called_once_with(1)
    assert len(result) == 1
    assert result[0].name == "אבוקדו"
    assert result[0].category_id == 1


@pytest.mark.parametrize(
    "query_function",
    [
        "get_store_products_by_subcategory",
        "search_store_products",
    ],
)
def test_store_product_results_resolve_shopper_brand(
    query_function: str,
) -> None:
    row = {
        "chain_id": "test-chain",
        "store_id": "1",
        "item_code": "store-item-1",
        "product_name": "חזה עוף",
        "chain_name_he": "רשת בדיקה",
        "chain_name_en": "Test chain",
        "brands": ["מותג לצרכן"],
        "store_name": "סניף בדיקה",
        "address": None,
        "city": "תל אביב",
        "latitude": None,
        "longitude": None,
    }

    if query_function == "get_store_products_by_subcategory":
        row.update(
            {
                "category_id": 1,
                "category": "קצבייה",
                "subcategory_id": 10,
                "subcategory": "חזה עוף",
            }
        )
        query_args = (10,)
    else:
        query_args = ("חזה עוף",)

    query_result = {
        "items": [row],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }

    with (
        patch.object(
            service.queries,
            query_function,
            return_value=query_result,
        ) as query,
        patch.object(
            service,
            "resolve_shopper_brand",
            return_value="מותג לצרכן",
        ) as resolve_brand,
    ):
        if query_function == "get_store_products_by_subcategory":
            result = service.get_store_products_by_subcategory(10)
        else:
            result = service.search_store_products("חזה עוף")

    query.assert_called_once_with(*query_args, limit=20, offset=0)
    assert result.total == 1
    assert result.items[0].item_code == "store-item-1"
    assert result.items[0].shopper_brand == "מותג לצרכן"
    resolve_brand.assert_called_once_with(
        "סניף בדיקה",
        ["מותג לצרכן"],
        "רשת בדיקה",
    )


def test_search_store_products_returns_empty_result() -> None:
    empty_result = {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }

    with patch.object(
        service.queries,
        "search_store_products",
        return_value=empty_result,
    ):
        result = service.search_store_products("no-match")

    assert result.items == []
    assert result.total == 0