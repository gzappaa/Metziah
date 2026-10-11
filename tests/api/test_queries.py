"""Integration tests for api/queries.py against a real Postgres.

Data comes from the `seed` fixture (tests/api/conftest.py) and lives only in
the test transaction. Assertions never depend on the rest of the DB's content:
we look at our own uniquely-named categories / barcodes.
"""

import pytest

from api import queries

CAT = "קטגוריית-ארוזים-טסט"  # same value as conftest.CAT_PACKAGED


def codes(rows):
    return [row["item_code"] for row in rows]


# --------------------------------------------------------------------------
# get_product / get_enrichment
# --------------------------------------------------------------------------

class TestGetProduct:
    def test_returns_enriched_columns(self, seed):
        product = queries.get_product(seed.milk)

        assert product["item_code"] == seed.milk
        assert product["name_he"] == "חלבטסט תנובה"
        assert product["brand_he"] == "תנובה"
        assert product["category_he"] == seed.cat_packaged

    def test_unknown_barcode_is_none(self, seed):
        assert queries.get_product("0000000000000") is None

    def test_sql_metacharacters_are_just_data(self, seed):
        assert queries.get_product("x'; DROP TABLE products; --") is None
        assert queries.get_product(seed.milk) is not None


class TestGetEnrichment:
    def test_unknown_barcode_is_none(self, seed):
        assert queries.get_enrichment("0000000000000") is None

    def test_null_entries_are_stripped_from_category_paths(self, seed):
        enrichment = queries.get_enrichment(seed.milk)

        assert enrichment["category_path_he"] == ["חלב", "מוצרי חלב"]
        assert enrichment["category_path_en"] == ["Dairy"]

    def test_nutrition_is_ordered_by_basis_then_nutrient_nulls_last(self, seed):
        nutrition = queries.get_enrichment(seed.milk)["nutrition"]

        assert [(n["basis"], n["nutrient"]) for n in nutrition] == [
            ("100g", "protein"),
            ("100ml", "fat"),
            ("100ml", None),
        ]

    def test_product_without_nutrition_gets_an_empty_list(self, seed):
        assert queries.get_enrichment(seed.cheese)["nutrition"] == []

    def test_nutrition_raw_is_decoded_json(self, seed):
        assert queries.get_enrichment(seed.milk)["nutrition_raw"] == {"אנרגיה": "60"}


# --------------------------------------------------------------------------
# get_prices
# --------------------------------------------------------------------------

class TestGetPrices:
    def test_returns_one_row_per_store_with_chain_and_store_details(self, seed):
        rows = queries.get_prices(seed.milk)

        assert len(rows) == 4
        by_store = {(r["chain_id"], r["store_id"]): r for r in rows}
        first = by_store[(seed.chain_a, "S1")]
        assert first["chain_name_he"] == "רשת בדיקה א"
        assert first["brands"] == ["מותג א"]
        assert first["store_name"] == "סניף א1"
        assert first["city"] == "תל אביב"
        assert str(first["price"]) == "5.90"

    def test_sorted_by_price_ascending_with_nulls_last(self, seed):
        prices = [r["price"] for r in queries.get_prices(seed.milk)]

        assert prices[-1] is None
        assert prices[:-1] == sorted(prices[:-1])

    def test_unknown_barcode_gives_empty_list(self, seed):
        assert queries.get_prices("0000000000000") == []

    def test_product_with_no_prices(self, seed):
        assert queries.get_prices(seed.cheese) == []


# --------------------------------------------------------------------------
# get_promotions
# --------------------------------------------------------------------------

class TestGetPromotions:
    def test_only_currently_valid_promotions(self, seed):
        promotion_ids = {r["promotion_id"] for r in queries.get_promotions(seed.milk)}

        # PA2 expired, PA3 not started yet
        assert promotion_ids == {"PA1", "PA4", "PB1"}

    def test_open_ended_promotion_is_included(self, seed):
        row = next(r for r in queries.get_promotions(seed.milk) if r["promotion_id"] == "PA4")

        assert row["start_datetime"] is None and row["end_datetime"] is None

    def test_row_has_store_chain_and_group_details(self, seed):
        row = next(r for r in queries.get_promotions(seed.milk) if r["promotion_id"] == "PA1")

        assert row["group_id"] == "G1"
        assert row["chain_name_he"] == "רשת בדיקה א"
        assert row["store_name"] == "סניף א1"
        assert str(row["discounted_price"]) == "4.90"
        assert str(row["min_qty"]) == "2.000"

    def test_ordered_by_end_date_open_ended_last(self, seed):
        ids = [r["promotion_id"] for r in queries.get_promotions(seed.milk)]

        assert ids[-1] == "PA4"  # NULL end_datetime sorts last
        assert ids.index("PB1") < ids.index("PA1")  # ends in 1 day vs 5 days

    def test_unknown_barcode(self, seed):
        assert queries.get_promotions("0000000000000") == []


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

