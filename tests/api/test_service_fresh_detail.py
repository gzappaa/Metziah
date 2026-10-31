"""Unit tests for service.get_fresh_product_detail (no database)."""

from decimal import Decimal

import pytest

from api import service


def _row(chain="A", store="S1", price=Decimal("3.50"), promotions=None, **over):
    row = {
        "chain_id": chain, "store_id": store, "item_code": "F1",
        "product_name": "עגבניה",
        "category_id": 1, "category": "ירקות ופירות",
        "subcategory_id": 58, "subcategory": "עגבניה",
        "chain_name_he": f"רשת {chain}", "chain_name_en": chain,
        "brands": ["מותג"], "store_name": f"סניף {chain}{store}", "address": None,
        "city": "תל אביב", "latitude": None, "longitude": None,
        "price": price, "unit_price": None,
        "promotions": promotions or [],
    }
    row.update(over)
    return row


def _promo(promotion_id="PF1", price=2.9, **over):
    promo = {
        "promotion_id": promotion_id, "description": "מבצע",
        "discounted_price": price, "discount_rate": None, "min_qty": 2.0,
        "max_qty": None, "group_id": "G1", "club_id": None,
        "start_datetime": "2026-10-01T00:00:00+00:00", "end_datetime": None,
    }
    promo.update(over)
    return promo


@pytest.fixture
def fake(monkeypatch):
    state = {"rows": [], "calls": []}

    def fake_query(product_name, subcategory_id):
        state["calls"].append((product_name, subcategory_id))
        return state["rows"]

    monkeypatch.setattr(service.queries, "get_fresh_product_detail", fake_query)
    monkeypatch.setattr(
        service, "resolve_shopper_brand",
        lambda store_name, brands, chain_name_he: f"brand:{chain_name_he}",
    )
    return state


def test_blank_name_returns_none_without_querying(fake):
    assert service.get_fresh_product_detail("   ", 58) is None
    assert fake["calls"] == []


def test_no_rows_returns_none(fake):
    fake["rows"] = []

    assert service.get_fresh_product_detail("עגבניה", 58) is None


def test_name_is_stripped_before_the_query(fake):
    fake["rows"] = [_row()]

    service.get_fresh_product_detail("  עגבניה  ", 58)

    assert fake["calls"] == [("עגבניה", 58)]


def test_category_info_comes_from_the_first_row(fake):
    fake["rows"] = [_row()]

    detail = service.get_fresh_product_detail("עגבניה", 58)

    assert (detail.product_name, detail.category, detail.subcategory) == (
        "עגבניה", "ירקות ופירות", "עגבניה"
    )
    assert (detail.category_id, detail.subcategory_id) == (1, 58)


def test_every_store_row_is_kept_with_shopper_brand(fake):
    fake["rows"] = [_row("A"), _row("B"), _row("C", price=None)]

    detail = service.get_fresh_product_detail("עגבניה", 58)

    assert [s.chain_id for s in detail.stores] == ["A", "B", "C"]
    assert detail.stores[0].shopper_brand == "brand:רשת A"


def test_lowest_price_ignores_zero_and_missing_prices(fake):
    fake["rows"] = [
        _row("A", price=Decimal("0.00")),
        _row("B", price=None),
        _row("C", price=Decimal("4.20")),
        _row("D", price=Decimal("3.90")),
    ]

    assert service.get_fresh_product_detail("עגבניה", 58).lowest_price == Decimal("3.90")


def test_lowest_price_is_none_when_no_valid_price(fake):
    fake["rows"] = [_row("A", price=Decimal("0")), _row("B", price=None)]

    assert service.get_fresh_product_detail("עגבניה", 58).lowest_price is None


def test_promotions_are_flattened_with_store_and_chain(fake):
    fake["rows"] = [
        _row("A", promotions=[_promo("PF1", 2.9)]),
        _row("B", promotions=[_promo("PF2", 3.4)]),
    ]

    detail = service.get_fresh_product_detail("עגבניה", 58)

    assert [(p.promotion_id, p.store_name, p.chain_name_he) for p in detail.promotions] == [
        ("PF1", "סניף AS1", "רשת A"),
        ("PF2", "סניף BS1", "רשת B"),
    ]
    assert detail.promotions[0].discounted_price == Decimal("2.9")


def test_lowest_promotion_is_the_cheapest_across_stores(fake):
    fake["rows"] = [
        _row("A", promotions=[_promo("PF1", 3.4)]),
        _row("B", promotions=[_promo("PF2", 2.5), _promo("PF3", 2.9)]),
    ]

    lowest = service.get_fresh_product_detail("עגבניה", 58).lowest_promotion

    assert lowest.promotion_id == "PF2"
    assert lowest.store_name == "סניף BS1"


def test_promotions_without_a_positive_price_are_dropped(fake):
    fake["rows"] = [
        _row("A", promotions=[_promo("PF1", 0), _promo("PF2", None), _promo("PF3", 3.0)])
    ]

    detail = service.get_fresh_product_detail("עגבניה", 58)

    assert [p.promotion_id for p in detail.promotions] == ["PF3"]


def test_no_promotions_gives_empty_list_and_no_lowest_promotion(fake):
    fake["rows"] = [_row("A"), _row("B")]

    detail = service.get_fresh_product_detail("עגבניה", 58)

    assert detail.promotions == [] and detail.lowest_promotion is None