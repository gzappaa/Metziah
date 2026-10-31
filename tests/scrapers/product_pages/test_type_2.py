from scrapers.product_pages.type_2 import (
    find_product,
    matches,
    parse,
)


# ============================================================
# find_product
# ============================================================

def test_find_product_returns_matching_product():
    payload = {
        "data": {
            "product": {
                "itemCode": "7291234567890",
                "name": "Fresh Milk",
            }
        }
    }

    assert find_product(payload, "7291234567890") == {
        "itemCode": "7291234567890",
        "name": "Fresh Milk",
    }


def test_find_product_searches_nested_lists():
    payload = {
        "data": [
            {"name": "Bread", "code": "111"},
            {"name": "Milk", "code": "7291234567890"},
        ]
    }

    assert find_product(payload, "7291234567890") == {
        "name": "Milk",
        "code": "7291234567890",
    }


def test_find_product_returns_none_when_code_missing():
    payload = {
        "data": {
            "product": {
                "code": "111",
                "name": "Bread",
            }
        }
    }

    assert find_product(payload, "7291234567890") is None


def test_find_product_accepts_numeric_item_code():
    payload = {
        "product": {
            "code": 7291234567890,
            "name": "Milk",
        }
    }

    assert find_product(payload, "7291234567890") == payload["product"]


def test_find_product_handles_empty_payload():
    assert find_product({}, "123") is None
    assert find_product([], "123") is None
    assert find_product(None, "123") is None


# ============================================================
# matches
# ============================================================

def test_matches_returns_true_for_matching_product():
    payload = {
        "data": {
            "product": {
                "code": "7291234567890",
                "name": "Milk",
            }
        }
    }

    assert matches(payload, "7291234567890") is True


def test_matches_returns_false_for_unrelated_payload():
    payload = {
        "data": {
            "product": {
                "code": "111",
                "name": "Bread",
            }
        }
    }

    assert matches(payload, "7291234567890") is False


# ============================================================
# parse
# ============================================================

def test_parse_basic_product():
    payload = {
        "data": {
            "product": {
                "code": "7291234567890",
                "name": "  Fresh   Milk  ",
                "images": {
                    "main": "/images/milk.jpg",
                },
                "price": 8.90,
            }
        }
    }

    result = parse(
        payload,
        "7291234567890",
        "https://www.example.com/product/7291234567890",
    )

    assert result == {
        "page_code": "7291234567890",
        "name": "Fresh Milk",
        "images": [
            "https://img.example.com/images/milk.jpg",
        ],
        "details": payload["data"]["product"],
    }


def test_parse_returns_none_when_product_not_found():
    payload = {
        "data": {
            "product": {
                "code": "111",
                "name": "Bread",
            }
        }
    }

    assert parse(
        payload,
        "7291234567890",
        "https://www.example.com",
    ) is None


def test_parse_uses_name_keys_in_priority_order():
    payload = {
        "product": {
            "code": "123",
            "title": "Product Title",
            "name": "Product Name",
            "product_name": "Product Name Field",
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["name"] == "Product Name"


def test_parse_uses_fallback_name_keys():
    payload = {
        "product": {
            "code": "123",
            "title": "Product Title",
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["name"] == "Product Title"


def test_parse_returns_none_name_when_no_name_key_exists():
    payload = {
        "product": {
            "code": "123",
            "price": 10,
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["name"] is None


def test_parse_returns_none_name_when_name_is_empty():
    payload = {
        "product": {
            "code": "123",
            "name": "   ",
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["name"] is None


# ============================================================
# Image extraction
# ============================================================

def test_parse_nested_images():
    payload = {
        "product": {
            "code": "123",
            "name": "Milk",
            "images": {
                "main": "main.jpg",
                "gallery": [
                    "front.jpg",
                    "back.webp",
                ],
            },
        }
    }

    result = parse(payload, "123", "https://example.com/product/123")

    assert result["images"] == [
        "https://example.com/back.webp",
        "https://example.com/front.jpg",
        "https://example.com/main.jpg",
    ]



def test_parse_removes_duplicate_images():
    payload = {
        "product": {
            "code": "123",
            "images": {
                "main": "/images/milk.jpg",
                "gallery": [
                    "/images/milk.jpg",
                    "/images/back.jpg",
                ],
            },
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["images"] == [
        "https://example.com/images/back.jpg",
        "https://example.com/images/milk.jpg",
    ]


def test_parse_ignores_non_image_values():
    payload = {
        "product": {
            "code": "123",
            "images": {
                "main": "/images/milk.jpg",
                "description": "Fresh milk",
                "id": "12345",
                "other": "/images/document.pdf",
            },
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["images"] == [
        "https://example.com/images/milk.jpg",
    ]


def test_parse_ignores_images_outside_images_field():
    payload = {
        "product": {
            "code": "123",
            "name": "Milk",
            "banner": "/images/banner.jpg",
            "images": {
                "main": "/images/milk.jpg",
            },
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["images"] == [
        "https://example.com/images/milk.jpg",
    ]


def test_parse_handles_missing_images():
    payload = {
        "product": {
            "code": "123",
            "name": "Milk",
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["images"] == []


def test_parse_handles_relative_image_paths():
    payload = {
        "product": {
            "code": "123",
            "images": {
                "main": "images/milk.jpg",
            },
        }
    }

    result = parse(payload, "123", "https://www.example.com")

    assert result["images"] == [
        "https://img.example.com/images/milk.jpg",
    ]


def test_parse_case_insensitive_image_extensions():
    payload = {
        "product": {
            "code": "123",
            "name": "Milk",
            "images": [
                "milk.jpg",
                "milk.AVIF",
            ],
        }
    }

    result = parse(payload, "123", "https://example.com/product/123")

    assert result["images"] == [
        "https://example.com/milk.AVIF",
        "https://example.com/milk.jpg",
    ]


def test_parse_preserves_full_product_details():
    payload = {
        "product": {
            "code": "123",
            "name": "Milk",
            "price": 8.90,
            "manufacturer": "Example",
            "nutrition": {
                "protein": 3.2,
                "fat": 2.0,
            },
            "unknown_field": ["A", "B"],
        }
    }

    result = parse(payload, "123", "https://example.com")

    assert result["details"] == payload["product"]