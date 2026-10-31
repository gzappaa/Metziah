import json

import pytest

from monitoring import scraper_coverage


def make_frontend_data():
    return {
        "rid": 1234,
        "retailer": {
            "branches": [
                {"id": 1},
            ],
        },
        "tree": {
            "categories": [
                {"id": 10},
            ],
        },
    }


def make_data_js(frontend_data):
    return (
        "window.sp = {\n"
        f"    frontendData: {json.dumps(frontend_data)}\n"
        "};"
    )


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, **kwargs):
        return self.responses[url]


def test_extract_js_object():
    text = """
    window.sp = {
        frontendData: {"rid": 1234, "name": "test"},
        other: true
    };
    """

    result = scraper_coverage.extract_js_object(
        text,
        "frontendData",
    )

    assert json.loads(result) == {
        "rid": 1234,
        "name": "test",
    }


def test_extract_js_object_missing_key():
    text = "window.sp = {other: true};"

    with pytest.raises(
        ValueError,
        match="Could not find frontendData",
    ):
        scraper_coverage.extract_js_object(
            text,
            "frontendData",
        )


def test_extract_js_object_nested_object():
    text = """
    window.sp = {
        frontendData: {
            "rid": 1234,
            "retailer": {
                "name": "Test",
                "branches": [
                    {"id": 1}
                ]
            }
        },
        other: true
    };
    """

    result = scraper_coverage.extract_js_object(
        text,
        "frontendData",
    )

    assert json.loads(result) == {
        "rid": 1234,
        "retailer": {
            "name": "Test",
            "branches": [
                {"id": 1},
            ],
        },
    }


def test_extract_js_object_with_escaped_quotes():
    text = r'''
    window.sp = {
        frontendData: {
            "rid": 1234,
            "name": "Test \"Store\""
        }
    };
    '''

    result = scraper_coverage.extract_js_object(
        text,
        "frontendData",
    )

    assert json.loads(result) == {
        "rid": 1234,
        "name": 'Test "Store"',
    }


def test_extract_js_object_missing_object():
    text = "window.sp = {frontendData: true};"

    with pytest.raises(
        ValueError,
        match="Could not find object for frontendData",
    ):
        scraper_coverage.extract_js_object(
            text,
            "frontendData",
        )


def test_extract_js_object_unclosed_object():
    text = """
    window.sp = {
        frontendData: {"rid": 1234
    """

    with pytest.raises(
        ValueError,
        match="Could not extract frontendData",
    ):
        scraper_coverage.extract_js_object(
            text,
            "frontendData",
        )


def test_get_all_categories():
    categories = [
        {
            "id": 1,
            "subCategories": [
                {
                    "id": 2,
                    "subCategories": [
                        {"id": 3},
                    ],
                },
            ],
        },
        {
            "id": 4,
        },
    ]

    result = scraper_coverage.get_all_categories(
        categories,
    )

    assert result == [
        {
            "id": 1,
            "subCategories": [
                {
                    "id": 2,
                    "subCategories": [
                        {"id": 3},
                    ],
                },
            ],
        },
        {
            "id": 2,
            "subCategories": [
                {"id": 3},
            ],
        },
        {"id": 3},
        {"id": 4},
    ]


def test_get_all_categories_empty():
    assert scraper_coverage.get_all_categories([]) == []


def test_get_data_url_from_html():
    html = """
    <html>
        <script src="https://example.com/assets/data.js?c=123"></script>
    </html>
    """

    assert (
        scraper_coverage.get_data_url_from_html(html)
        == "https://example.com/assets/data.js?c=123"
    )


def test_get_data_url_from_html_single_quotes():
    html = """
    <html>
        <script src='https://example.com/assets/data.js'></script>
    </html>
    """

    assert (
        scraper_coverage.get_data_url_from_html(html)
        == "https://example.com/assets/data.js"
    )


def test_get_data_url_from_html_case_insensitive():
    html = """
    <html>
        <script SRC="https://example.com/assets/DATA.JS"></script>
    </html>
    """

    assert (
        scraper_coverage.get_data_url_from_html(html)
        == "https://example.com/assets/DATA.JS"
    )


def test_get_data_url_from_html_missing():
    assert (
        scraper_coverage.get_data_url_from_html(
            "<html></html>"
        )
        is None
    )


def test_discover_website_success():
    frontend_data = make_frontend_data()
    data_js = make_data_js(frontend_data)

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                (
                    '<script src="'
                    "https://example.com/data.js"
                    '"></script>'
                ),
            ),
            "https://example.com/data.js": FakeResponse(
                200,
                data_js,
            ),
        }
    )

    result = scraper_coverage.discover_website(
        client,
        "https://example.com",
    )

    assert result == {
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/v2/retailers/1234/"
            "branches/{branch_id}/categories/{category_id}/products"
        ),
        "retailer_id": 1234,
        "available": True,
    }


