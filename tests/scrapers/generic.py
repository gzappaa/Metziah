"""Tests for the generic retailer scraper."""

import json
from unittest.mock import Mock

import httpx

from scrapers import generic


def make_response(data=None, text="", status_code=200):
    request = httpx.Request(
        "GET",
        "https://example.com",
    )

    if data is not None:
        return httpx.Response(
            status_code=status_code,
            request=request,
            json=data,
        )

    return httpx.Response(
        status_code=status_code,
        request=request,
        text=text,
    )


def test_extract_js_object():
    text = """
    const something = 123;
    frontendData: {"tree": {"categories": []}, "retailer": {}};
    """

    result = generic.extract_js_object(
        text,
        "frontendData",
    )

    assert json.loads(result) == {
        "tree": {"categories": []},
        "retailer": {},
    }


def test_extract_js_object_handles_nested_objects_and_strings():
    text = r'''
    frontendData: {
        "name": "test } value",
        "nested": {
            "value": 123
        }
    };
    '''

    result = generic.extract_js_object(
        text,
        "frontendData",
    )

    assert json.loads(result) == {
        "name": "test } value",
        "nested": {"value": 123},
    }


def test_extract_js_object_missing_key():
    try:
        generic.extract_js_object(
            "something: {}",
            "frontendData",
        )
    except ValueError as exc:
        assert str(exc) == "Could not find frontendData"
    else:
        raise AssertionError("Expected ValueError")


def test_extract_js_object_missing_object():
    try:
        generic.extract_js_object(
            "frontendData:;",
            "frontendData",
        )
    except ValueError as exc:
        assert str(exc) == (
            "Could not find object for frontendData"
        )
    else:
        raise AssertionError("Expected ValueError")


def test_extract_js_object_unclosed_object():
    try:
        generic.extract_js_object(
            'frontendData: {"test": 123',
            "frontendData",
        )
    except ValueError as exc:
        assert str(exc) == "Could not extract frontendData"
    else:
        raise AssertionError("Expected ValueError")


def test_get_all_categories_flattens_nested_categories():
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

    result = generic.get_all_categories(categories)

    assert [category["id"] for category in result] == [
        1,
        2,
        3,
        4,
    ]


def test_get_all_categories_handles_missing_subcategories():
    categories = [
        {"id": 1},
        {"id": 2, "subCategories": []},
    ]

    assert generic.get_all_categories(categories) == categories


def test_load_retailers_only_returns_available(
    tmp_path,
    monkeypatch,
):
    config = {
        "1062": {
            "name_en_normalized": "tiv_taam",
            "available": True,
        },
        "9999": {
            "name_en_normalized": "unavailable",
            "available": False,
        },
        "1234": {
            "name_en_normalized": "missing_flag",
        },
    }

    config_file = tmp_path / "scraper_coverage.json"

    config_file.write_text(
        json.dumps(config),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        generic,
        "CONFIG_FILE",
        config_file,
    )

    assert generic.load_retailers() == [
        {
            "chain_id": "1062",
            "name_en_normalized": "tiv_taam",
            "available": True,
        }
    ]


def test_get_frontend_data():
    client = Mock()

    retailer = {
        "data_url": "https://example.com/data.js",
    }

    frontend_data = {
        "tree": {
            "categories": [],
        },
        "retailer": {
            "branches": [],
        },
    }

    client.get.return_value = make_response(
        text=(
            "frontendData: "
            + json.dumps(frontend_data)
            + ";"
        )
    )

    result = generic.get_frontend_data(
        client,
        retailer,
    )

    assert result == frontend_data

    client.get.assert_called_once_with(
        "https://example.com/data.js"
    )


def test_get_frontend_data_raises_for_http_error():
    client = Mock()

    retailer = {
        "data_url": "https://example.com/data.js",
    }

    response = make_response(status_code=500)
    client.get.return_value = response

    try:
        generic.get_frontend_data(
            client,
            retailer,
        )
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError(
            "Expected HTTPStatusError"
        )


def test_scrape_category_single_page():
    client = Mock()

    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    products = [
        {"barcode": "111"},
        {"barcode": "222"},
    ]

    client.get.return_value = make_response(
        data={
            "total": 2,
            "products": products,
        }
    )

    result = generic.scrape_category(
        client=client,
        retailer=retailer,
        branch_id="10",
        category_id="20",
    )

    assert result["products"] == products

    assert result["_metziah"] == {
        "chain_id": "1062",
        "retailer_id": "123",
        "branch_id": "10",
        "category_id": "20",
    }

    client.get.assert_called_once_with(
        "https://example.com/10/20",
        params={
            "from": 0,
            "size": 100,
        },
    )


