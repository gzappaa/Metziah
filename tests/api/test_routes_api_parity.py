"""Route tests for the UI-parity JSON endpoints. No database: everything is faked."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import queries, routes_api, service
from api.schemas import (
    FreshProductDetail,
    FreshStorePrice,
    FreshStorePromotion,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_api.router)
    return TestClient(app)


@pytest.fixture
def rec():
    """Records the arguments each faked function was called with."""
    return {}


def fake(monkeypatch, target, name, result, rec, key=None):
    key = key or name

    def _fake(*args, **kwargs):
        rec[key] = (args, kwargs)
        return result

    monkeypatch.setattr(target, name, _fake)


PAGE = {"items": [], "total": 0, "limit": 20, "offset": 0}


# --------------------------------------------------------------------------
# stats / packaged categories
# --------------------------------------------------------------------------

def test_stats(client, monkeypatch, rec):
    stats = {"total_stores": 10, "total_brands": 4, "total_fresh_products": 99}
    fake(monkeypatch, queries, "get_catalog_stats", stats, rec)

    response = client.get("/api/v1/stats")

    assert response.status_code == 200
    assert response.json() == stats


def test_packaged_categories_turns_null_subcategories_into_empty_list(
    client, monkeypatch, rec
):
    fake(
        monkeypatch, queries, "get_packaged_product_categories",
        [
            {"name": "חלב", "count": 3, "subcategories": ["א", "ב"]},
            {"name": "שונות", "count": 1, "subcategories": None},
        ],
        rec,
    )

    body = client.get("/api/v1/categories/packaged").json()

    assert body[0]["subcategories"] == ["א", "ב"]
    assert body[1]["subcategories"] == []


# --------------------------------------------------------------------------
# packaged products by category
# --------------------------------------------------------------------------

def test_products_by_category_passes_arguments(client, monkeypatch, rec):
    fake(monkeypatch, queries, "get_packaged_products_by_category", dict(PAGE), rec)

    response = client.get(
        "/api/v1/products", params={"category": "חלב וביצים", "limit": 5, "offset": 10}
    )

    assert response.status_code == 200
    assert rec["get_packaged_products_by_category"] == (
        ("חלב וביצים",), {"limit": 5, "offset": 10}
    )


def test_products_by_category_defaults(client, monkeypatch, rec):
    fake(monkeypatch, queries, "get_packaged_products_by_category", dict(PAGE), rec)

    client.get("/api/v1/products", params={"category": "x"})

    assert rec["get_packaged_products_by_category"][1] == {"limit": 40, "offset": 0}


@pytest.mark.parametrize(
    "params",
    [{}, {"category": ""}, {"category": "x", "limit": 0},
     {"category": "x", "limit": 101}, {"category": "x", "offset": -1}],
)
def test_products_by_category_rejects_bad_parameters(client, monkeypatch, rec, params):
    fake(monkeypatch, queries, "get_packaged_products_by_category", dict(PAGE), rec)

    assert client.get("/api/v1/products", params=params).status_code == 422
    assert "get_packaged_products_by_category" not in rec


# --------------------------------------------------------------------------
# search (UI-shaped hits)
# --------------------------------------------------------------------------

def test_search_maps_products_to_items_and_strips_q(client, monkeypatch, rec):
    result = {
        "products": [
            {"identifier": "1", "name": "חלב", "brand": "תנובה",
             "category": "חלב וביצים", "min_price": Decimal("5.90"), "store_count": 3}
        ],
        "total": 1, "limit": 20, "offset": 0,
    }
    fake(monkeypatch, service, "search_products", result, rec)

    body = client.get("/api/v1/products/search", params={"q": "  חלב  "}).json()

    assert rec["search_products"] == (("חלב",), {"limit": 20, "offset": 0})
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["items"][0] == {
        "identifier": "1", "name": "חלב", "brand": "תנובה",
        "category": "חלב וביצים", "min_price": "5.90", "store_count": 3,
    }


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 201}]
)
def test_search_rejects_bad_parameters(client, monkeypatch, rec, params):
    fake(monkeypatch, service, "search_products", {}, rec)

    assert client.get("/api/v1/products/search", params=params).status_code == 422


def test_search_is_not_captured_by_the_barcode_route(client, monkeypatch, rec):
    fake(
        monkeypatch, service, "search_products",
        {"products": [], "total": 0, "limit": 20, "offset": 0}, rec,
    )
    monkeypatch.setattr(
        routes_api, "get_product_detail",
        lambda barcode: pytest.fail("/products/search was treated as a barcode"),
    )

    assert client.get("/api/v1/products/search").status_code == 200


# --------------------------------------------------------------------------
# fresh categories / subcategories / products
# --------------------------------------------------------------------------

def test_fresh_categories_expose_count(client, monkeypatch, rec):
    fake(
        monkeypatch, queries, "get_store_product_categories",
        [{"id": 1, "name": "ירקות ופירות", "sort_order": 1, "count": 12}], rec,
    )

    assert client.get("/api/v1/fresh/categories").json() == [
        {"id": 1, "name": "ירקות ופירות", "sort_order": 1, "count": 12}
    ]


def test_fresh_subcategories(client, monkeypatch, rec):
    fake(
        monkeypatch, queries, "get_store_product_subcategories",
        [{"id": 5, "category_id": 1, "category": "ירקות", "name": "עגבניה",
          "sort_order": 1, "count": 7}], rec,
    )

    body = client.get("/api/v1/fresh/categories/1/subcategories").json()

    assert rec["get_store_product_subcategories"] == ((1,), {})
    assert body[0]["count"] == 7


@pytest.mark.parametrize("category_id", [0, 32768, "abc"])
def test_fresh_subcategories_rejects_bad_category_id(client, monkeypatch, rec, category_id):
    fake(monkeypatch, queries, "get_store_product_subcategories", [], rec)

    response = client.get(f"/api/v1/fresh/categories/{category_id}/subcategories")

    assert response.status_code == 422
    assert "get_store_product_subcategories" not in rec


def test_fresh_products(client, monkeypatch, rec):
    fake(
        monkeypatch, queries, "get_store_products_by_subcategory",
        {"items": [{"product_name": "עגבניה", "store_count": 2,
                    "lowest_price": Decimal("3.50"), "cheapest_promotion": None}],
         "total": 1, "limit": 3, "offset": 0}, rec,
    )

    body = client.get("/api/v1/fresh/products", params={"subcategory_id": 58, "limit": 3}).json()

    assert rec["get_store_products_by_subcategory"] == ((58,), {"limit": 3, "offset": 0})
    assert body["items"][0]["lowest_price"] == "3.50"
    assert body["items"][0]["cheapest_promotion"] is None


@pytest.mark.parametrize(
    "params",
    [{}, {"subcategory_id": 0}, {"subcategory_id": 2_147_483_648},
     {"subcategory_id": 1, "limit": 0}, {"subcategory_id": 1, "offset": -1}],
)
def test_fresh_products_rejects_bad_parameters(client, monkeypatch, rec, params):
    fake(monkeypatch, queries, "get_store_products_by_subcategory", dict(PAGE), rec)

    assert client.get("/api/v1/fresh/products", params=params).status_code == 422


# --------------------------------------------------------------------------
# fresh product detail
# --------------------------------------------------------------------------

def _detail():
    promo = FreshStorePromotion(
        promotion_id="PF1", discounted_price=Decimal("2.90"),
        store_name="סניף", chain_name_he="רשת",
    )
    return FreshProductDetail(
        product_name="עגבניה", category_id=1, category="ירקות ופירות",
        subcategory_id=58, subcategory="עגבניה", lowest_price=Decimal("3.50"),
        lowest_promotion=promo, promotions=[promo],
        stores=[FreshStorePrice(
            chain_id="C", store_id="S1", item_code="F1", chain_name_he="רשת",
            chain_name_en="chain", price=Decimal("3.50"),
        )],
    )


def test_fresh_detail_returns_service_result(client, monkeypatch, rec):
    fake(monkeypatch, service, "get_fresh_product_detail", _detail(), rec)

    response = client.get(
        "/api/v1/fresh/products/detail", params={"name": "עגבניה", "subcategory_id": 58}
    )

    assert response.status_code == 200
    body = response.json()
    assert rec["get_fresh_product_detail"] == (("עגבניה", 58), {})
    assert body["lowest_price"] == "3.50"
    assert body["lowest_promotion"]["store_name"] == "סניף"
    assert len(body["stores"]) == 1 and len(body["promotions"]) == 1


def test_fresh_detail_404_when_not_found(client, monkeypatch, rec):
    fake(monkeypatch, service, "get_fresh_product_detail", None, rec)

    response = client.get(
        "/api/v1/fresh/products/detail", params={"name": "nope", "subcategory_id": 58}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Fresh product not found"


@pytest.mark.parametrize(
    "params",
    [{"subcategory_id": 58}, {"name": "x"}, {"name": "", "subcategory_id": 58},
     {"name": "x" * 301, "subcategory_id": 58}, {"name": "x", "subcategory_id": 0}],
)
def test_fresh_detail_rejects_bad_parameters(client, monkeypatch, rec, params):
    fake(monkeypatch, service, "get_fresh_product_detail", _detail(), rec)

    assert client.get("/api/v1/fresh/products/detail", params=params).status_code == 422
    assert "get_fresh_product_detail" not in rec


# --------------------------------------------------------------------------
# fresh search
# --------------------------------------------------------------------------

def test_fresh_search_passes_through(client, monkeypatch, rec):
    from api.schemas import StoreProduct, StoreProductSearchResult

    result = StoreProductSearchResult(
        items=[StoreProduct(
            chain_id="C", store_id="S1", item_code="F1", product_name="עגבניה",
            chain_name_he="רשת", chain_name_en="c",
        )],
        total=1, limit=20, offset=0,
    )
    fake(monkeypatch, service, "search_store_products", result, rec)

    body = client.get("/api/v1/fresh/search", params={"q": "עגבניה", "limit": 5}).json()

    assert rec["search_store_products"] == (("עגבניה",), {"limit": 5, "offset": 0})
    assert body["total"] == 1 and body["items"][0]["product_name"] == "עגבניה"