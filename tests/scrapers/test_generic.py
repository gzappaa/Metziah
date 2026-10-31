
import json

import httpx
import pytest

from scrapers import generic


def test_extract_js_object():
    text = '''
    const config = {
        frontendData: {
            "name": "Store",
            "nested": {"items": [1, 2]},
            "text": "a } inside a string"
        }
    };
    '''

    result = generic.extract_js_object(
        text,
        "frontendData",
    )

    assert json.loads(result) == {
        "name": "Store",
        "nested": {"items": [1, 2]},
        "text": "a } inside a string",
    }


def test_extract_js_object_missing_key():
    with pytest.raises(ValueError, match="Could not find missing"):
        generic.extract_js_object(
            "const data = {};",
            "missing",
        )


def test_extract_js_object_missing_object():
    with pytest.raises(
        ValueError,
        match="Could not find object for frontendData",
    ):
        generic.extract_js_object(
            "frontendData: null",
            "frontendData",
        )


def test_extract_js_object_unclosed_object():
    with pytest.raises(
        ValueError,
        match="Could not extract frontendData",
    ):
        generic.extract_js_object(
            'frontendData: {"items": [1, 2]',
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
        {"id": 4},
    ]

    result = generic.get_all_categories(categories)

    assert [category["id"] for category in result] == [
        1, 2, 3, 4,
    ]


def test_get_all_categories_empty():
    assert generic.get_all_categories([]) == []


