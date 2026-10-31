import json

import pytest

from parsers.product_page_type1 import (
    _basis_label,
    _classification,
    _collect_images,
    iter_products,
    parse_product,
)


GTIN = "7290008909853"


@pytest.fixture
def raw_product():
    return {
        "item_code": GTIN,
        "page_code": GTIN,
        "name": "חלב 3%",
        "categories": [
            {"1": "ראשי"},
            {"1": "מוצרי חלב"},
            {"1": "חלב"},
            {"1": "חלב 3%"},
        ],
        "images": [
            "https://example.com/products_regular/image1.jpg",
            "https://example.com/products_zoom/image2.jpg",
        ],
        "sections": [
            {
                "title": "נתונים",
                "content": {
                    'מק"ט': [GTIN],
                    "מותג/יצרן": ["תנובה"],
                },
            },
            {
                "title": "רכיבים",
                "content": ["חלב", "ויטמינים"],
            },
            {
                "title": "ערכים תזונתיים",
                "content": [
                    {
                        "for": "100 גרם",
                        "nutrients": {
                            "אנרגיה": {
                                "value": "250",
                                "unit": "קלוריות",
                            },
                            "שומן": {
                                "value": "פחות מ-3",
                                "unit": "גרם",
                            },
                        },
                    }
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Product parsing
# ---------------------------------------------------------------------------

def test_parse_product_returns_expected_fields(raw_product):
    product = parse_product(raw_product, "shufersal", "product.json")

    assert product["company"] == "shufersal"
    assert product["source"] == "shufersal"
    assert product["source_file"] == "product.json"

    assert product["barcode"] == GTIN
    assert product["local_barcode"] is None

    assert product["local_name"] == "חלב 3%"
    assert product["name_he"] == "חלב 3%"
    assert product["name_en"] is None

    assert product["brand_name_he"] == "תנובה"
    assert product["ingredients_he"] == "חלב, ויטמינים"

    assert product["category_path_he"] == ["מוצרי חלב", "חלב"]
    assert product["categories_paths"] == [
        [{"1": "מוצרי חלב"}, {"1": "חלב"}]
    ]


def test_parse_product_uses_item_code_before_other_candidates(raw_product):
    product = parse_product(raw_product, "shufersal", "product.json")

    assert product["barcode"] == GTIN


def test_parse_product_falls_back_to_page_code(raw_product):
    raw_product["item_code"] = "invalid"

    product = parse_product(raw_product, "shufersal", "product.json")

    assert product["barcode"] == GTIN
    assert product["local_barcode"] is None


def test_parse_product_falls_back_to_sku(raw_product):
    raw_product["item_code"] = "invalid"
    raw_product["page_code"] = None

    product = parse_product(raw_product, "shufersal", "product.json")

    assert product["barcode"] == GTIN
    assert product["local_barcode"] is None


def test_parse_product_preserves_invalid_barcode_as_local_barcode(raw_product):
    raw_product["item_code"] = "invalid"
    raw_product["page_code"] = None
    raw_product["sections"][0]["content"]['מק"ט'] = ["also-invalid"]

    product = parse_product(raw_product, "shufersal", "product.json")

    assert product["barcode"] is None
    assert product["local_barcode"] == "invalid"


# ---------------------------------------------------------------------------
# Nutrition
# ---------------------------------------------------------------------------

def test_parse_product_extracts_nutrition_values(raw_product):
    product = parse_product(raw_product, "shufersal", "product.json")

    nutrition = product["nutrition_values"]

    assert nutrition["sizes"] == [
        {
            "id": 1,
            "names": {"1": "ל-100 גרם"},
        }
    ]

    values = {item["names"]["1"]: item for item in nutrition["values"]}

    assert values["אנרגיה"]["sizeValues"] == [
        {
            "sizeId": 1,
            "unitOfMeasure": {"names": {"1": "קלוריות"}},
            "value": 250,
            "valueLessThan": False,
        }
    ]

    assert values["שומן"]["sizeValues"] == [
        {
            "sizeId": 1,
            "unitOfMeasure": {"names": {"1": "גרם"}},
            "value": 3,
            "valueLessThan": True,
        }
    ]


def test_parse_product_without_nutrition_returns_none(raw_product):
    raw_product["sections"] = [
        section
        for section in raw_product["sections"]
        if section["title"] != "ערכים תזונתיים"
    ]

    product = parse_product(raw_product, "shufersal", "product.json")

    assert product["nutrition_values"] is None


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def test_collect_images_deduplicates_and_skips_placeholders():
    raw = {
        "images": [
            "https://example.com/products_regular/regular.jpg",
            "https://example.com/products_zoom/zoom.jpg",
            "https://example.com/products_zoom/zoom.jpg",
            "https://example.com/products_regular/Z_P_default.png",
            "https://example.com/S_P_default.png?width=200",
        ]
    }

    images = _collect_images(raw)

    assert [image["url"] for image in images] == [
        "https://example.com/products_regular/regular.jpg",
        "https://example.com/products_zoom/zoom.jpg",
    ]

    assert images[0]["is_default"] is False
    assert images[1]["is_default"] is True
    assert images[0]["classification"] == "regular"
    assert images[1]["classification"] == "zoom"


def test_collect_images_uses_first_image_when_no_zoom_exists():
    images = _collect_images({
        "images": [
            "https://example.com/products_regular/first.jpg",
            "https://example.com/products_regular/second.jpg",
        ]
    })

    assert images[0]["is_default"] is True
    assert images[1]["is_default"] is False


def test_collect_images_without_images_returns_empty_list():
    assert _collect_images({}) == []


def test_classification_extracts_type_from_url():
    assert _classification(
        "https://example.com/products_zoom/image.jpg"
    ) == "zoom"

    assert _classification(
        "https://example.com/products_regular/image.jpg"
    ) == "regular"


def test_classification_returns_none_for_unmatched_url():
    assert _classification("https://example.com/image.jpg") is None


# ---------------------------------------------------------------------------
# Basis labels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("basis", "expected"),
    [
        ("100 גרם", "ל-100 גרם"),
        ("ליטר", "ליטר"),
        ('100 "גרם"', "ל-100 גרם"),
        (None, "לunknown"),
    ],
)
def test_basis_label(basis, expected):
    assert _basis_label(basis) == expected


# ---------------------------------------------------------------------------
# Product iteration
# ---------------------------------------------------------------------------

def test_iter_products_reads_single_product_file(tmp_path, raw_product):
    path = tmp_path / "shufersal" / "product.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(raw_product, ensure_ascii=False),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 1
    assert products[0]["barcode"] == GTIN
    assert products[0]["company"] == "shufersal"
    assert products[0]["source_file"] == "product.json"


def test_iter_products_reads_products_list(tmp_path, raw_product):
    path = tmp_path / "rami_levi" / "products.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {"products": [raw_product, None, "invalid"]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 1
    assert products[0]["company"] == "rami_levi"


def test_iter_products_reads_top_level_list(tmp_path, raw_product):
    path = tmp_path / "shufersal" / "products.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps([raw_product], ensure_ascii=False),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 1


def test_iter_products_counts_products_without_valid_gtin(
    tmp_path,
    raw_product,
):
    raw_product["item_code"] = "invalid"
    raw_product["page_code"] = None
    raw_product["sections"][0]["content"]['מק"ט'] = ["also-invalid"]

    path = tmp_path / "shufersal" / "products.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps([raw_product], ensure_ascii=False),
        encoding="utf-8",
    )

    stats = {}
    products = list(iter_products(path, stats=stats))

    assert len(products) == 1
    assert products[0]["barcode"] is None
    assert stats == {"no_valid_gtin": 1}


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"items": []},
        "invalid",
        123,
    ],
)
def test_iter_products_rejects_unrecognised_layout(tmp_path, document):
    path = tmp_path / "products.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="unrecognised type_1 layout"):
        list(iter_products(path))