class TestSearch:
    def test_blank_query_short_circuits(self, seed):
        assert queries.search("   ") == {"items": [], "total": 0, "limit": 20, "offset": 0}

    def test_finds_by_hebrew_name(self, seed):
        result = queries.search("חלבטסט")

        assert result["total"] == 1
        assert codes(result["items"]) == [seed.milk]

    def test_finds_by_english_name_case_insensitively(self, seed):
        assert codes(queries.search("test MILK")["items"]) == [seed.milk]

    def test_finds_by_partial_barcode(self, seed):
        assert seed.milk in codes(queries.search("77700000001")["items"])

    def test_exact_barcode_is_ranked_first(self, seed):
        result = queries.search(seed.milk)

        assert codes(result["items"])[0] == seed.milk

    def test_query_is_stripped(self, seed):
        assert codes(queries.search("  חלבטסט  ")["items"]) == [seed.milk]

    def test_no_match(self, seed):
        assert queries.search("zzzz-no-such-product")["total"] == 0

    def test_pagination(self, seed):
        page1 = queries.search("7770000000", limit=2, offset=0)
        page2 = queries.search("7770000000", limit=2, offset=2)

        assert page1["total"] == page2["total"] == 4
        assert len(page1["items"]) == 2 and len(page2["items"]) == 2
        assert not set(codes(page1["items"])) & set(codes(page2["items"]))

    @pytest.mark.parametrize("limit", [0, -1, 101])
    def test_limit_must_be_between_1_and_100(self, seed, limit):
        with pytest.raises(ValueError):
            queries.search("חלב", limit=limit)

    def test_offset_must_not_be_negative(self, seed):
        with pytest.raises(ValueError):
            queries.search("חלב", offset=-1)


def test_like_wildcards_are_treated_literally(seed):
    assert queries.search("_")["total"] > 0
    assert queries.search("%")["total"] > 0


# --------------------------------------------------------------------------
# packaged categories
# --------------------------------------------------------------------------

class TestPackagedCategories:
    def _ours(self):
        return next(c for c in queries.get_packaged_product_categories() if c["name"] == CAT)

    def test_counts_only_packaged_products(self, seed):
        category = self._ours()

        # 4 enriched rows carry this category, but NO_PRODUCT has no products row and
        # STORE_CODE also exists in store_products -> only MILK and CHEESE count.
        assert category["count"] == 2

    def test_subcategories_are_distinct_and_exclude_nulls(self, seed):
        assert self._ours()["subcategories"] == ["חלב"]

    def test_products_by_category_excludes_non_packaged(self, seed):
        result = queries.get_packaged_products_by_category(seed.cat_packaged)

        assert result["total"] == 2
        assert set(codes(result["items"])) == {seed.milk, seed.cheese}

    def test_products_by_category_pagination_and_order(self, seed):
        page1 = queries.get_packaged_products_by_category(seed.cat_packaged, limit=1, offset=0)
        page2 = queries.get_packaged_products_by_category(seed.cat_packaged, limit=1, offset=1)

        assert page1["total"] == page2["total"] == 2
        assert codes(page1["items"]) + codes(page2["items"]) == [seed.cheese, seed.milk]  # by name_he

    def test_blank_category_short_circuits(self, seed):
        assert queries.get_packaged_products_by_category("   ")["items"] == []

    def test_unknown_category(self, seed):
        assert queries.get_packaged_products_by_category("אין-כזה")["total"] == 0

    @pytest.mark.parametrize("limit", [0, 101])
    def test_limit_validated(self, seed, limit):
        with pytest.raises(ValueError):
            queries.get_packaged_products_by_category("x", limit=limit)

    def test_offset_validated(self, seed):
        with pytest.raises(ValueError):
            queries.get_packaged_products_by_category("x", offset=-1)



# --------------------------------------------------------------------------
# fresh categories / subcategories
# --------------------------------------------------------------------------

class TestFreshCategories:
    def test_categories_are_listed_with_id_name_sort_order(self, seed):
        category = next(c for c in queries.get_store_product_categories() if c["name"] == seed.cat_fresh)

        assert category["id"] == seed.category_id
        assert category["sort_order"] == 9999

    def test_categories_sorted_by_sort_order(self, seed):
        orders = [c["sort_order"] for c in queries.get_store_product_categories()]

        assert orders == sorted(orders)

    def test_subcategories_filtered_by_category(self, seed):
        subs = queries.get_store_product_subcategories(seed.category_id)

        assert [s["name"] for s in subs] == ["עגבניהטסט", "חזהטסט עוףטסט"]
        assert {s["category"] for s in subs} == {seed.cat_fresh}

    def test_subcategories_without_filter_include_ours(self, seed):
        names = {s["name"] for s in queries.get_store_product_subcategories()}

        assert {"עגבניהטסט", "חזהטסט עוףטסט"} <= names

    def test_unknown_category_has_no_subcategories(self, seed):
        assert queries.get_store_product_subcategories(32000) == []


    def test_categories_and_subcategories_expose_a_product_count(self, seed):
        category = next(
            c for c in queries.get_store_product_categories()
            if c["name"] == seed.cat_fresh
        )
        subcategory = queries.get_store_product_subcategories(seed.category_id)[0]

        print("SUBCATEGORY:", subcategory)

        assert "count" in category and "count" in subcategory


