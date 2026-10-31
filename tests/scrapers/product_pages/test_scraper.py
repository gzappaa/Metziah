import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scrapers.product_pages import scraper


# ============================================================
# Test helpers
# ============================================================

def make_page_type(
    name="type_test",
    marker=".product",
    matches=None,
    prepare=None,
    parse=None,
):
    return scraper.PageType(
        name=name,
        marker=marker,
        matches=matches,
        prepare=prepare,
        parse=parse or (lambda html: {"name": "Example product"}),
    )


def make_site(page_type=None, name="example market", api=None):
    return scraper.Site(
        name=name,
        url_template="https://example.test/products/{item_code}",
        page_type=page_type or make_page_type(),
        api=api,
    )


# ============================================================
# URL and site configuration
# ============================================================

def test_read_site_entries_ignores_comments_and_blank_lines():
    contents = """
# Example site

https://example.test/products/1234567890123
  # another comment
https://shop.sample.test/item/9876543210987
"""

    with (
        patch.object(scraper, "URLS_FILE") as urls_file,
        patch.object(
            scraper,
            "site_name",
            side_effect=["example market", "sample shop"],
        ),
    ):
        urls_file.read_text.return_value = contents
        entries = scraper.read_site_entries()

    assert entries == [
        (
            "example market",
            "https://example.test/products/1234567890123",
            "https://example.test/products/{item_code}",
            "1234567890123",
        ),
        (
            "sample shop",
            "https://shop.sample.test/item/9876543210987",
            "https://shop.sample.test/item/{item_code}",
            "9876543210987",
        ),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/products/no-barcode",
        "https://example.test/products/12345678/87654321",
    ],
)
def test_read_site_entries_rejects_invalid_barcode_count(url):
    with (
        patch.object(scraper, "URLS_FILE") as urls_file,
        patch.object(scraper, "site_name") as mocked_site_name,
    ):
        urls_file.read_text.return_value = url

        with pytest.raises(ValueError, match="Expected exactly one barcode"):
            scraper.read_site_entries()

    mocked_site_name.assert_not_called()


def test_site_name_uses_closest_chain_name():
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("example market",),
        ("sample shop",),
    ]

    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor

    with patch("db.get_connection", return_value=connection):
        name = scraper.site_name(
            "https://www.example-market.test/item/12345678"
        )

    assert name == "example market"


def test_site_name_falls_back_to_hostname():
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [("unrelated shop",)]

    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor

    with (
        patch("db.get_connection", return_value=connection),
        patch.object(scraper, "get_close_matches", return_value=[]),
    ):
        name = scraper.site_name(
            "https://new-store.test/item/12345678"
        )

    assert name == "new store"


# ============================================================
# Page-type discovery
# ============================================================

def test_discover_types_loads_type_modules():
    module = SimpleNamespace(__path__=["unused"])
    module_info = SimpleNamespace(name="type_example")

    fake_type_module = SimpleNamespace(
        MARKER=".example",
        matches=None,
        parse=lambda html: {"name": "Example"},
        prepare=None,
    )

    with (
        patch.object(scraper.importlib, "import_module") as import_module,
        patch.object(
            scraper.pkgutil,
            "iter_modules",
            return_value=[module_info],
        ),
    ):
        import_module.side_effect = [
            module,
            fake_type_module,
        ]

        types = scraper.discover_types()

    assert len(types) == 1
    assert types[0].name == "type_example"
    assert types[0].marker == ".example"
    assert types[0].matches is None
    assert types[0].prepare is None
    assert types[0].parse("<html></html>") == {"name": "Example"}


def test_discover_types_accepts_api_type():
    module = SimpleNamespace(__path__=["unused"])
    module_info = SimpleNamespace(name="type_api")

    matches = lambda payload, code: True

    fake_type_module = SimpleNamespace(
        MARKER=None,
        matches=matches,
        parse=lambda payload, code, url: {},
        prepare=None,
    )

    with (
        patch.object(scraper.importlib, "import_module") as import_module,
        patch.object(
            scraper.pkgutil,
            "iter_modules",
            return_value=[module_info],
        ),
    ):
        import_module.side_effect = [
            module,
            fake_type_module,
        ]

        types = scraper.discover_types()

    assert len(types) == 1
    assert types[0].name == "type_api"
    assert types[0].marker is None
    assert types[0].matches is matches