def test_discover_website_adds_trailing_slash():
    frontend_data = make_frontend_data()
    data_js = make_data_js(frontend_data)

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                '<script src="https://example.com/data.js"></script>',
            ),
            "https://example.com/data.js": FakeResponse(
                200,
                data_js,
            ),
        }
    )

    result = scraper_coverage.discover_website(
        client,
        "https://example.com/",
    )

    assert result["data_url"] == (
        "https://example.com/data.js"
    )

    assert result["scraping_url"] == (
        "https://example.com/v2/retailers/1234/"
        "branches/{branch_id}/categories/{category_id}/products"
    )


def test_discover_website_invalid_frontend_data():
    data_js = make_data_js(
        {
            "rid": 1234,
            "retailer": {},
            "tree": {},
        }
    )

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                '<script src="https://example.com/data.js"></script>',
            ),
            "https://example.com/data.js": FakeResponse(
                200,
                data_js,
            ),
        }
    )

    with pytest.raises(KeyError):
        scraper_coverage.discover_website(
            client,
            "https://example.com",
        )


def test_discover_website_http_error():
    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                500,
                "Server error",
            ),
        }
    )

    with pytest.raises(RuntimeError, match="HTTP error"):
        scraper_coverage.discover_website(
            client,
            "https://example.com",
        )


def test_discover_website_403_uses_playwright(monkeypatch):
    frontend_data = make_frontend_data()
    data_js = make_data_js(frontend_data)

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(403),
            "https://example.com/data.js": FakeResponse(
                200,
                data_js,
            ),
        }
    )

    monkeypatch.setattr(
        scraper_coverage,
        "get_data_url_with_playwright",
        lambda url: "https://example.com/data.js",
    )

    result = scraper_coverage.discover_website(
        client,
        "https://example.com",
    )

    assert result == {
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/v2/retailers/1234/"
            "branches/{branch_id}/categories/{category_id}/products"
        ),
        "retailer_id": 1234,
        "available": False,
    }


def test_discover_website_no_data_js(monkeypatch):
    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                "<html>No data.js here</html>",
            ),
        }
    )

    def raise_playwright_error(url):
        raise RuntimeError(
            "Playwright could not find data.js."
        )

    monkeypatch.setattr(
        scraper_coverage,
        "get_data_url_with_playwright",
        raise_playwright_error,
    )

    with pytest.raises(
        RuntimeError,
        match="Playwright could not find data.js",
    ):
        scraper_coverage.discover_website(
            client,
            "https://example.com",
        )


def test_discover_website_no_branches():
    frontend_data = make_frontend_data()
    frontend_data["retailer"]["branches"] = []

    data_js = make_data_js(frontend_data)

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                '<script src="https://example.com/data.js"></script>',
            ),
            "https://example.com/data.js": FakeResponse(
                200,
                data_js,
            ),
        }
    )

    with pytest.raises(
        RuntimeError,
        match="No branches found",
    ):
        scraper_coverage.discover_website(
            client,
            "https://example.com",
        )


def test_discover_website_no_categories():
    frontend_data = make_frontend_data()
    frontend_data["tree"]["categories"] = []

    data_js = make_data_js(frontend_data)

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                '<script src="https://example.com/data.js"></script>',
            ),
            "https://example.com/data.js": FakeResponse(
                200,
                data_js,
            ),
        }
    )

    with pytest.raises(
        RuntimeError,
        match="No categories found",
    ):
        scraper_coverage.discover_website(
            client,
            "https://example.com",
        )


def test_discover_website_http_data_js_request(monkeypatch):
    frontend_data = make_frontend_data()
    data_js = make_data_js(frontend_data)

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                "<html>No data.js here</html>",
            ),
            "https://example.com/data.js": FakeResponse(
                200,
                data_js,
            ),
        }
    )

    monkeypatch.setattr(
        scraper_coverage,
        "get_data_url_with_playwright",
        lambda url: "https://example.com/data.js",
    )

    result = scraper_coverage.discover_website(
        client,
        "https://example.com",
    )

    assert result == {
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/v2/retailers/1234/"
            "branches/{branch_id}/categories/{category_id}/products"
        ),
        "retailer_id": 1234,
        "available": True,
    }


def test_discover_website_data_js_http_error():
    frontend_data = make_frontend_data()

    client = FakeClient(
        {
            "https://example.com/": FakeResponse(
                200,
                '<script src="https://example.com/data.js"></script>',
            ),
            "https://example.com/data.js": FakeResponse(
                500,
                "Server error",
            ),
        }
    )

    with pytest.raises(RuntimeError, match="HTTP error"):
        scraper_coverage.discover_website(
            client,
            "https://example.com",
        )