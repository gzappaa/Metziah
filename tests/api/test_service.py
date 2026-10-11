"""Unit tests for api/service.py and api/schemas.py (no database)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from api import service
from api.schemas import Price, Product, ProductEnrichment, Promotion


def _price_row(**over):
    row = {
        "item_code": "111",
        "chain_id": "C1",
        "store_id": "S1",
        "chain_name_he": "רשת",
        "chain_name_en": "chain",
        "brands": ["מותג"],
        "store_name": "סניף",
        "price": Decimal("5.90"),
    }
    row.update(over)
    return row


def _promo_row(**over):
    row = {
        "item_code": "111",
        "chain_id": "C1",
        "promotion_id": "P1",
        "store_id": "S1",
        "chain_name_he": "רשת",
        "chain_name_en": "chain",
        "brands": [],
        "group_id": "G1",
        "discounted_price": Decimal("4.90"),
        "start_datetime": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    row.update(over)
    return row


@pytest.fixture
def fake_queries(monkeypatch):
    """Replace every function service.py calls on `queries`."""
    state = {
        "product": {"item_code": "111", "name_he": "חלב"},
        "prices": [],
        "promotions": [],
        "enrichment": None,
        "search": {"items": [], "total": 0, "limit": 20, "offset": 0},
    }
    monkeypatch.setattr(service.queries, "get_product", lambda barcode: state["product"])
    monkeypatch.setattr(service.queries, "get_prices", lambda barcode: state["prices"])
    monkeypatch.setattr(service.queries, "get_promotions", lambda barcode: state["promotions"])
    monkeypatch.setattr(service.queries, "get_enrichment", lambda barcode: state["enrichment"])
    monkeypatch.setattr(service.queries, "search", lambda q, limit, offset: state["search"])
    monkeypatch.setattr(
        service, "resolve_shopper_brand", lambda store_name, brands, chain_name_he: f"brand:{chain_name_he}"
    )
    return state


# --------------------------------------------------------------------------
# get_product_detail
# --------------------------------------------------------------------------

class TestGetProductDetail:
    def test_unknown_barcode_returns_none(self, fake_queries):
        fake_queries["product"] = None
        assert service.get_product_detail("nope") is None

    def test_combines_product_prices_promotions(self, fake_queries):
        fake_queries["prices"] = [_price_row()]
        fake_queries["promotions"] = [_promo_row()]

        detail = service.get_product_detail("111")

        assert detail.product.item_code == "111"
        assert len(detail.prices) == 1
        assert len(detail.promotions) == 1
        assert detail.enrichment is None

    @pytest.mark.parametrize("bad_price", [None, Decimal("0"), Decimal("-1.00")])
    def test_drops_missing_zero_and_negative_prices(self, fake_queries, bad_price):
        fake_queries["prices"] = [_price_row(price=bad_price), _price_row(store_id="S2", price=Decimal("7.00"))]

        detail = service.get_product_detail("111")

        assert [p.store_id for p in detail.prices] == ["S2"]

    @pytest.mark.parametrize("bad_price", [None, Decimal("0"), Decimal("-0.5")])
    def test_drops_promotions_without_a_positive_discounted_price(self, fake_queries, bad_price):
        fake_queries["promotions"] = [_promo_row(discounted_price=bad_price)]

        assert service.get_product_detail("111").promotions == []

    def test_resolves_shopper_brand_for_prices_and_promotions(self, fake_queries):
        fake_queries["prices"] = [_price_row()]
        fake_queries["promotions"] = [_promo_row()]

        detail = service.get_product_detail("111")

        assert detail.prices[0].shopper_brand == "brand:רשת"
        assert detail.promotions[0].shopper_brand == "brand:רשת"

    def test_does_not_mutate_the_rows_returned_by_queries(self, fake_queries):
        row = _price_row()
        fake_queries["prices"] = [row]

        service.get_product_detail("111")

        assert "shopper_brand" not in row

    def test_enrichment_is_validated_when_present(self, fake_queries):
        fake_queries["enrichment"] = {
            "item_code": "111",
            "source": "test",
            "name_he": "חלב",
            "nutrition": [
                {
                    "source": "test",
                    "raw_label": "שומן",
                    "basis": "100g",
                    "basis_raw": "100g",
                    "is_canonical": True,
                }
            ],
        }

        detail = service.get_product_detail("111")

        assert isinstance(detail.enrichment, ProductEnrichment)
        assert detail.enrichment.nutrition[0].raw_label == "שומן"


# --------------------------------------------------------------------------
# search_products
# --------------------------------------------------------------------------

class TestSearchProducts:
    def _item(self, **over):
        item = {"item_code": "111", "name_he": "חלב", "brand_he": "תנובה", "category_he": "חלב וביצים"}
        item.update(over)
        return item

    def test_builds_template_friendly_rows(self, fake_queries, monkeypatch):
        fake_queries["search"] = {"items": [self._item()], "total": 1, "limit": 20, "offset": 0}
        monkeypatch.setattr(
            service.queries,
            "get_prices_for_products",
            lambda item_codes: {
                "111": [
                    {
                        "price": Decimal("6.50"),
                        "chain_id": "C1",
                        "store_id": "S1",
                    },
                    {
                        "price": Decimal("5.90"),
                        "chain_id": "C1",
                        "store_id": "S2",
                    },
                    {
                        "price": Decimal("5.90"),
                        "chain_id": "C2",
                        "store_id": "S1",
                    },
                ]
            },
        )

        result = service.search_products("חלב")

        assert result["total"] == 1
        product = result["products"][0]
        assert product["identifier"] == "111"
        assert product["name"] == "חלב"
        assert product["brand"] == "תנובה"
        assert product["category"] == "חלב וביצים"
        assert product["min_price"] == Decimal("5.90")
        assert product["store_count"] == 3

    def test_name_falls_back_to_english_then_barcode(self, fake_queries, monkeypatch):
        fake_queries["search"] = {
            "items": [self._item(name_he=None, name_en="Milk"), self._item(item_code="222", name_he=None)],
            "total": 2,
            "limit": 20,
            "offset": 0,
        }
        monkeypatch.setattr(service.queries, "get_prices", lambda code: [])

        names = [p["name"] for p in service.search_products("x")["products"]]

        assert names == ["Milk", "222"]

    def test_no_prices_gives_none_min_price_and_zero_stores(self, fake_queries, monkeypatch):
        fake_queries["search"] = {"items": [self._item()], "total": 1, "limit": 20, "offset": 0}
        monkeypatch.setattr(
                service.queries,
                "get_prices_for_products",
                lambda item_codes: {"111": []},
            )

        product = service.search_products("x")["products"][0]

        assert product["min_price"] is None
        assert product["store_count"] == 0


    def test_min_price_ignores_zero_prices(self, fake_queries, monkeypatch):
        fake_queries["search"] = {
            "items": [self._item()],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }

        monkeypatch.setattr(
            service.queries,
            "get_prices_for_products",
            lambda item_codes: {
                "111": [
                    {
                        "price": Decimal("0.00"),
                        "chain_id": "C1",
                        "store_id": "S1",
                    },
                    {
                        "price": Decimal("5.90"),
                        "chain_id": "C1",
                        "store_id": "S2",
                    },
                ]
            },
        )

        result = service.search_products("x")

        assert result["products"][0]["min_price"] == Decimal("5.90")


# --------------------------------------------------------------------------
# store-product wrappers
# --------------------------------------------------------------------------


    def test_search_store_products_validates_rows(self, monkeypatch):
        monkeypatch.setattr(
            service.queries,
            "search_store_products",
            lambda q, limit, offset: {
                "items": [
                    {
                        "chain_id": "C1",
                        "store_id": "S1",
                        "item_code": "F1",
                        "product_name": "עגבניה",
                        "chain_name_he": "רשת",
                        "chain_name_en": "chain",
                        "brands": [],
                    }
                ],
                "total": 1,
                "limit": limit,
                "offset": offset,
            },
        )
        monkeypatch.setattr(service, "resolve_shopper_brand", lambda *a: "מותג")

        result = service.search_store_products("עגבניה")

        assert result.total == 1
        assert result.items[0].shopper_brand == "מותג"

    def test_category_wrappers_return_models(self, monkeypatch):
        monkeypatch.setattr(
            service.queries, "get_store_product_categories", lambda: [{"id": 1, "name": "ירקות", "sort_order": 1}]
        )
        monkeypatch.setattr(
            service.queries,
            "get_store_product_subcategories",
            lambda category_id: [{"id": 5, "category_id": 1, "category": "ירקות", "name": "עגבניה", "sort_order": 1}],
        )

        assert service.get_store_product_categories()[0].name == "ירקות"
        assert service.get_store_product_subcategories(1)[0].category == "ירקות"


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------

class TestIdentifiers:
    def test_fresh_identifier_roundtrip(self):
        identifier = service.make_fresh_identifier("7290000000001")

        assert identifier == "fresh:7290000000001"
        assert service.parse_product_identifier(identifier) == {"type": "fresh", "item_code": "7290000000001"}

    def test_store_product_identifier_roundtrip(self):
        identifier = service.make_store_product_identifier("C1", "S1", "F1")

        assert identifier == "sp:C1:S1:F1"
        assert service.parse_product_identifier(identifier) == {
            "type": "store_product",
            "chain_id": "C1",
            "store_id": "S1",
            "item_code": "F1",
        }

    @pytest.mark.parametrize("bad", ["", "   ", "a:b", "x:y"])
    def test_fresh_identifier_rejects_empty_blank_and_colon(self, bad):
        with pytest.raises(ValueError):
            service.make_fresh_identifier(bad)

    @pytest.mark.parametrize(
        "args",
        [("", "S", "I"), ("C", " ", "I"), ("C", "S", ""), ("C:1", "S", "I"), ("C", "S:1", "I"), ("C", "S", "I:1")],
    )
    def test_store_product_identifier_rejects_bad_parts(self, args):
        with pytest.raises(ValueError):
            service.make_store_product_identifier(*args)

    @pytest.mark.parametrize(
        "bad",
        ["", "  ", "fresh", "fresh:", "fresh: ", "fresh:a:b", "sp:C:S", "sp:C:S:I:X", "sp::S:I", "sp:C: :I", "other:1", "123"],
    )
    def test_parse_rejects_malformed_identifiers(self, bad):
        with pytest.raises(ValueError):
            service.parse_product_identifier(bad)


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------

class TestSchemas:
    def test_product_only_requires_item_code(self):
        assert Product(item_code="1").name_he is None
        with pytest.raises(ValidationError):
            Product()

    def test_price_defaults(self):
        price = Price(item_code="1", chain_id="C", store_id="S", chain_name_he="א", chain_name_en="a")
        assert price.brands == []
        assert price.price is None

    def test_promotion_requires_group_id_and_promotion_id(self):
        base = dict(item_code="1", chain_id="C", store_id="S", chain_name_he="א", chain_name_en="a")
        with pytest.raises(ValidationError):
            Promotion(**base, promotion_id="P")  # no group_id
        with pytest.raises(ValidationError):
            Promotion(**base, group_id="G")  # no promotion_id

    def test_mutable_defaults_are_not_shared(self):
        a = Price(item_code="1", chain_id="C", store_id="S", chain_name_he="א", chain_name_en="a")
        b = Price(item_code="2", chain_id="C", store_id="S", chain_name_he="א", chain_name_en="a")
        a.brands.append("x")
        assert b.brands == []


    def test_enrichment_schema_exposes_local_name(self):
        assert "local_name" in ProductEnrichment.model_fields