# --------------------------------------------------------------------------
# fresh products by subcategory
# --------------------------------------------------------------------------

class TestFreshProductsBySubcategory:
    def _by_name(self, seed, subcategory_id):
        result = queries.get_store_products_by_subcategory(subcategory_id)
        return result, {item["product_name"]: item for item in result["items"]}

    def test_groups_by_product_name(self, seed):
        result, items = self._by_name(seed, seed.sub_tomato)

        assert result["total"] == 2
        assert set(items) == {seed.tomato_cherry, seed.tomato_organic}

    def test_store_count_counts_distinct_stores(self, seed):
        _, items = self._by_name(seed, seed.sub_tomato)

        assert items[seed.tomato_cherry]["store_count"] == 2
        assert items[seed.tomato_organic]["store_count"] == 1

    def test_lowest_price_ignores_zero_and_missing_prices(self, seed):
        _, items = self._by_name(seed, seed.sub_tomato)

        assert str(items[seed.tomato_cherry]["lowest_price"]) == "3.50"  # B/S1 is 0.00
        assert items[seed.tomato_organic]["lowest_price"] is None  # only a NULL price

    def test_cheapest_promotion_only_considers_active_promotions(self, seed):
        _, items = self._by_name(seed, seed.sub_tomato)

        assert str(items[seed.tomato_cherry]["cheapest_promotion"]) == "2.90"  # expired 1.00 ignored
        assert items[seed.tomato_organic]["cheapest_promotion"] is None

    def test_all_words_must_match_in_any_order(self, seed):
        _, items = self._by_name(seed, seed.sub_chicken)

        assert list(items) == ["עוףטסט טרי חזהטסט"]

    def test_pagination_total_is_independent_of_page_size(self, seed):
        result = queries.get_store_products_by_subcategory(seed.sub_tomato, limit=1, offset=1)

        assert result["total"] == 2
        assert len(result["items"]) == 1

    def test_unknown_subcategory(self, seed):
        result = queries.get_store_products_by_subcategory(2_000_000_000)

        assert result == {"items": [], "total": 0, "limit": 20, "offset": 0}

    @pytest.mark.parametrize("limit", [0, 101])
    def test_limit_validated(self, seed, limit):
        with pytest.raises(ValueError):
            queries.get_store_products_by_subcategory(1, limit=limit)

    def test_offset_validated(self, seed):
        with pytest.raises(ValueError):
            queries.get_store_products_by_subcategory(1, offset=-1)


# --------------------------------------------------------------------------
# fresh product detail
# --------------------------------------------------------------------------

class TestFreshProductDetail:
    def test_one_row_per_store_with_category_info(self, seed):
        rows = queries.get_fresh_product_detail(seed.tomato_cherry, seed.sub_tomato)

        assert {(r["chain_id"], r["store_id"]) for r in rows} == {(seed.chain_a, "S1"), (seed.chain_b, "S1")}
        assert {r["category"] for r in rows} == {seed.cat_fresh}
        assert {r["subcategory_id"] for r in rows} == {seed.sub_tomato}

    def test_promotions_are_a_json_list_with_only_active_ones(self, seed):
        rows = queries.get_fresh_product_detail(seed.tomato_cherry, seed.sub_tomato)
        row = next(r for r in rows if r["chain_id"] == seed.chain_a)

        assert [p["promotion_id"] for p in row["promotions"]] == ["PF1"]
        assert row["promotions"][0]["discounted_price"] == pytest.approx(2.90)

    def test_stores_without_promotions_get_an_empty_list_not_null(self, seed):
        rows = queries.get_fresh_product_detail(seed.tomato_cherry, seed.sub_tomato)
        row = next(r for r in rows if r["chain_id"] == seed.chain_b)

        assert row["promotions"] == []

    def test_store_with_no_price_row_is_kept_with_null_price(self, seed):
        rows = queries.get_fresh_product_detail(seed.tomato_organic, seed.sub_tomato)

        assert len(rows) == 1 and rows[0]["price"] is None

    def test_unknown_product_or_wrong_subcategory(self, seed):
        assert queries.get_fresh_product_detail("אין-כזה", seed.sub_tomato) == []
        assert queries.get_fresh_product_detail(seed.tomato_cherry, seed.sub_chicken) == []


    def test_stores_with_a_real_price_are_listed_before_zero_priced_ones(self, seed):
        rows = queries.get_fresh_product_detail(seed.tomato_cherry, seed.sub_tomato)

        assert rows[0]["price"] is not None and rows[0]["price"] > 0