def test_scrape_category_paginates():
    client = Mock()

    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    first_page = [
        {"barcode": str(i)}
        for i in range(100)
    ]

    second_page = [
        {"barcode": str(i)}
        for i in range(100, 105)
    ]

    client.get.side_effect = [
        make_response(
            data={
                "total": 105,
                "products": first_page,
            }
        ),
        make_response(
            data={
                "total": 105,
                "products": second_page,
            }
        ),
    ]

    result = generic.scrape_category(
        client=client,
        retailer=retailer,
        branch_id="10",
        category_id="20",
    )

    assert len(result["products"]) == 105
    assert result["products"] == (
        first_page + second_page
    )

    assert client.get.call_args_list[0].kwargs["params"] == {
        "from": 0,
        "size": 100,
    }

    assert client.get.call_args_list[1].kwargs["params"] == {
        "from": 100,
        "size": 100,
    }


def test_scrape_category_returns_none_when_no_products():
    client = Mock()

    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    client.get.return_value = make_response(
        data={
            "total": 0,
            "products": [],
        }
    )

    result = generic.scrape_category(
        client=client,
        retailer=retailer,
        branch_id="10",
        category_id="20",
    )

    assert result is None


def test_scrape_category_returns_none_on_initial_request_error():
    client = Mock()

    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    client.get.side_effect = httpx.HTTPError(
        "connection failed"
    )

    result = generic.scrape_category(
        client=client,
        retailer=retailer,
        branch_id="10",
        category_id="20",
    )

    assert result is None


def test_scrape_category_stops_on_empty_pagination_page():
    client = Mock()

    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    client.get.side_effect = [
        make_response(
            data={
                "total": 150,
                "products": [{"barcode": "1"}] * 100,
            }
        ),
        make_response(
            data={
                "total": 150,
                "products": [],
            }
        ),
    ]

    result = generic.scrape_category(
        client=client,
        retailer=retailer,
        branch_id="10",
        category_id="20",
    )

    assert result is None


def test_scrape_category_returns_none_on_pagination_error():
    client = Mock()

    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    client.get.side_effect = [
        make_response(
            data={
                "total": 150,
                "products": [{"barcode": "1"}] * 100,
            }
        ),
        httpx.HTTPError("pagination failed"),
    ]

    result = generic.scrape_category(
        client=client,
        retailer=retailer,
        branch_id="10",
        category_id="20",
    )

    assert result is None


def test_scrape_retailer_uses_first_branch_with_products(
    tmp_path,
    monkeypatch,
):
    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    frontend_data = {
        "tree": {
            "categories": [
                {"id": "10"},
                {"id": "20"},
            ],
        },
        "retailer": {
            "branches": [
                {"id": 1},
                {"id": 2},
            ],
        },
    }

    monkeypatch.setattr(
        generic,
        "OUTPUT_DIR",
        tmp_path,
    )

    monkeypatch.setattr(
        generic,
        "get_frontend_data",
        lambda client, retailer: frontend_data,
    )

    calls = []

    def fake_scrape_category(
        client,
        retailer,
        branch_id,
        category_id,
    ):
        calls.append(
            (branch_id, category_id)
        )

        if len(calls) == 1:
            return None

        if len(calls) == 2:
            return {
                "products": [
                    {"barcode": "123"},
                ]
            }

        return {
            "products": [
                {"barcode": "456"},
            ]
        }

    monkeypatch.setattr(
        generic,
        "scrape_category",
        fake_scrape_category,
    )

    assert generic.scrape_retailer(retailer) is True

    output_dir = tmp_path / "tiv_taam"

    assert json.loads(
        (output_dir / "10.json").read_text(
            encoding="utf-8"
        )
    )["products"] == [
        {"barcode": "123"},
    ]

    assert json.loads(
        (output_dir / "20.json").read_text(
            encoding="utf-8"
        )
    )["products"] == [
        {"barcode": "456"},
    ]

    assert calls == [
        ("1", "10"),
        ("2", "10"),
        ("1", "20"),
    ]


def test_scrape_retailer_skips_existing_category(
    tmp_path,
    monkeypatch,
):
    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    output_dir = tmp_path / "tiv_taam"
    output_dir.mkdir()

    existing_file = output_dir / "10.json"

    existing_file.write_text(
        '{"products": ["existing"]}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        generic,
        "OUTPUT_DIR",
        tmp_path,
    )

    monkeypatch.setattr(
        generic,
        "get_frontend_data",
        lambda client, retailer: {
            "tree": {
                "categories": [
                    {"id": "10"},
                ],
            },
            "retailer": {
                "branches": [
                    {"id": 1},
                ],
            },
        },
    )

    called = False

    def fake_scrape_category(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        generic,
        "scrape_category",
        fake_scrape_category,
    )

    assert generic.scrape_retailer(retailer) is True
    assert called is False

    assert json.loads(
        existing_file.read_text(
            encoding="utf-8"
        )
    ) == {
        "products": ["existing"],
    }


def test_scrape_retailer_returns_false_on_unexpected_error(
    monkeypatch,
):
    retailer = {
        "chain_id": "1062",
        "retailer_id": "123",
        "name_en_normalized": "tiv_taam",
        "data_url": "https://example.com/data.js",
        "scraping_url": (
            "https://example.com/"
            "{branch_id}/{category_id}"
        ),
    }

    def raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        generic,
        "get_frontend_data",
        raise_error,
    )

    assert generic.scrape_retailer(retailer) is False