def test_discover_types_rejects_module_without_marker_or_matches():
    module = SimpleNamespace(__path__=["unused"])
    module_info = SimpleNamespace(name="type_broken")
    broken_module = SimpleNamespace(parse=lambda html: {})

    with (
        patch.object(scraper.importlib, "import_module") as import_module,
        patch.object(
            scraper.pkgutil,
            "iter_modules",
            return_value=[module_info],
        ),
    ):
        import_module.side_effect = [
            module,
            broken_module,
        ]

        with pytest.raises(ValueError, match="must define parse"):
            scraper.discover_types()


def test_discover_types_rejects_empty_package():
    module = SimpleNamespace(__path__=["unused"])

    with (
        patch.object(
            scraper.importlib,
            "import_module",
            return_value=module,
        ),
        patch.object(scraper.pkgutil, "iter_modules", return_value=[]),
    ):
        with pytest.raises(ValueError, match="No page types found"):
            scraper.discover_types()


# ============================================================
# Browser helpers
# ============================================================

@pytest.mark.asyncio
async def test_new_context_sets_locale_viewport_and_route():
    browser = MagicMock()
    context = MagicMock()
    context.route = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)

    result = await scraper.new_context(browser)

    browser.new_context.assert_awaited_once_with(
        viewport={"width": 1440, "height": 1000},
        locale="he-IL",
    )
    context.route.assert_awaited_once_with(
        "**/*",
        scraper.block_heavy,
    )
    assert result is context


@pytest.mark.asyncio
async def test_block_heavy_aborts_images():
    route = MagicMock()
    route.request.resource_type = "image"
    route.abort = AsyncMock()
    route.continue_ = AsyncMock()

    await scraper.block_heavy(route)

    route.abort.assert_awaited_once()
    route.continue_.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("resource_type", ["media", "font"])
async def test_block_heavy_aborts_media_and_fonts(resource_type):
    route = MagicMock()
    route.request.resource_type = resource_type
    route.abort = AsyncMock()
    route.continue_ = AsyncMock()

    await scraper.block_heavy(route)

    route.abort.assert_awaited_once()
    route.continue_.assert_not_awaited()


@pytest.mark.asyncio
async def test_block_heavy_allows_document_requests():
    route = MagicMock()
    route.request.resource_type = "document"
    route.abort = AsyncMock()
    route.continue_ = AsyncMock()

    await scraper.block_heavy(route)

    route.continue_.assert_awaited_once()
    route.abort.assert_not_awaited()


# ============================================================
# Driver detection
# ============================================================

@pytest.mark.parametrize(
    "message",
    [
        "Connection closed while reading from the driver",
        "Pipe closed by peer",
    ],
)
def test_is_driver_dead_detects_driver_errors(message):
    assert scraper.is_driver_dead(RuntimeError(message)) is True


def test_is_driver_dead_ignores_unrelated_errors():
    assert scraper.is_driver_dead(RuntimeError("network timeout")) is False


# ============================================================
# Type detection
# ============================================================

@pytest.mark.asyncio
async def test_detect_type_returns_matching_page_type():
    page = MagicMock()
    page.goto = AsyncMock()
    page.close = AsyncMock()

    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    page.locator.return_value = locator

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)

    expected = make_page_type(marker=".example")
    other = make_page_type(name="type_other", marker=".other")

    result = await scraper.detect_type(
        context,
        "example market",
        "https://example.test/products/12345678",
        "12345678",
        [expected, other],
    )

    assert result == (expected, None)
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_detect_type_raises_when_no_type_matches():
    page = MagicMock()
    page.goto = AsyncMock()
    page.close = AsyncMock()

    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    page.locator.return_value = locator

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)

    with (
        patch.object(scraper, "PRODUCT_WAIT_MS", 0),
        pytest.raises(ValueError, match="no known page type matched"),
    ):
        await scraper.detect_type(
            context,
            "example market",
            "https://example.test/products/12345678",
            "12345678",
            [make_page_type()],
        )

    page.close.assert_awaited_once()


# ============================================================
# API request capture
# ============================================================