def test_load_retailers_filters_available_true(
    monkeypatch,
    tmp_path,
):
    config_file = tmp_path / "scraper_coverage.json"
    config_file.write_text(
        json.dumps(
            {
                "7442": {
                    "available": True,
                    "name_en_normalized": "store_a",
                },
                "1234": {
                    "available": False,
                    "name_en_normalized": "store_b",
                },
                "5678": {
                    "available": "true",
                    "name_en_normalized": "store_c",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        generic,
        "CONFIG_FILE",
        config_file,
    )

    assert generic.load_retailers() == [
        {
            "chain_id": "7442",
            "available": True,
            "name_en_normalized": "store_a",
        },
    ]


def test_get_frontend_data():
    class FakeResponse:
        text = (
            'window.config = {frontendData: '
            '{"tree": {"categories": []}, '
            '"retailer": {"branches": []}}};'
        )

        def raise_for_status(self):
            pass

    class FakeClient:
        def get(self, url):
            assert url == "https://example.com/data"
            return FakeResponse()

    result = generic.get_frontend_data(
        FakeClient(),
        {"data_url": "https://example.com/data"},
    )

    assert result == {
        "tree": {"categories": []},
        "retailer": {"branches": []},
    }


def test_scrape_category_paginates():
    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class FakeClient:
        def __init__(self):
            self.offsets = []

        def get(self, url, params):
            self.offsets.append(params["from"])

            if params["from"] == 0:
                return FakeResponse(
                    {
                        "total": 3,
                        "products": [{"id": 1}, {"id": 2}],
                    }
                )

            return FakeResponse(
                {
                    "total": 3,
                    "products": [{"id": 3}],
                }
            )

    client = FakeClient()
    retailer = {
        "chain_id": "7442",
        "retailer_id": "retailer-1",
        "name_en_normalized": "store_a",
        "scraping_url": (
            "https://example.com/branches/{branch_id}/"
            "categories/{category_id}"
        ),
    }

    result = generic.scrape_category(
        client,
        retailer,
        branch_id="10",
        category_id=20,
    )

    assert client.offsets == [0, 2]
    assert result["total"] == 3
    assert result["products"] == [
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]
    assert result["_metziah"] == {
        "chain_id": "7442",
        "retailer_id": "retailer-1",
        "branch_id": "10",
        "category_id": 20,
    }


def test_scrape_category_returns_none_on_http_error():
    class FakeClient:
        def get(self, url, params):
            raise httpx.ConnectError("connection failed")

    retailer = {
        "chain_id": "7442",
        "retailer_id": "retailer-1",
        "name_en_normalized": "store_a",
        "scraping_url": "https://example.com/{branch_id}/{category_id}",
    }

    result = generic.scrape_category(
        FakeClient(),
        retailer,
        branch_id="10",
        category_id=20,
    )

    assert result is None


def test_scrape_category_stops_on_empty_pagination_page():
    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class FakeClient:
        def get(self, url, params):
            if params["from"] == 0:
                return FakeResponse(
                    {
                        "total": 3,
                        "products": [{"id": 1}],
                    }
                )

            return FakeResponse(
                {
                    "total": 3,
                    "products": [],
                }
            )

    retailer = {
        "chain_id": "7442",
        "retailer_id": "retailer-1",
        "name_en_normalized": "store_a",
        "scraping_url": "https://example.com/{branch_id}/{category_id}",
    }

    result = generic.scrape_category(
        FakeClient(),
        retailer,
        branch_id="10",
        category_id=20,
    )

    assert result is None


def test_scrape_retailer_saves_category_json(
    monkeypatch,
    tmp_path,
):
    output_dir = tmp_path / "raw"
    monkeypatch.setattr(generic, "OUTPUT_DIR", output_dir)

    frontend_data = {
        "tree": {
            "categories": [
                {"id": 20, "subCategories": [{"id": 21}]},
            ],
        },
        "retailer": {
            "branches": [{"id": 10}],
        },
    }

    class FakeResponse:
        def __init__(self, data=None, text=""):
            self.data = data
            self.text = text

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == generic.REQUEST_TIMEOUT
            self.category_calls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params=None):
            if url == "https://example.com/frontend":
                return FakeResponse(
                    text=(
                        "frontendData: "
                        + json.dumps(frontend_data)
                    )
                )

            self.category_calls.append(url)

            return FakeResponse(
                {
                    "total": 1,
                    "products": [{"id": 99, "name": "Milk"}],
                }
            )

    monkeypatch.setattr(
        generic.httpx,
        "Client",
        FakeClient,
    )

    retailer = {
        "chain_id": "7442",
        "retailer_id": "retailer-1",
        "name_en_normalized": "store_a",
        "data_url": "https://example.com/frontend",
        "scraping_url": (
            "https://example.com/{branch_id}/{category_id}"
        ),
    }

    assert generic.scrape_retailer(retailer) is True

    first_file = output_dir / "store_a" / "20.json"
    second_file = output_dir / "store_a" / "21.json"

    assert first_file.exists()
    assert second_file.exists()

    saved = json.loads(first_file.read_text(encoding="utf-8"))

    assert saved["products"] == [
        {"id": 99, "name": "Milk"},
    ]
    assert saved["_metziah"] == {
        "chain_id": "7442",
        "retailer_id": "retailer-1",
        "branch_id": "10",
        "category_id": 20,
    }


def test_scrape_retailer_skips_existing_category(
    monkeypatch,
    tmp_path,
):
    output_dir = tmp_path / "raw"
    monkeypatch.setattr(generic, "OUTPUT_DIR", output_dir)

    retailer_dir = output_dir / "store_a"
    retailer_dir.mkdir(parents=True)
    existing_file = retailer_dir / "20.json"
    existing_file.write_text(
        '{"products": [{"id": 1}]}',
        encoding="utf-8",
    )

    frontend_data = {
        "tree": {"categories": [{"id": 20}]},
        "retailer": {"branches": [{"id": 10}]},
    }

    class FakeResponse:
        text = (
            "frontendData: "
            + json.dumps(frontend_data)
        )

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params=None):
            assert url == "https://example.com/frontend"
            return FakeResponse()

    monkeypatch.setattr(
        generic.httpx,
        "Client",
        FakeClient,
    )

    retailer = {
        "chain_id": "7442",
        "retailer_id": "retailer-1",
        "name_en_normalized": "store_a",
        "data_url": "https://example.com/frontend",
        "scraping_url": "https://example.com/{branch_id}/{category_id}",
    }

    assert generic.scrape_retailer(retailer) is True

    assert json.loads(
        existing_file.read_text(encoding="utf-8")
    ) == {"products": [{"id": 1}]}
