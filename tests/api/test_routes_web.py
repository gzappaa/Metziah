"""Route + template tests for api/routes_web.py (no database).

Collaborators (queries / service / stats) are monkeypatched on
`api.routes_web`, so these tests exercise routing, validation, view-model
building and the Jinja templates only.
"""

import html
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from api import routes_web
from api.schemas import (
    Nutrition,
    Price,
    Product,
    ProductDetail,
    ProductEnrichment,
    Promotion,
)


def hrefs(text: str) -> list[str]:
    return [html.unescape(h) for h in re.findall(r'href="([^"]*)"', text)]


def cheapest_badges(text: str) -> int:
    """Number of small 'הזול ביותר' badges (whitespace-insensitive)."""
    return len(re.findall(r"stamp-badge[^>]*>\s*הזול ביותר\s*</span>", text))


# --------------------------------------------------------------------------
# misc app wiring
# --------------------------------------------------------------------------

class TestApp:
    def test_health(self, client):
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_static_files_are_served(self, client):
        response = client.get("/static/image-placeholder.svg")

        assert response.status_code == 200
        assert "svg" in response.headers["content-type"]

    def test_unknown_route_is_404(self, client):
        assert client.get("/definitely-not-here").status_code == 404


    def test_app_does_not_depend_on_the_working_directory(self, client, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        assert client.get("/search", params={"q": ""}).status_code == 200


    def test_every_internal_footer_link_resolves(self, client, monkeypatch):
        monkeypatch.setattr(routes_web, "get_homepage_stats", lambda: dict(total_stores=0, total_brands=0, total_fresh_products=0))
        page = client.get("/").text
        footer = page.split('<footer', 1)[1]

        for link in hrefs(footer):
            if link.startswith("/api/"):
                assert client.get(link).status_code < 400, link


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

class TestFindProductImage:
    @pytest.mark.parametrize("bad", ["", "../etc/passwd", "a/b", "a b", "ab-c", "א123", "123\n", "a.b", "..", "%00"])
    def test_rejects_non_alphanumeric_or_non_ascii_codes(self, bad):
        assert routes_web.find_product_image(bad) is None

    def test_missing_image(self, tmp_path, monkeypatch):
        monkeypatch.setattr(routes_web, "IMAGES_DIR", tmp_path)

        assert routes_web.find_product_image("7290000000001") is None

    def test_finds_image_in_a_known_source_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(routes_web, "IMAGES_DIR", tmp_path)
        (tmp_path / "freshmarket").mkdir()
        image = tmp_path / "freshmarket" / "123_001.jpg"
        image.write_bytes(b"jpg")

        assert routes_web.find_product_image("123") == image

    def test_source_priority_is_tiv_taam_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(routes_web, "IMAGES_DIR", tmp_path)
        for source in ("super yuda", "tiv taam"):
            (tmp_path / source).mkdir()
            (tmp_path / source / "123_001.jpg").write_bytes(b"jpg")

        assert routes_web.find_product_image("123").parent.name == "tiv taam"

    def test_ignores_unknown_source_folders(self, tmp_path, monkeypatch):
        monkeypatch.setattr(routes_web, "IMAGES_DIR", tmp_path)
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "123_001.jpg").write_bytes(b"jpg")

        assert routes_web.find_product_image("123") is None