def test_build_api_request_replaces_item_code():
    request = SimpleNamespace(
        method="POST",
        url="https://example.test/api/products/12345678",
        post_data='{"code": "12345678"}',
        headers={
            "content-type": "application/json",
            "cookie": "session=abc",
            "host": "example.test",
            "x-item": "12345678",
        },
    )

    result = scraper.build_api_request(request, "12345678")

    assert result == scraper.ApiRequest(
        method="POST",
        url="https://example.test/api/products/{item_code}",
        body='{"code": "{item_code}"}',
        headers={
            "content-type": "application/json",
            "x-item": "{item_code}",
        },
    )


def test_api_request_render_replaces_item_code():
    api = scraper.ApiRequest(
        method="GET",
        url="https://example.test/api/{item_code}",
        body=None,
        headers={"x-item": "{item_code}"},
    )

    result = api.render("12345678")

    assert result == {
        "url": "https://example.test/api/12345678",
        "method": "GET",
        "data": None,
        "headers": {"x-item": "12345678"},
    }


def test_request_body_returns_post_data():
    request = SimpleNamespace(post_data='{"code": "123"}')

    assert scraper.request_body(request) == '{"code": "123"}'


def test_request_body_handles_binary_data():
    request = MagicMock()
    type(request).post_data = property(
        lambda self: (_ for _ in ()).throw(UnicodeDecodeError(
            "utf-8", b"\xff", 0, 1, "invalid start byte"
        ))
    )

    assert scraper.request_body(request) is None


@pytest.mark.asyncio
async def test_match_api_returns_matching_request():
    request = SimpleNamespace(
        resource_type="fetch",
        method="GET",
        url="https://example.test/api/12345678",
        post_data=None,
        headers={"accept": "application/json"},
    )

    response = MagicMock()
    response.request = request
    response.json = AsyncMock(
        return_value={"product": {"code": "12345678"}}
    )

    page_type = make_page_type(
        name="type_api",
        marker=None,
        matches=lambda payload, code: (
            payload["product"]["code"] == code
        ),
    )

    result = await scraper.match_api(
        response,
        "12345678",
        [page_type],
    )

    assert result is not None
    detected_type, api = result

    assert detected_type is page_type
    assert api.url == "https://example.test/api/{item_code}"


@pytest.mark.asyncio
async def test_match_api_ignores_non_api_requests():
    request = SimpleNamespace(
        resource_type="document",
        url="https://example.test/products/12345678",
        post_data=None,
    )

    response = MagicMock()
    response.request = request

    result = await scraper.match_api(
        response,
        "12345678",
        [],
    )

    assert result is None


@pytest.mark.asyncio
async def test_match_api_ignores_requests_without_item_code():
    request = SimpleNamespace(
        resource_type="fetch",
        url="https://example.test/api/products",
        post_data=None,
    )

    response = MagicMock()
    response.request = request

    result = await scraper.match_api(
        response,
        "12345678",
        [],
    )

    assert result is None


@pytest.mark.asyncio
async def test_match_api_ignores_invalid_json():
    request = SimpleNamespace(
        resource_type="fetch",
        url="https://example.test/api/12345678",
        post_data=None,
    )

    response = MagicMock()
    response.request = request
    response.json = AsyncMock(side_effect=ValueError("invalid JSON"))

    result = await scraper.match_api(
        response,
        "12345678",
        [],
    )

    assert result is None


# ============================================================
# Fetching HTML
# ============================================================

@pytest.mark.asyncio
async def test_fetch_html_returns_none_for_404():
    page = MagicMock()
    page.goto = AsyncMock(return_value=SimpleNamespace(status=404))

    result = await scraper.fetch_html(
        page,
        make_site(),
        "https://example.test/404",
    )

    assert result is None


@pytest.mark.asyncio
async def test_fetch_html_returns_none_when_marker_times_out():
    page = MagicMock()
    page.goto = AsyncMock(return_value=SimpleNamespace(status=200))
    page.wait_for_selector = AsyncMock(
        side_effect=PlaywrightTimeoutError("timed out")
    )

    result = await scraper.fetch_html(
        page,
        make_site(),
        "https://example.test/item",
    )

    assert result is None


