import json

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

    try:
        scraper_coverage.extract_js_object(
            text,
            "frontendData",
        )
    except ValueError as exc:
        assert "Could not find frontendData" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


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


def test_get_data_url_from_html_missing():
    assert scraper_coverage.get_data_url_from_html(
        "<html></html>"
    ) is None


def test_test_website_success():
    frontend_data = make_frontend_data()
    data_js = make_data_js(frontend_data)

    responses = {
        "https://example.com/": FakeResponse(
            200,
            '<script src="https://example.com/data.js"></script>',
        ),
        "https://example.com/data.js": FakeResponse(
            200,
            data_js,
        ),
    }

    class FakeClient:
        def get(self, url, **kwargs):
            return responses[url]

    result = scraper_coverage.test_website(
        FakeClient(),
        None,
        "https://example.com",
    )

    assert result == {
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/v2/retailers/1234/"
            "branches/{branch_id}/categories/{category_id}/products"
        ),
        "retailer_id": 1234,
    }


def test_test_website_invalid_frontend_data():
    data_js = make_data_js(
        {
            "rid": 1234,
            "retailer": {},
            "tree": {},
        }
    )

    responses = {
        "https://example.com/": FakeResponse(
            200,
            '<script src="https://example.com/data.js"></script>',
        ),
        "https://example.com/data.js": FakeResponse(
            200,
            data_js,
        ),
    }

    class FakeClient:
        def get(self, url, **kwargs):
            return responses[url]

    assert scraper_coverage.test_website(
        FakeClient(),
        None,
        "https://example.com",
    ) is None


def test_test_website_http_error():
    class FakeClient:
        def get(self, url, **kwargs):
            return FakeResponse(
                500,
                "Server error",
            )

    assert scraper_coverage.test_website(
        FakeClient(),
        None,
        "https://example.com",
    ) is None


def test_test_website_403_uses_playwright(monkeypatch):
    frontend_data = make_frontend_data()
    data_js = make_data_js(frontend_data)

    class FakeClient:
        def get(self, url, **kwargs):
            if url == "https://example.com/":
                return FakeResponse(403)

            if url == "https://example.com/data.js":
                return FakeResponse(200, data_js)

            raise AssertionError(url)

    monkeypatch.setattr(
        scraper_coverage,
        "get_data_url_with_playwright",
        lambda page, url: "https://example.com/data.js",
    )

    result = scraper_coverage.test_website(
        FakeClient(),
        object(),
        "https://example.com",
    )

    assert result == {
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/v2/retailers/1234/"
            "branches/{branch_id}/categories/{category_id}/products"
        ),
        "retailer_id": 1234,
    }


def test_test_website_no_data_js():
    class FakeClient:
        def get(self, url, **kwargs):
            return FakeResponse(
                200,
                "<html>No data.js here</html>",
            )

    assert scraper_coverage.test_website(
        FakeClient(),
        None,
        "https://example.com",
    ) is None