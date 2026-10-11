"""Tests for shopper-facing API database queries."""

from db import get_connection
from api.queries import get_product, get_prices, get_promotions, get_enrichment


def test_get_product_returns_enriched_product() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_code
                FROM product_enrichment
                LIMIT 1
                """
            )
            row = cur.fetchone()

    assert row is not None, "Test database has no enriched products"

    product = get_product(row[0])

    assert product is not None
    assert product["item_code"] == row[0]


def test_get_product_returns_none_for_unknown_barcode() -> None:
    product = get_product("0000000000000")

    assert product is None



def test_get_prices_returns_list() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_code
                FROM prices
                LIMIT 1
                """
            )
            row = cur.fetchone()

    if row is None:
        import pytest
        pytest.skip("Test database has no prices")

    prices = get_prices(row[0])

    assert prices
    assert all(price["item_code"] == row[0] for price in prices)
    assert all("brands" in price for price in prices)


def test_get_prices_returns_empty_list_for_unknown_barcode() -> None:
    assert get_prices("0000000000000") == []




def test_get_promotions_returns_list() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pi.item_code
                FROM promotion_items AS pi
                JOIN promotions AS p
                    ON p.chain_id = pi.chain_id
                   AND p.promotion_id = pi.promotion_id
                   AND p.store_id = pi.store_id
                WHERE (p.start_datetime IS NULL OR p.start_datetime <= now())
                  AND (p.end_datetime IS NULL OR p.end_datetime >= now())
                LIMIT 1
                """
            )
            row = cur.fetchone()

    if row is None:
        import pytest
        pytest.skip("Test database has no currently valid promotions")

    promotions = get_promotions(row[0])

    assert promotions
    assert all(promo["item_code"] == row[0] for promo in promotions)
    assert all("brands" in promo for promo in promotions)


def test_get_promotions_returns_empty_list_for_unknown_barcode() -> None:
    assert get_promotions("0000000000000") == []




def test_get_enrichment_returns_product_and_nutrition() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_code
                FROM product_enrichment
                LIMIT 1
                """
            )
            row = cur.fetchone()

    assert row is not None, "Test database has no enriched products"

    enrichment = get_enrichment(row[0])

    assert enrichment is not None
    assert enrichment["item_code"] == row[0]
    assert isinstance(enrichment["nutrition"], list)


def test_get_enrichment_returns_none_for_unknown_barcode() -> None:
    assert get_enrichment("0000000000000") is None

from api.queries import search


def test_search_finds_product_by_barcode() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_code
                FROM product_enrichment
                LIMIT 1
                """
            )
            row = cur.fetchone()

    assert row is not None

    result = search(row[0], limit=10)

    assert result["total"] >= 1
    assert result["items"]
    assert result["items"][0]["item_code"] == row[0]


def test_search_returns_empty_for_no_match() -> None:
    result = search("no-match-xyz-987654")

    assert result["items"] == []
    assert result["total"] == 0


def test_search_paginates() -> None:
    first_page = search("", limit=2)
    assert first_page["items"] == []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name_he
                FROM product_enrichment
                WHERE name_he IS NOT NULL
                LIMIT 1
                """
            )
            row = cur.fetchone()

    assert row is not None

    first_page = search(row[0], limit=1, offset=0)
    second_page = search(row[0], limit=1, offset=1)

    assert first_page["limit"] == 1
    assert first_page["offset"] == 0
    assert second_page["offset"] == 1