@pytest.mark.asyncio
async def test_fetch_html_runs_prepare_before_returning_html():
    page = MagicMock()
    page.goto = AsyncMock(return_value=SimpleNamespace(status=200))
    page.wait_for_selector = AsyncMock()
    page.content = AsyncMock(
        return_value="<div class='product'>Example</div>"
    )

    prepare = AsyncMock()
    site = make_site(make_page_type(prepare=prepare))

    result = await scraper.fetch_html(
        page,
        site,
        "https://example.test/item",
    )

    assert result == "<div class='product'>Example</div>"
    prepare.assert_awaited_once_with(page)


# ============================================================
# Image URL
# ============================================================

@pytest.mark.parametrize(
    ("page_url", "expected"),
    [
        (
            "https://www.example.com/product/123",
            "https://img.example.com/",
        ),
        (
            "https://example.com/product/123",
            "https://example.com/",
        ),
        (
            "https://www.example.com:8443/product/123",
            "https://img.example.com:8443/",
        ),
    ],
)
def test_image_base_url(page_url, expected):
    assert scraper.image_base_url(page_url) == expected


# ============================================================
# Scraping and parsing
# ============================================================

@pytest.mark.asyncio
async def test_scrape_item_returns_none_when_product_is_missing():
    context = MagicMock()
    page = MagicMock()
    page.close = AsyncMock()
    context.new_page = AsyncMock(return_value=page)

    site = make_site()

    with patch.object(
        scraper,
        "fetch_html",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await scraper.scrape_item(
            context,
            site,
            "12345678",
        )

    assert result is None
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scrape_item_returns_parsed_result():
    context = MagicMock()
    page = MagicMock()
    page.close = AsyncMock()
    context.new_page = AsyncMock(return_value=page)

    page_type = make_page_type(
        parse=lambda html: {
            "page_code": "12345678",
            "name": "Example product",
            "images": [],
            "sections": [],
        }
    )
    site = make_site(page_type)

    with patch.object(
        scraper,
        "fetch_html",
        new_callable=AsyncMock,
        return_value="<html></html>",
    ):
        result = await scraper.scrape_item(
            context,
            site,
            "12345678",
        )

    assert result["item_code"] == "12345678"
    assert result["source"] == "example market"
    assert result["url"] == "https://example.test/products/12345678"
    assert result["page_code"] == "12345678"
    assert result["name"] == "Example product"
    assert "scraped_at" in result


@pytest.mark.asyncio
async def test_scrape_item_uses_api_without_browser():
    page_type = make_page_type(
        name="type_api",
        marker=None,
        matches=lambda payload, code: True,
        parse=lambda payload, code, base_url: {
            "page_code": code,
            "name": "Milk",
            "images": [],
        },
    )

    api = scraper.ApiRequest(
        method="GET",
        url="https://example.test/api/{item_code}",
        body=None,
        headers={},
    )

    site = make_site(page_type, api=api)

    payload = {"product": {"code": "12345678"}}

    with patch.object(
        scraper,
        "fetch_api",
        new_callable=AsyncMock,
        return_value=payload,
    ) as fetch_api:
        result = await scraper.scrape_item(
            None,
            site,
            "12345678",
        )

    fetch_api.assert_awaited_once_with(site, "12345678")
    assert result["name"] == "Milk"
    assert result["page_code"] == "12345678"


@pytest.mark.asyncio
async def test_scrape_item_returns_none_when_parser_returns_none():
    context = MagicMock()
    page = MagicMock()
    page.close = AsyncMock()
    context.new_page = AsyncMock(return_value=page)

    site = make_site(
        make_page_type(parse=lambda html: None)
    )

    with patch.object(
        scraper,
        "fetch_html",
        new_callable=AsyncMock,
        return_value="<html></html>",
    ):
        result = await scraper.scrape_item(
            context,
            site,
            "12345678",
        )

    assert result is None


@pytest.mark.asyncio
async def test_scrape_item_closes_page_if_fetch_fails():
    context = MagicMock()
    page = MagicMock()
    page.close = AsyncMock()
    context.new_page = AsyncMock(return_value=page)

    site = make_site()

    with patch.object(
        scraper,
        "fetch_html",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network error"),
    ):
        with pytest.raises(RuntimeError, match="network error"):
            await scraper.scrape_item(
                context,
                site,
                "12345678",
            )

    page.close.assert_awaited_once()


# ============================================================
# Saving results
# ============================================================

def test_save_result_writes_valid_json(tmp_path):
    result = {
        "item_code": "12345678",
        "name": "Example product",
        "description": "Hebrew text: חלב",
    }

    scraper.save_result(tmp_path, "12345678", result)

    path = tmp_path / "12345678.json"

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert not (tmp_path / "12345678.json.tmp").exists()


def test_save_result_creates_output_directory(tmp_path):
    out_dir = tmp_path / "nested" / "products"

    scraper.save_result(
        out_dir,
        "12345678",
        {"name": "Example"},
    )

    assert (out_dir / "12345678.json").exists()


def test_save_result_replaces_existing_file(tmp_path):
    path = tmp_path / "12345678.json"
    path.write_text('{"old": true}', encoding="utf-8")

    scraper.save_result(
        tmp_path,
        "12345678",
        {"new": True},
    )

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}