class TestImageRoute:
    def test_serves_the_jpeg_when_it_exists(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(routes_web, "IMAGES_DIR", tmp_path)
        (tmp_path / "tiv taam").mkdir()
        (tmp_path / "tiv taam" / "123_001.jpg").write_bytes(b"\xff\xd8jpegdata")

        response = client.get("/img/123")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == b"\xff\xd8jpegdata"

    def test_falls_back_to_placeholder(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(routes_web, "IMAGES_DIR", tmp_path)

        response = client.get("/img/999")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/svg+xml"

    @pytest.mark.parametrize("path", ["/img/..%2f..%2fetc%2fpasswd", "/img/%2e%2e", "/img/a%00b"])
    def test_path_traversal_gets_placeholder_or_404_never_a_file(self, client, path):
        response = client.get(path)

        assert response.status_code in (200, 404)
        assert response.headers["content-type"] in ("image/svg+xml", "application/json")

    def test_is_hidden_from_openapi(self, client):
        assert "/img/{item_code}" not in client.get("/openapi.json").json()["paths"]


class TestBrandLogoRoute:
    @pytest.fixture(autouse=True)
    def brand_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(routes_web, "BRAND_IMAGES_DIR", tmp_path)
        (tmp_path / "שופרסל.jpg").write_bytes(b"logo")
        return tmp_path

    def test_serves_existing_logo(self, client):
        response = client.get("/brand-logo/שופרסל")

        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == b"logo"

    def test_name_is_stripped(self, client):
        assert client.get("/brand-logo/%20שופרסל%20").content == b"logo"

    def test_unknown_brand_gets_placeholder(self, client):
        assert client.get("/brand-logo/אין-כזה").headers["content-type"] == "image/svg+xml"

    def test_blank_brand_gets_placeholder(self, client):
        assert client.get("/brand-logo/%20").headers["content-type"] == "image/svg+xml"

    @pytest.mark.parametrize("name", ["..", "..%2f..%2fsecret", "%2e%2e%2fsecret", "a%2fb", "..%5c..%5csecret"])
    def test_cannot_escape_the_brand_directory(self, client, brand_dir, name):
        (brand_dir.parent / "secret.jpg").write_bytes(b"TOP SECRET")

        response = client.get(f"/brand-logo/{name}")

        assert b"TOP SECRET" not in response.content

    def test_directory_guard_itself_blocks_traversal(self, brand_dir):
        """Over HTTP Starlette already refuses '/' inside the path param, so the
        `candidate.parent == BRAND_IMAGES_DIR` guard is only reachable by calling
        the function directly - this keeps that defence-in-depth honest."""
        (brand_dir.parent / "secret.jpg").write_bytes(b"TOP SECRET")

        response = routes_web.brand_logo("../secret")

        assert response.media_type == "image/svg+xml"
        assert response.path != brand_dir.parent / "secret.jpg"


    def test_null_byte_in_name_does_not_crash(self, client):
        assert client.get("/brand-logo/a%00b").status_code == 200


# --------------------------------------------------------------------------
# home page
# --------------------------------------------------------------------------

@pytest.fixture
def home(monkeypatch):
    """Patch everything the index route touches and record calls."""
    calls = {"packaged_products": [], "subcategories": [], "fresh_products": []}
    monkeypatch.setattr(
        routes_web,
        "get_homepage_stats",
        lambda: {"total_stores": 1234, "total_brands": 7, "total_fresh_products": 99},
    )
    monkeypatch.setattr(
        routes_web,
        "get_packaged_product_categories",
        lambda: [
            {"name": "חלב וביצים", "count": 5, "subcategories": ["חלב", "ביצים"]},
            {"name": "בשר ועוף", "count": 2, "subcategories": []},
        ],
    )
    monkeypatch.setattr(
        routes_web,
        "get_store_product_categories",
        lambda: [
            {"id": 1, "name": "ירקות ופירות", "sort_order": 1},
            {"id": 2, "name": "קצבייה", "sort_order": 2},
        ],
    )

    def packaged_products(category, *a, **kw):
        calls["packaged_products"].append(category)
        return {
            "items": [
                {"item_code": "111", "name_he": "חלב תנובה", "name_en": None, "brand_he": "תנובה", "brand_en": None, "subcategory_he": "חלב"},
                {"item_code": "222", "name_he": None, "name_en": "Eggs", "brand_he": None, "brand_en": None, "subcategory_he": None},
            ],
            "total": 2,
            "limit": 40,
            "offset": 0,
        }

    def subcategories(category_id):
        calls["subcategories"].append(category_id)
        return [
            {"id": 10, "category_id": category_id, "category": "ירקות ופירות", "name": "עגבניה", "sort_order": 1},
            {"id": 11, "category_id": category_id, "category": "ירקות ופירות", "name": "מלפפון", "sort_order": 2},
        ]

    def fresh_products(subcategory_id, limit, offset):
        calls["fresh_products"].append((subcategory_id, limit, offset))
        return {
            "items": [
                {"product_name": "עגבניה שרי", "store_count": 3, "lowest_price": Decimal("3.5"), "cheapest_promotion": Decimal("2.9")},
                {"product_name": "עגבניה רגילה", "store_count": 1, "lowest_price": None, "cheapest_promotion": None},
            ],
            "total": 2,
        }

    monkeypatch.setattr(routes_web, "get_packaged_products_by_category", packaged_products)
    monkeypatch.setattr(routes_web, "get_store_product_subcategories", subcategories)
    monkeypatch.setattr(routes_web, "get_store_products_by_subcategory", fresh_products)
    return calls


class TestHome:
    def test_landing_page_shows_formatted_stats_and_both_tabs(self, client, home):
        response = client.get("/")

        assert response.status_code == 200
        assert "1,234" in response.text
        assert "99" in response.text
        assert "/?tab=packaged" in hrefs(response.text)
        assert "/?tab=fresh" in hrefs(response.text)

    def test_landing_page_has_no_category_tiles(self, client, home):
        assert "category-tile-title" not in client.get("/").text

    def test_unknown_tab_is_harmless(self, client, home):
        response = client.get("/", params={"tab": "<script>x</script>"})

        assert response.status_code == 200
        assert "<script>x</script>" not in response.text

    def test_packaged_tab_lists_categories_with_urlencoded_links(self, client, home):
        response = client.get("/", params={"tab": "packaged"})

        assert response.status_code == 200
        assert "חלב וביצים" in response.text
        assert "2 תת-קטגוריות" in response.text
        assert "/?tab=packaged&category=%D7%97%D7%9C%D7%91%20%D7%95%D7%91%D7%99%D7%A6%D7%99%D7%9D" in hrefs(response.text)
        assert home["packaged_products"] == []  # no category chosen yet

    def test_packaged_tab_with_category_lists_products(self, client, home):
        response = client.get("/", params={"tab": "packaged", "category": "חלב וביצים"})

        assert response.status_code == 200
        assert home["packaged_products"] == ["חלב וביצים"]
        assert "/product/111" in hrefs(response.text)
        assert "/product/222" in hrefs(response.text)
        assert "חלב תנובה" in response.text
        assert "Eggs" in response.text  # falls back to the English name
        assert "ברקוד: 111" in response.text
        assert "← כל הקטגוריות" in response.text

    def test_packaged_tab_does_not_touch_fresh_queries(self, client, home):
        client.get("/", params={"tab": "packaged", "category": "חלב וביצים"})

        assert home["subcategories"] == [] and home["fresh_products"] == []

    def test_category_without_tab_is_ignored(self, client, home):
        client.get("/", params={"category": "חלב וביצים"})

        assert home["packaged_products"] == []

    def test_fresh_tab_lists_categories_by_id(self, client, home):
        response = client.get("/", params={"tab": "fresh"})

        assert "ירקות ופירות" in response.text and "קצבייה" in response.text
        assert "/?tab=fresh&category=1" in hrefs(response.text)
        assert "🥬" in response.text and "🥩" in response.text

    def test_fresh_category_lists_subcategories(self, client, home):
        response = client.get("/", params={"tab": "fresh", "category": "1"})

        assert home["subcategories"] == [1]
        assert "/?tab=fresh&category=1&subcategory=10" in hrefs(response.text)
        assert "עגבניה" in response.text and "מלפפון" in response.text

    def test_fresh_subcategory_lists_products_with_prices_and_promotions(self, client, home):
        response = client.get("/", params={"tab": "fresh", "category": "1", "subcategory": "10"})

        assert home["fresh_products"] == [(10, 40, 0)]
        link = next(l for l in hrefs(response.text) if l.startswith("/fresh-product"))
        assert parse_qs(urlparse(link).query) == {"name": ["עגבניה שרי"], "subcategory_id": ["10"]}
        assert "החל מ־₪3.50" in response.text
        assert "מבצע החל מ־₪2.90" in response.text
        assert "מחיר לא זמין" in response.text  # second product has no price

    def test_subcategory_from_another_category_is_not_queried(self, client, home):
        response = client.get("/", params={"tab": "fresh", "category": "1", "subcategory": "999"})

        assert response.status_code == 200
        assert home["fresh_products"] == []

    @pytest.mark.parametrize(
        "params",
        [
            {"tab": "fresh", "category": "abc"},
            {"tab": "fresh", "category": "1", "subcategory": "x"},
            {"tab": "fresh", "category": "1.5"},
            {"tab": "fresh", "category": "' OR 1=1 --"},
        ],
    )
    def test_non_numeric_ids_do_not_crash_and_query_nothing(self, client, home, params):
        response = client.get("/", params=params)

        assert response.status_code == 200
        assert home["fresh_products"] == []
        assert home["subcategories"] == []

    def test_fresh_subcategory_without_category_is_ignored(self, client, home):
        response = client.get("/", params={"tab": "fresh", "subcategory": "10"})

        assert response.status_code == 200
        assert home["fresh_products"] == []

    def test_category_name_is_html_escaped(self, client, home, monkeypatch):
        monkeypatch.setattr(
            routes_web, "get_packaged_product_categories", lambda: [{"name": "<img src=x onerror=alert(1)>", "count": 1, "subcategories": []}]
        )

        assert "<img src=x" not in client.get("/", params={"tab": "packaged"}).text


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

class TestSearch:
    @pytest.fixture
    def searched(self, monkeypatch):
        seen = []

        def fake(query, limit, offset):
            seen.append((query, limit, offset))
            return {
                "products": [
                    {"identifier": "111", "brand": "תנובה", "category": "חלב", "name": "חלב 3%", "min_price": Decimal("5.9"), "store_count": 4},
                    {"identifier": "222", "brand": None, "category": "", "name": "ביצים", "min_price": None, "store_count": 0},
                ],
                "total": 2,
                "limit": 20,
                "offset": 0,
            }

        monkeypatch.setattr(routes_web, "search_products", fake)
        return seen

    @pytest.mark.parametrize("path", ["/search", "/partials/search-results"])
    def test_both_endpoints_return_result_cards(self, client, searched, path):
        response = client.get(path, params={"q": "חלב"})

        assert response.status_code == 200
        assert "/product/111" in hrefs(response.text)
        assert "5.90 ₪" in response.text
        assert "לפי סניף" in response.text  # second product has no price
        assert "נמצאו 2 פריטים" in response.text
        assert "<html" not in response.text  # it is a partial, not a full page

    def test_query_is_stripped_and_paged(self, client, searched):
        client.get("/search", params={"q": "  חלב  "})

        assert searched == [("חלב", 20, 0)]

    @pytest.mark.parametrize("q", ["", "   "])
    def test_blank_query_does_not_hit_the_search_service(self, client, searched, q):
        response = client.get("/search", params={"q": q})

        assert response.status_code == 200
        assert searched == []
        assert response.text.strip() == ""

    def test_missing_q_param_is_blank(self, client, searched):
        assert client.get("/search").status_code == 200
        assert searched == []

    def test_no_results_message_echoes_the_query_escaped(self, client, monkeypatch):
        monkeypatch.setattr(
            routes_web, "search_products", lambda q, limit, offset: {"products": [], "total": 0, "limit": limit, "offset": offset}
        )

        text = client.get("/search", params={"q": "<script>alert(1)</script>"}).text

        assert "לא אותרו מוצרים" in text
        assert "<script>alert(1)</script>" not in text
        assert "&lt;script&gt;" in text

    def test_query_longer_than_200_chars_is_rejected(self, client, searched):
        assert client.get("/search", params={"q": "א" * 201}).status_code == 422
        assert client.get("/search", params={"q": "א" * 200}).status_code == 200


# --------------------------------------------------------------------------
# packaged product page
# --------------------------------------------------------------------------

def make_price(store_id="S1", price="5.90", store_name="סניף", brand="מותג", unit_price=None, **over):
    return Price(
        item_code="111",
        chain_id="C1",
        store_id=store_id,
        chain_name_he="רשת",
        chain_name_en="chain",
        shopper_brand=brand,
        store_name=store_name,
        price=Decimal(price) if price is not None else None,
        unit_price=Decimal(unit_price) if unit_price else None,
        **over,
    )


def make_promo(promotion_id="P1", discounted="4.90", description="מבצע חלב", store_name="סניף", **over):
    return Promotion(
        item_code="111",
        chain_id="C1",
        promotion_id=promotion_id,
        store_id="S1",
        chain_name_he="רשת",
        chain_name_en="chain",
        shopper_brand="מותג",
        store_name=store_name,
        group_id="G1",
        description=description,
        discounted_price=Decimal(discounted) if discounted is not None else None,
        **over,
    )


@pytest.fixture
def detail(monkeypatch):
    """Control what get_product_detail returns."""
    holder = {"value": ProductDetail(product=Product(item_code="111", name_he="חלב תנובה"))}
    monkeypatch.setattr(routes_web, "get_product_detail", lambda barcode: holder["value"])
    return holder


class TestProductDetailPage:
    def test_unknown_product_is_404(self, client, monkeypatch):
        monkeypatch.setattr(routes_web, "get_product_detail", lambda barcode: None)

        assert client.get("/product/000").status_code == 404

    def test_header_uses_name_brand_and_breadcrumbs(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111", name_he="שם בסיס", brand_he="בסיס", category_he="קט בסיס"),
            enrichment=ProductEnrichment(
                item_code="111", source="t", name_he="שם מועשר", brand_he="תנובה", category_he="חלב וביצים", subcategory_he="חלב"
            ),
        )

        text = client.get("/product/111").text

        assert "<h1 class=\"product-detail-name\">שם מועשר</h1>" in text  # enrichment wins
        assert "תנובה" in text
        assert "חלב וביצים" in text and "חלב</span>" in text
        assert "קוד פריט / ברקוד: 111" in text

    def test_name_falls_back_to_english_then_barcode(self, client, detail):
        detail["value"] = ProductDetail(product=Product(item_code="111", name_en="Milk"))
        assert 'product-detail-name">Milk<' in client.get("/product/111").text

        detail["value"] = ProductDetail(product=Product(item_code="111"))
        assert 'product-detail-name">111<' in client.get("/product/111").text

    def test_prices_sorted_ascending_and_cheapest_highlighted(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111", name_he="חלב"),
            prices=[make_price("S2", "7.00", "יקר"), make_price("S1", "5.90", "זול"), make_price("S3", "6.00", "אמצע")],
        )

        text = client.get("/product/111").text

        assert text.index("זול") < text.index("אמצע") < text.index("יקר")
        assert cheapest_badges(text) == 1
        assert "★ המחיר הזול ביותר ★" in text and "5.90 ₪" in text
        assert "3 סניפים זמינים" in text

    def test_ties_for_cheapest_are_all_highlighted(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111"), prices=[make_price("S1", "5.00"), make_price("S2", "5.00")]
        )

        assert cheapest_badges(client.get("/product/111").text) == 2

    def test_zero_and_missing_prices_are_not_listed(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111"),
            prices=[make_price("S1", "0.00", "אפס"), make_price("S2", None, "ריק"), make_price("S3", "9.99", "אמיתי")],
        )

        text = client.get("/product/111").text

        assert "אמיתי" in text and "אפס" not in text and "ריק" not in text
        assert "1 סניפים זמינים" in text

    def test_no_prices_means_no_cheapest_stamp(self, client, detail):
        text = client.get("/product/111").text

        assert client.get("/product/111").status_code == 200
        assert "★ המחיר הזול ביותר ★" not in text
        assert "0 סניפים זמינים" in text

    def test_unit_price_is_shown_with_measure(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111"), prices=[make_price(unit_price="11.80", unit_measure="ק\"ג")]
        )

        assert '11.80 ₪ / ק&#34;ג' in client.get("/product/111").text

    def test_promotions_section(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111"),
            promotions=[
                make_promo("P1", "4.90", "מבצע א", min_qty=Decimal("2"), remarks="עד גמר המלאי"),
                make_promo("P2", "0", "מבצע אפס"),
                make_promo("P3", None, "מבצע ריק"),
            ],
        )

        text = client.get("/product/111").text

        assert "מבצעים פעילים בתוקף" in text
        assert "מבצע א" in text and "4.90 ₪" in text
        assert "מינימום 2 יח׳" in text
        assert "עד גמר המלאי" in text
        assert "מבצע אפס" not in text and "מבצע ריק" not in text  # route filters <= 0 / None

    def test_no_promotions_section_when_none(self, client, detail):
        assert "מבצעים פעילים" not in client.get("/product/111").text

    def test_enrichment_sections_and_nutrition(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111", name_he="חלב"),
            enrichment=ProductEnrichment(
                item_code="111",
                source="super yuda",
                source_file="f.json",
                name_he="חלב",
                description_he="חלב טרי",
                ingredients_he="חלב פרה",
                category_path_he=["חלב", "מוצרי חלב"],
                category_path_en=["Dairy", "Milk"],
                nutrition=[
                    Nutrition(
                        source="super yuda", raw_label="שומן", nutrient="fat", amount=Decimal("3"), unit="g",
                        bound="max", basis="100ml", basis_raw="ל-100 מ\"ל", flags=["unit_missing"], is_canonical=True,
                    )
                ],
            ),
        )

        text = client.get("/product/111").text

        assert "נתונים מועשרים וסימון תזונתי" in text
        assert "חלב טרי" in text and "חלב פרה" in text
        assert "Dairy › Milk" in text
        assert "מקור הנתונים: super yuda" in text and "f.json" in text
        assert "שומן" in text and "max3" in text and "unit_missing" in text
        assert "מידע על הנתונים" in text  # shown when a canonical row exists

    def test_enrichment_with_nothing_to_show(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111"), enrichment=ProductEnrichment(item_code="111", source="t")
        )

        text = client.get("/product/111").text

        assert "אין תיאור או רשימת רכיבים זמינים" in text
        assert "אין סימון תזונתי מובנה זמין" in text

    def test_without_enrichment_the_fallback_notice_is_shown(self, client, detail):
        assert "פרטי המוצר המורחבים אינם זמינים כרגע" in client.get("/product/111").text

    def test_user_controlled_text_is_escaped(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111", name_he="<script>alert(1)</script>"),
            enrichment=ProductEnrichment(item_code="111", source="t", description_he="<b onmouseover=x>"),
        )

        text = client.get("/product/111").text

        assert "<script>alert(1)</script>" not in text
        assert "<b onmouseover=x>" not in text


    def test_store_without_a_name_does_not_render_none(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111"),
            prices=[make_price(store_name=None)],
            promotions=[make_promo(store_name=None)],
        )

        assert "None" not in client.get("/product/111").text


    def test_raw_nutrition_json_keeps_hebrew_readable(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111"),
            enrichment=ProductEnrichment(item_code="111", source="t", nutrition_raw={"אנרגיה": "60"}),
        )

        assert "אנרגיה" in client.get("/product/111").text


    def test_manufacturer_is_displayed_when_known(self, client, detail):
        detail["value"] = ProductDetail(
            product=Product(item_code="111", name_he="חלב"),
            prices=[make_price(quantity=Decimal("1"), unit_qty="ליטר")],
        )

        assert "תכולה" in client.get("/product/111").text


