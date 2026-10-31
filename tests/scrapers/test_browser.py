
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scrapers import browser as scraper


@pytest.fixture
def retailer():
    return {
        "chain_id": "test-chain",
        "retailer_id": "test-retailer",
        "name_en_normalized": "test retailer",
        "name_en": "Test Retailer",
        "web_site": "https://example.com/",
        "data_url": "https://example.com/data.js",
    }


@pytest.fixture
def categories():
    return [
        {"id": "100", "name": "Category A"},
        {"id": "200", "name": "Category B"},
    ]


def test_retailer_name_prefers_normalized_name():
    assert scraper.retailer_name({
        "name_en_normalized": "test retailer",
        "name_en": "Test Retailer",
        "name": "Generic Retailer",
    }) == "test retailer"


def test_retailer_name_falls_back_to_name():
    assert scraper.retailer_name({"name": "Generic Retailer"}) == "Generic Retailer"


def test_retailer_name_returns_none_when_missing():
    assert scraper.retailer_name({}) is None


def test_extract_frontend_data():
    expected = {
        "tree": {
            "categories": [
                {"id": "100", "name": "Category A"},
            ]
        }
    }

    with patch.object(
        scraper,
        "extract_js_object",
        return_value=json.dumps(expected),
    ) as extract:
        result = scraper.extract_frontend_data(
            "mock JavaScript containing frontend data"
        )

    extract.assert_called_once_with(
        "mock JavaScript containing frontend data",
        "frontendData",
    )
    assert result == expected


def test_extract_frontend_data_invalid_json():
    with (
        patch.object(scraper, "extract_js_object", return_value="{invalid"),
        pytest.raises(ValueError, match="frontendData is not valid JSON"),
    ):
        scraper.extract_frontend_data("mock JavaScript")


def test_get_categories():
    source_categories = [
        {"id": "1", "name": "Category A"},
        {"id": "2", "name": "Category B"},
    ]

    with patch.object(
        scraper,
        "get_all_categories",
        return_value=source_categories,
    ) as flatten:
        result = scraper.get_categories({
            "tree": {"categories": source_categories}
        })

    flatten.assert_called_once_with(source_categories)
    assert result == source_categories


def test_get_categories_missing_tree():
    with pytest.raises(ValueError, match="tree.categories"):
        scraper.get_categories({})


def test_get_categories_invalid_type():
    with pytest.raises(ValueError, match="not a list"):
        scraper.get_categories({"tree": {"categories": {}}})


def test_save_and_load_categories(retailer, categories, tmp_path):
    with (
        patch.object(scraper, "RAW_DIR", tmp_path),
        patch.object(scraper, "ROOT", tmp_path),
    ):
        path = scraper.save_categories(retailer, categories)

        assert path.exists()

        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["categories_count"] == 2
        assert saved["categories"] == categories

        assert scraper.load_saved_categories(retailer) == categories


def test_load_saved_categories_missing_file(retailer, tmp_path):
    with (
        patch.object(scraper, "RAW_DIR", tmp_path),
        patch.object(scraper, "ROOT", tmp_path),
        pytest.raises(FileNotFoundError),
    ):
        scraper.load_saved_categories(retailer)


def test_load_retailers(tmp_path):
    coverage_file = tmp_path / "coverage.json"
    coverage_file.write_text(
        json.dumps({
            "test-chain": {
                "name_en_normalized": "test retailer",
                "available": False,
            }
        }),
        encoding="utf-8",
    )

    with patch.object(scraper, "COVERAGE_FILE", coverage_file):
        result = scraper.load_retailers()

    assert len(result) == 1
    assert result[0]["chain_id"] == "test-chain"


def test_load_retailers_rejects_non_dictionary(tmp_path):
    coverage_file = tmp_path / "coverage.json"
    coverage_file.write_text(json.dumps([]), encoding="utf-8")

    with (
        patch.object(scraper, "COVERAGE_FILE", coverage_file),
        pytest.raises(ValueError, match="Expected a dictionary"),
    ):
        scraper.load_retailers()


@pytest.mark.asyncio
async def test_scrape_category_saves_all_products(retailer, tmp_path):
    products = [
        {"code": "item-001", "name": "Product A"},
        {"code": "item-002", "name": "Product B"},
    ]

    api_response = MagicMock()
    api_response.status = 200
    api_response.url = (
        "https://example.com/categories/100/products?from=0&size=2"
    )
    api_response.headers = {"content-type": "application/json"}
    api_response.json = AsyncMock(return_value={
        "products": products,
        "total": 2,
    })

    page = AsyncMock()
    page.url = "https://example.com/categories/100/products"
    page.title = AsyncMock(return_value="Category A")
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.close = AsyncMock()

    def register_listener(event, callback):
        if event == "response":
            callback(api_response)

    page.on = MagicMock(side_effect=register_listener)

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)

    with (
        patch.object(scraper, "RAW_DIR", tmp_path),
        patch.object(scraper, "ROOT", tmp_path),
    ):
        result = await scraper.scrape_category(
            context, retailer, "100"
        )

    assert result is True

    output = tmp_path / "test retailer" / "100.json"
    assert output.exists()

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["total"] == 2
    assert saved["products"] == products
    assert saved["_metziah"]["chain_id"] == "test-chain"
    assert saved["_metziah"]["category_id"] == "100"
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scrape_category_fails_without_product_response(
    retailer, tmp_path
):
    page = AsyncMock()
    page.url = "https://example.com/challenge"
    page.title = AsyncMock(return_value="Access Challenge")
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.close = AsyncMock()
    page.on = MagicMock()

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)

    with (
        patch.object(scraper, "RAW_DIR", tmp_path),
        pytest.raises(scraper.NoProductResponse),
    ):
        await scraper.scrape_category(context, retailer, "100")

    assert not (tmp_path / "test retailer" / "100.json").exists()
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scrape_category_skips_empty_category(retailer, tmp_path):
    api_response = MagicMock()
    api_response.status = 200
    api_response.url = "https://example.com/categories/100/products"
    api_response.headers = {"content-type": "application/json"}
    api_response.json = AsyncMock(return_value={
        "products": [],
        "total": 0,
    })

    page = AsyncMock()
    page.url = "https://example.com/categories/100/products"
    page.title = AsyncMock(return_value="Empty Category")
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.close = AsyncMock()

    def register_listener(event, callback):
        if event == "response":
            callback(api_response)

    page.on = MagicMock(side_effect=register_listener)

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)

    with patch.object(scraper, "RAW_DIR", tmp_path):
        result = await scraper.scrape_category(
            context, retailer, "100"
        )

    assert result is False
    assert not (tmp_path / "test retailer" / "100.json").exists()
    page.close.assert_awaited_once()


def test_load_saved_categories_rejects_invalid_format(
    retailer, tmp_path
):
    output_dir = tmp_path / "test retailer"
    output_dir.mkdir()

    (output_dir / "categories.json").write_text(
        json.dumps({"categories": "invalid"}),
        encoding="utf-8",
    )

    with (
        patch.object(scraper, "RAW_DIR", tmp_path),
        pytest.raises(ValueError, match="Invalid categories format"),
    ):
        scraper.load_saved_categories(retailer)
