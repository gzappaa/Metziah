"""Unit tests for service.search_unenriched_products (no database)."""

from decimal import Decimal

import pytest

from api import service


def _item(**over):
    item = {"item_code": "111", "name": "מוצר", "name_he": "מוצר"}
    item.update(over)
    return item


@pytest.fixture
def fake(monkeypatch):
    state = {
        "search": {"items": [], "total": 0, "limit": 20, "offset": 0},
        "prices": {},
        "search_args": None,
        "price_args": None,
    }

    def fake_search(q, limit, offset):
        state["search_args"] = (q, limit, offset)
        return state["search"]

    def fake_prices(item_codes):
        state["price_args"] = list(item_codes)
        return state["prices"]

    monkeypatch.setattr(service.queries, "search_unenriched_products", fake_search)
    monkeypatch.setattr(service.queries, "get_prices_for_products", fake_prices)
    return state


class TestSearchUnenrichedProducts:
    def test_builds_template_friendly_rows(self, fake):
        fake["search"] = {"items": [_item()], "total": 1, "limit": 20, "offset": 0}
        fake["prices"] = {
            "111": [
                {"price": Decimal("6.50"), "chain_id": "C1", "store_id": "S1"},
                {"price": Decimal("5.90"), "chain_id": "C1", "store_id": "S2"},
                {"price": Decimal("5.90"), "chain_id": "C2", "store_id": "S1"},
            ]
        }

        result = service.search_unenriched_products("מוצר")

        assert result["total"] == 1
        assert result["products"][0] == {
            "identifier": "111",
            "brand": None,
            "category": "",
            "name": "מוצר",
            "min_price": Decimal("5.90"),
            "store_count": 3,
        }

    def test_passes_arguments_through_and_echoes_paging(self, fake):
        fake["search"] = {"items": [], "total": 7, "limit": 5, "offset": 10}

        result = service.search_unenriched_products("x", limit=5, offset=10)

        assert fake["search_args"] == ("x", 5, 10)
        assert (result["total"], result["limit"], result["offset"]) == (7, 5, 10)
        assert result["products"] == []

    def test_prices_are_fetched_once_for_all_items(self, fake):
        fake["search"] = {
            "items": [_item(), _item(item_code="222")],
            "total": 2, "limit": 20, "offset": 0,
        }

        service.search_unenriched_products("x")

        assert fake["price_args"] == ["111", "222"]

    def test_name_falls_back_to_barcode(self, fake):
        fake["search"] = {
            "items": [_item(name=None, name_he=None)],
            "total": 1, "limit": 20, "offset": 0,
        }

        assert service.search_unenriched_products("x")["products"][0]["name"] == "111"

    def test_no_prices_gives_none_min_price_and_zero_stores(self, fake):
        fake["search"] = {"items": [_item()], "total": 1, "limit": 20, "offset": 0}
        fake["prices"] = {"111": []}

        product = service.search_unenriched_products("x")["products"][0]

        assert product["min_price"] is None
        assert product["store_count"] == 0

    def test_item_missing_from_price_map_is_handled(self, fake):
        fake["search"] = {"items": [_item()], "total": 1, "limit": 20, "offset": 0}
        fake["prices"] = {}

        product = service.search_unenriched_products("x")["products"][0]

        assert product["min_price"] is None and product["store_count"] == 0

    def test_min_price_ignores_zero_and_none_prices(self, fake):
        fake["search"] = {"items": [_item()], "total": 1, "limit": 20, "offset": 0}
        fake["prices"] = {
            "111": [
                {"price": Decimal("0.00"), "chain_id": "C1", "store_id": "S1"},
                {"price": None, "chain_id": "C1", "store_id": "S2"},
                {"price": Decimal("5.90"), "chain_id": "C1", "store_id": "S3"},
            ]
        }

        product = service.search_unenriched_products("x")["products"][0]

        assert product["min_price"] == Decimal("5.90")