# --------------------------------------------------------------------------
# fresh product page
# --------------------------------------------------------------------------

def make_store(**over):
    store = {
        "chain_id": "C1",
        "store_id": "S1",
        "item_code": "F1",
        "product_name": "עגבניה שרי",
        "category_id": 1,
        "category": "ירקות ופירות",
        "subcategory_id": 10,
        "subcategory": "עגבניה",
        "chain_name_he": "רשת",
        "chain_name_en": "chain",
        "store_name": "סניף",
        "city": "תל אביב",
        "price": Decimal("3.50"),
        "promotions": [],
    }
    store.update(over)
    return store


@pytest.fixture
def fresh(monkeypatch):
    calls = []
    holder = {"stores": [make_store()]}

    def fake(product_name, subcategory_id):
        calls.append((product_name, subcategory_id))
        return holder["stores"]

    monkeypatch.setattr(routes_web, "get_fresh_product_detail", fake)
    holder["calls"] = calls
    return holder


class TestFreshProductPage:
    URL = "/fresh-product"

    def test_renders_header_breadcrumbs_and_back_link(self, client, fresh):
        response = client.get(self.URL, params={"name": "עגבניה שרי", "subcategory_id": 10})

        assert response.status_code == 200
        text = response.text
        assert 'product-detail-name">עגבניה שרי<' in text
        assert "ירקות ופירות" in text and "עגבניה</span>" in text
        assert "/?tab=fresh&category=1&subcategory=10" in hrefs(text)
        assert fresh["calls"] == [("עגבניה שרי", 10)]

    def test_name_is_stripped(self, client, fresh):
        client.get(self.URL, params={"name": "  עגבניה שרי  ", "subcategory_id": 10})

        assert fresh["calls"] == [("עגבניה שרי", 10)]

    def test_no_stores_is_404(self, client, fresh):
        fresh["stores"] = []

        assert client.get(self.URL, params={"name": "x", "subcategory_id": 1}).status_code == 404

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"name": "x"},
            {"subcategory_id": 1},
            {"name": "", "subcategory_id": 1},
            {"name": "x", "subcategory_id": 0},
            {"name": "x", "subcategory_id": -3},
            {"name": "x", "subcategory_id": "abc"},
            {"name": "x" * 301, "subcategory_id": 1},
        ],
    )
    def test_invalid_query_params_are_422(self, client, fresh, params):
        assert client.get(self.URL, params=params).status_code == 422
        assert fresh["calls"] == []

    def test_whitespace_only_name_is_404_without_querying(self, client, fresh):
        assert client.get(self.URL, params={"name": "   ", "subcategory_id": 1}).status_code == 404
        assert fresh["calls"] == []

    def test_cheapest_store_is_highlighted_and_zero_prices_are_unavailable(self, client, fresh):
        fresh["stores"] = [
            make_store(store_id="S0", store_name="אפס", price=Decimal("0")),
            make_store(store_id="S1", store_name="זול", price=Decimal("3.50")),
            make_store(store_id="S2", store_name="יקר", price=Decimal("4.20")),
            make_store(store_id="S3", store_name="ללא", price=None),
        ]

        text = client.get(self.URL, params={"name": "x", "subcategory_id": 10}).text

        assert cheapest_badges(text) == 1
        assert "★ המחיר הזול ביותר ★" in text and "3.50 ₪" in text
        assert text.count("לא זמין") == 2  # the 0.00 row and the NULL row
        assert "4 סניפים נמצאו" in text

    def test_all_prices_unavailable_means_no_stamp(self, client, fresh):
        fresh["stores"] = [make_store(price=None)]

        text = client.get(self.URL, params={"name": "x", "subcategory_id": 10}).text

        assert "★ המחיר הזול ביותר ★" not in text

    def test_store_without_name_or_city_renders_cleanly(self, client, fresh):
        fresh["stores"] = [make_store(store_name=None, city=None)]

        text = client.get(self.URL, params={"name": "x", "subcategory_id": 10}).text

        assert "None" not in text

    def test_promotions_listed_with_details(self, client, fresh):
        fresh["stores"] = [
            make_store(
                promotions=[
                    {"description": "2 ב-5", "discounted_price": 2.5, "min_qty": 2, "end_datetime": None},
                    {"description": None, "discounted_price": 2.0, "min_qty": None, "end_datetime": None},
                ]
            )
        ]

        text = client.get(self.URL, params={"name": "x", "subcategory_id": 10}).text

        assert "מבצעים פעילים בתוקף" in text
        assert "2 ב-5" in text and "2.50 ₪" in text
        assert "מינימום 2 יח׳" in text
        assert "מבצע על המוצר" in text  # fallback when description is missing

    def test_no_promotions_notice(self, client, fresh):
        assert "לא נמצאו מבצעים פעילים" in client.get(self.URL, params={"name": "x", "subcategory_id": 10}).text


    def test_zero_priced_promotions_are_not_shown(self, client, fresh):
        fresh["stores"] = [make_store(promotions=[{"description": "שבור", "discounted_price": 0, "min_qty": None, "end_datetime": None}])]

        assert "שבור" not in client.get(self.URL, params={"name": "x", "subcategory_id": 10}).text


    def test_promotion_end_date_is_formatted_for_humans(self, client, fresh):
        fresh["stores"] = [
            make_store(promotions=[{"description": "מבצע", "discounted_price": 2.0, "min_qty": None, "end_datetime": "2026-10-20T23:59:00+00:00"}])
        ]

        text = client.get(self.URL, params={"name": "x", "subcategory_id": 10}).text

        assert "20/10/2026" in text