"""Integration tests for the unenriched-product queries in api/queries.py.

Uses the `seed` fixture (tests/api/conftest.py) for a chain/store that already
exist, and adds its own uniquely-named products inside the same test
transaction. Assertions rely on a unique name token, never on the rest of
the DB's content.
"""

from types import SimpleNamespace

import pytest

from api import queries
from db import get_connection

TOKEN = "ללאהעשרהטסט"  # unique token present in every product name we insert


def codes(rows):
    return [row["item_code"] for row in rows]


@pytest.fixture
def unenriched(seed, conn):
    """Four barcoded products with no enrichment row.

    alpha / beta  -> valid: have a price, not store products
    no_price      -> excluded: no price row anywhere
    store_code    -> excluded: the barcode also exists in store_products
    """
    ids = SimpleNamespace(
        alpha="8880000000001",
        beta="8880000000002",
        no_price="8880000000003",
        store_code="8880000000004",
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO products (item_code, name) VALUES
                (%s, %s), (%s, %s), (%s, %s), (%s, %s)
            """,
            (
                ids.alpha, f"{TOKEN} אלפא",
                ids.beta, f"{TOKEN} בטא",
                ids.no_price, f"{TOKEN} ללא מחיר",
                ids.store_code, f"{TOKEN} קוד חנות",
            ),
        )
        cur.execute(
            """
            INSERT INTO store_products (chain_id, store_id, item_code, name)
            VALUES (%s, 'S1', %s, %s)
            """,
            (seed.chain_a, ids.store_code, f"{TOKEN} קוד חנות"),
        )
        cur.execute(
            """
            INSERT INTO prices (chain_id, store_id, item_code, price) VALUES
                (%s, 'S1', %s, 4.50),
                (%s, 'S1', %s, 6.00),
                (%s, 'S1', %s, 7.00)
            """,
            (
                seed.chain_a, ids.alpha,
                seed.chain_a, ids.beta,
                seed.chain_a, ids.store_code,
            ),
        )

    return ids


# --------------------------------------------------------------------------
# search_unenriched_products
# --------------------------------------------------------------------------

class TestSearchUnenriched:
    def test_blank_query_short_circuits(self, unenriched):
        assert queries.search_unenriched_products("   ") == {
            "items": [], "total": 0, "limit": 20, "offset": 0,
        }

    def test_finds_only_valid_unenriched_products(self, unenriched):
        result = queries.search_unenriched_products(TOKEN)

        assert result["total"] == 2
        assert set(codes(result["items"])) == {unenriched.alpha, unenriched.beta}

    def test_excludes_product_without_prices(self, unenriched):
        result = queries.search_unenriched_products(TOKEN)

        assert unenriched.no_price not in codes(result["items"])

    def test_excludes_barcodes_that_are_store_products(self, unenriched):
        result = queries.search_unenriched_products(TOKEN)

        assert unenriched.store_code not in codes(result["items"])

    def test_excludes_enriched_products(self, unenriched, seed):
        assert queries.search_unenriched_products(seed.milk)["total"] == 0

    def test_finds_by_barcode(self, unenriched):
        result = queries.search_unenriched_products(unenriched.alpha)

        assert codes(result["items"]) == [unenriched.alpha]

    def test_query_is_stripped(self, unenriched):
        assert queries.search_unenriched_products(f"  {TOKEN}  ")["total"] == 2

    def test_ordered_by_name(self, unenriched):
        result = queries.search_unenriched_products(TOKEN)

        assert codes(result["items"]) == [unenriched.alpha, unenriched.beta]

    def test_row_shape_matches_enriched_rows(self, unenriched):
        item = queries.search_unenriched_products(unenriched.alpha)["items"][0]

        assert item["name_he"] == item["name"] == f"{TOKEN} אלפא"
        for key in ("name_en", "brand_he", "brand_en", "category_he", "subcategory_he"):
            assert key in item and item[key] is None

    def test_pagination(self, unenriched):
        page1 = queries.search_unenriched_products(TOKEN, limit=1, offset=0)
        page2 = queries.search_unenriched_products(TOKEN, limit=1, offset=1)

        assert page1["total"] == page2["total"] == 2
        assert codes(page1["items"]) + codes(page2["items"]) == [
            unenriched.alpha, unenriched.beta,
        ]

    def test_underscore_is_literal(self, unenriched):
        # Unescaped, "_" would match the "ט" in the token.
        assert queries.search_unenriched_products("ללאהעשרה_סט")["total"] == 0

    def test_percent_is_literal(self, unenriched):
        assert queries.search_unenriched_products("ללאהעשרה%טסט")["total"] == 0

    def test_no_match(self, unenriched):
        assert queries.search_unenriched_products("zzzz-no-such-product")["total"] == 0

    def test_sql_metacharacters_are_just_data(self, unenriched):
        assert queries.search_unenriched_products("x'; DROP TABLE products; --")["total"] == 0
        assert queries.search_unenriched_products(TOKEN)["total"] == 2

    @pytest.mark.parametrize("limit", [0, -1, 101])
    def test_limit_validated(self, unenriched, limit):
        with pytest.raises(ValueError):
            queries.search_unenriched_products(TOKEN, limit=limit)

    def test_offset_validated(self, unenriched):
        with pytest.raises(ValueError):
            queries.search_unenriched_products(TOKEN, offset=-1)


# --------------------------------------------------------------------------
# get_unenriched_products (browse)
# --------------------------------------------------------------------------

class TestGetUnenriched:
    def test_returns_paged_structure(self, unenriched):
        result = queries.get_unenriched_products(limit=5, offset=0)

        assert result["limit"] == 5 and result["offset"] == 0
        assert result["total"] >= 2
        assert 1 <= len(result["items"]) <= 5

    def test_never_includes_enriched_or_excluded_products(self, unenriched, seed):
        result = queries.get_unenriched_products(limit=100)
        returned = set(codes(result["items"]))

        assert seed.milk not in returned
        assert unenriched.no_price not in returned
        assert unenriched.store_code not in returned

    def test_pages_do_not_overlap(self, unenriched):
        page1 = queries.get_unenriched_products(limit=1, offset=0)
        page2 = queries.get_unenriched_products(limit=1, offset=1)

        assert page1["total"] == page2["total"]
        assert not set(codes(page1["items"])) & set(codes(page2["items"]))

    def test_offset_past_the_end_is_empty_but_keeps_total(self, unenriched):
        total = queries.get_unenriched_products(limit=1)["total"]
        result = queries.get_unenriched_products(limit=1, offset=total + 1000)

        assert result["items"] == [] and result["total"] == total

    @pytest.mark.parametrize("limit", [0, 101])
    def test_limit_validated(self, unenriched, limit):
        with pytest.raises(ValueError):
            queries.get_unenriched_products(limit=limit)

    def test_offset_validated(self, unenriched):
        with pytest.raises(ValueError):
            queries.get_unenriched_products(offset=-1)