# ============================================================
# Database item-code loading
# ============================================================

def test_load_item_codes_uses_site_name():
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("12345678",),
        ("87654321",),
    ]

    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor

    with patch("db.get_connection", return_value=connection):
        codes = scraper.load_item_codes("example market")

    cursor.execute.assert_called_once_with(
        scraper.SQL_ITEM_CODES,
        ("example market",),
    )
    assert codes == ["12345678", "87654321"]


# ============================================================
# Worker
# ============================================================

@pytest.mark.asyncio
async def test_worker_saves_successful_result(tmp_path):
    queue = asyncio.Queue()
    queue.put_nowait("12345678")

    stats = {"saved": 0, "missing": 0, "failed": 0}
    site = make_site()

    with (
        patch.object(
            scraper,
            "scrape_item",
            new_callable=AsyncMock,
            return_value={
                "item_code": "12345678",
                "name": "Example",
            },
        ),
        patch.object(scraper, "save_result") as save_result,
    ):
        await scraper.worker(
            1,
            MagicMock(),
            site,
            queue,
            stats,
            tmp_path,
            1,
        )

    save_result.assert_called_once_with(
        tmp_path,
        "12345678",
        {
            "item_code": "12345678",
            "name": "Example",
        },
    )
    assert stats == {"saved": 1, "missing": 0, "failed": 0}


@pytest.mark.asyncio
async def test_worker_records_missing_item(tmp_path):
    queue = asyncio.Queue()
    queue.put_nowait("12345678")

    stats = {"saved": 0, "missing": 0, "failed": 0}

    with patch.object(
        scraper,
        "scrape_item",
        new_callable=AsyncMock,
        return_value=None,
    ):
        await scraper.worker(
            1,
            MagicMock(),
            make_site(),
            queue,
            stats,
            tmp_path,
            1,
        )

    assert stats == {"saved": 0, "missing": 1, "failed": 0}
    assert (
        tmp_path / "_missing.txt"
    ).read_text(encoding="utf-8") == "12345678\n"


@pytest.mark.asyncio
async def test_worker_records_failure_without_saving(tmp_path):
    queue = asyncio.Queue()
    queue.put_nowait("12345678")

    stats = {"saved": 0, "missing": 0, "failed": 0}

    with (
        patch.object(
            scraper,
            "scrape_item",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ),
        patch.object(scraper, "save_result") as save_result,
    ):
        await scraper.worker(
            1,
            MagicMock(),
            make_site(),
            queue,
            stats,
            tmp_path,
            1,
        )

    assert stats == {"saved": 0, "missing": 0, "failed": 1}
    save_result.assert_not_called()
    assert not (tmp_path / "_missing.txt").exists()


@pytest.mark.asyncio
async def test_worker_reraises_driver_disconnection(tmp_path):
    queue = asyncio.Queue()
    queue.put_nowait("12345678")

    stats = {"saved": 0, "missing": 0, "failed": 0}

    with patch.object(
        scraper,
        "scrape_item",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Pipe closed by peer"),
    ):
        with pytest.raises(RuntimeError, match="Pipe closed by peer"):
            await scraper.worker(
                1,
                MagicMock(),
                make_site(),
                queue,
                stats,
                tmp_path,
                1,
            )

    assert stats == {"saved": 0, "missing": 0, "failed": 0}