"""End-to-end tests: real SQL -> service -> route -> Jinja template.

Uses the `seed` dataset (see tests/api/conftest.py); everything is rolled back.
"""

import html
import re
from urllib.parse import parse_qs, urlparse

import pytest

from api import routes_web


def hrefs(text):
    return [html.unescape(h) for h in re.findall(r'href="([^"]*)"', text)]


class TestHomepageStats:
    def test_returns_three_ints_that_include_the_seed(self, seed):
        stats = routes_web.get_homepage_stats()

        assert set(stats) == {"total_stores", "total_brands", "total_fresh_products"}
        assert all(isinstance(value, int) for value in stats.values())
        assert stats["total_stores"] >= 4
        assert stats["total_brands"] >= 3  # 2 chain names + the 'מותג א' brand
        assert stats["total_fresh_products"] >= 3  # 3 distinct matched product names


class TestHomeEndToEnd:
    def test_landing_page(self, client, seed):
        response = client.get("/")

        assert response.status_code == 200
        assert "סניפים" in response.text

    def test_packaged_flow(self, client, seed):
        tab = client.get("/", params={"tab": "packaged"})
        assert seed.cat_packaged in tab.text

        listing = client.get("/", params={"tab": "packaged", "category": seed.cat_packaged})
        links = hrefs(listing.text)

        assert listing.status_code == 200
        assert f"/product/{seed.milk}" in links and f"/product/{seed.cheese}" in links
        # not packaged: no `products` row / also a store_products code
        assert f"/product/{seed.no_product}" not in links
        assert f"/product/{seed.store_code}" not in links

    def test_fresh_flow_category_to_subcategory_to_products(self, client, seed):
        tab = client.get("/", params={"tab": "fresh"})
        assert seed.cat_fresh in tab.text

        subs = client.get("/", params={"tab": "fresh", "category": seed.category_id})
        assert f"/?tab=fresh&category={seed.category_id}&subcategory={seed.sub_tomato}" in hrefs(subs.text)

        products = client.get(
            "/", params={"tab": "fresh", "category": seed.category_id, "subcategory": seed.sub_tomato}
        )
        assert products.status_code == 200
        assert seed.tomato_cherry in products.text and seed.tomato_organic in products.text
        assert "החל מ־₪3.50" in products.text
        assert "מבצע החל מ־₪2.90" in products.text
        assert "מחיר לא זמין" in products.text  # tomato_organic only has a NULL price

    def test_subcategory_of_a_different_category_shows_no_products(self, client, seed):
        response = client.get(
            "/", params={"tab": "fresh", "category": seed.category_id, "subcategory": 2_000_000_000}
        )

        assert response.status_code == 200
        assert "/fresh-product?" not in response.text


class TestSearchEndToEnd:
    def test_finds_the_seeded_product(self, client, seed):
        response = client.get("/search", params={"q": "חלבטסט"})

        assert response.status_code == 200
        assert f"/product/{seed.milk}" in hrefs(response.text)
        assert "חלבטסט תנובה" in response.text

    def test_search_by_barcode(self, client, seed):
        assert f"/product/{seed.milk}" in hrefs(client.get("/search", params={"q": seed.milk}).text)

    def test_no_match_message(self, client, seed):
        assert "לא אותרו מוצרים" in client.get("/search", params={"q": "zzzz-nothing"}).text


    def test_card_shows_the_cheapest_real_price(self, client, seed):
        assert "5.90 ₪" in client.get("/search", params={"q": "חלבטסט"}).text


class TestProductPageEndToEnd:
    def test_unknown_barcode_is_404(self, client, seed):
        assert client.get("/product/0000000000000").status_code == 404

    def test_full_page(self, client, seed):
        response = client.get(f"/product/{seed.milk}")
        text = response.text

        assert response.status_code == 200
        assert "חלבטסט תנובה" in text
        # only the two real prices (5.90, 6.50); 0.00 and NULL are dropped
        assert "2 סניפים זמינים" in text
        assert "5.90 ₪" in text and "6.50 ₪" in text
        assert "0.00 ₪" not in text
        # active promotions only (PA1, PA4, PB1); PA2 expired, PA3 future
        assert "מבצע PA1" in text and "מבצע PA4" in text and "מבצע PB1" in text
        assert "מבצע PA2" not in text and "מבצע PA3" not in text
        assert "4.90 ₪" in text
        # enrichment + nutrition
        assert "חלבון" in text and "שומן" in text

    def test_product_without_prices_still_renders(self, client, seed):
        response = client.get(f"/product/{seed.cheese}")

        assert response.status_code == 200
        assert "★ המחיר הזול ביותר ★" not in response.text

    def test_barcode_with_sql_metacharacters_is_just_a_404(self, client, seed):
        assert client.get("/product/1'%20OR%20'1'='1").status_code == 404


class TestFreshProductPageEndToEnd:
    URL = "/fresh-product"

    def test_full_page(self, client, seed):
        response = client.get(self.URL, params={"name": seed.tomato_cherry, "subcategory_id": seed.sub_tomato})
        text = response.text

        assert response.status_code == 200
        assert seed.cat_fresh in text
        assert "2 סניפים נמצאו" in text
        assert "3.50 ₪" in text and "★ המחיר הזול ביותר ★" in text
        assert "מבצע עגבניות" in text and "2.90 ₪" in text
        assert "מבצע שפג" not in text  # expired promotion

    def test_product_with_only_a_null_price(self, client, seed):
        response = client.get(self.URL, params={"name": seed.tomato_organic, "subcategory_id": seed.sub_tomato})

        assert response.status_code == 200
        assert "לא זמין" in response.text
        assert "★ המחיר הזול ביותר ★" not in response.text

    def test_wrong_subcategory_is_404(self, client, seed):
        response = client.get(self.URL, params={"name": seed.tomato_cherry, "subcategory_id": seed.sub_chicken})

        assert response.status_code == 404

    def test_link_from_the_listing_opens_the_detail_page(self, client, seed):
        listing = client.get(
            "/", params={"tab": "fresh", "category": seed.category_id, "subcategory": seed.sub_tomato}
        )
        link = next(l for l in hrefs(listing.text) if l.startswith("/fresh-product"))
        query = parse_qs(urlparse(link).query)

        response = client.get(self.URL, params={"name": query["name"][0], "subcategory_id": query["subcategory_id"][0]})

        assert response.status_code == 200