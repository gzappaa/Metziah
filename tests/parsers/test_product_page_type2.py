import json

import pytest

from parsers.product_page_type2 import (
    _category_path,
    _collect_images,
    _description_he,
    _html_to_text,
    _keywords,
    _nutrition,
    _resolve_barcode,
    _to_number,
    iter_products,
    parse_product,
)


GTIN = "7290018893920"


@pytest.fixture
def raw_product():
    return {
        "item_code": GTIN,
        "source": "example",
        "url": "https://example.test/product",
        "page_code": GTIN,
        "name": "מוצר לדוגמה 700 גרם",
        "images": [
            "https://cdn.example.test/product/transparent.png",
            "https://cdn.example.test/product/trim.jpg",
            "https://cdn.example.test/product/large.jpg",
            "https://cdn.example.test/product/small.jpg",
        ],
        "details": {
            "id": 402149,
            "barcode": int(GTIN),
            "department": {
                "name": "חטיפים ומתוקים",
                "id": 56,
            },
            "group": {
                "name": "סוכריות ומסטיקים",
                "id": 301,
            },
            "subGroup": {
                "name": "סוכריות ג'לי",
                "id": 395,
            },
            "department_id": 56,
            "group_id": 301,
            "sub_group_id": 395,
            "images": {
                "small": "/product/small.jpg",
                "original": "/product/large.jpg",
                "trim": "/product/trim.jpg",
                "transparent": "/product/transparent.png",
                "gallery": [],
            },
            "full_desc": "",
            "short_desc": "",
            "properties": [],
            "gs": {
                "Ingredient_Sequence_and_Name": "סוכר, סירופ גלוקוז",
                "BrandName": "מותג לדוגמה",
                "Product_Description_English": "Example product",
                "Search_Tags": [
                    GTIN,
                    "סוכריות",
                    "ממתקים",
                    "",
                    "סוכריות",
                ],
                "Nutritional_Values": [
                    {
                        "code": "79001",
                        "label": "אנרגיה (קלוריות)",
                        "fields": [
                            {
                                "col_code": "78001",
                                "col_label": "ל-100 גרם",
                                "UOM": "קלוריות",
                                "text": "321 קלוריות",
                                "value": "321",
                            }
                        ],
                    },
                    {
                        "code": "79007",
                        "label": "שומנים (גרם)",
                        "fields": [
                            {
                                "col_code": "78001",
                                "col_label": "ל-100 גרם",
                                "UOM": "גרם",
                                "text": "0 גרם",
                                "value": "0",
                            }
                        ],
                    },
                    {
                        "code": "79011",
                        "label": "נתרן (מג)",
                        "fields": [
                            {
                                "col_code": "78001",
                                "col_label": "ל-100 גרם",
                                "UOM": "מג",
                                "text": "פחות מ-5 מג",
                                "value": "5",
                            }
                        ],
                    },
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("6.3", 6.3),
        ("182", 182),
        ("1,5", 1.5),
        ("0", 0),
        ("abc", "abc"),
        (None, None),
        ("", None),
    ],
)
def test_to_number(value, expected):
    assert _to_number(value) == expected


def test_html_to_text():
    assert _html_to_text(
        "<p>First line</p><p>Second&nbsp;line</p>"
    ) == "First line\nSecond line"


def test_html_to_text_empty():
    assert _html_to_text("") is None
    assert _html_to_text(None) is None


# ---------------------------------------------------------------------------
# Barcode
# ---------------------------------------------------------------------------

def test_resolve_barcode_from_details(raw_product):
    assert _resolve_barcode(raw_product) == (GTIN, None)


def test_resolve_barcode_falls_back_to_item_code(raw_product):
    raw_product["details"]["barcode"] = None

    assert _resolve_barcode(raw_product) == (GTIN, None)


def test_resolve_barcode_falls_back_to_page_code(raw_product):
    raw_product["details"]["barcode"] = None
    raw_product["item_code"] = None

    assert _resolve_barcode(raw_product) == (GTIN, None)


def test_resolve_barcode_keeps_invalid_code_as_local_barcode(raw_product):
    raw_product["details"]["barcode"] = 32147231
    raw_product["item_code"] = "32147231"
    raw_product["page_code"] = "32147231"

    assert _resolve_barcode(raw_product) == (None, "32147231")


def test_resolve_barcode_removes_float_suffix(raw_product):
    raw_product["details"]["barcode"] = f"{GTIN}.0"

    assert _resolve_barcode(raw_product) == (GTIN, None)


def test_resolve_barcode_missing_code():
    assert _resolve_barcode({"details": {}}) == (None, None)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def test_category_path(raw_product):
    details = raw_product["details"]

    assert _category_path(details) == [
        {"id": 56, "name_he": "חטיפים ומתוקים"},
        {"id": 301, "name_he": "סוכריות ומסטיקים"},
        {"id": 395, "name_he": "סוכריות ג'לי"},
    ]


def test_category_path_uses_fallback_ids(raw_product):
    details = raw_product["details"]

    details["department"] = {"name": "מחלקה"}
    details["group"] = {"name": "קבוצה"}
    details["subGroup"] = {"name": "תת קבוצה"}

    assert _category_path(details) == [
        {"id": 56, "name_he": "מחלקה"},
        {"id": 301, "name_he": "קבוצה"},
        {"id": 395, "name_he": "תת קבוצה"},
    ]


def test_category_path_skips_missing_names():
    assert _category_path({
        "department": {"id": 1},
        "group": {"name": "קבוצה", "id": 2},
        "subGroup": None,
    }) == [
        {"id": 2, "name_he": "קבוצה"},
    ]


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def test_collect_images_uses_absolute_urls_from_raw(raw_product):
    images = _collect_images(raw_product)

    assert images == [
        {
            "url": "https://cdn.example.test/product/large.jpg",
            "type": "original",
            "is_default": True,
        },
        {
            "url": "https://cdn.example.test/product/trim.jpg",
            "type": "trim",
            "is_default": False,
        },
        {
            "url": "https://cdn.example.test/product/small.jpg",
            "type": "small",
            "is_default": False,
        },
        {
            "url": "https://cdn.example.test/product/transparent.png",
            "type": "transparent",
            "is_default": False,
        },
    ]


def test_collect_images_without_raw_images(raw_product):
    raw_product["images"] = []

    assert _collect_images(raw_product) == []


def test_collect_images_without_details_images(raw_product):
    raw_product["details"]["images"] = {}

    assert _collect_images(raw_product) == []


def test_collect_images_deduplicates_urls(raw_product):
    raw_product["images"].append(
        "https://cdn.example.test/product/large.jpg"
    )

    images = _collect_images(raw_product)

    urls = [image["url"] for image in images]

    assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# Nutrition
# ---------------------------------------------------------------------------

def test_nutrition(raw_product):
    gs = raw_product["details"]["gs"]
    nutrition = _nutrition(gs)

    assert nutrition is not None
    assert nutrition["sizes"] == [
        {
            "id": 78001,
            "names": {"1": "ל-100 גרם"},
        }
    ]

    assert nutrition["values"] == [
        {
            "id": 79001,
            "names": {"1": "אנרגיה (קלוריות)"},
            "sizeValues": [
                {
                    "sizeId": 78001,
                    "unitOfMeasure": {"names": {"1": "קלוריות"}},
                    "value": 321,
                    "valueLessThan": False,
                }
            ],
        },
        {
            "id": 79007,
            "names": {"1": "שומנים (גרם)"},
            "sizeValues": [
                {
                    "sizeId": 78001,
                    "unitOfMeasure": {"names": {"1": "גרם"}},
                    "value": 0,
                    "valueLessThan": False,
                }
            ],
        },
        {
            "id": 79011,
            "names": {"1": "נתרן (מג)"},
            "sizeValues": [
                {
                    "sizeId": 78001,
                    "unitOfMeasure": {"names": {"1": "מג"}},
                    "value": 5,
                    "valueLessThan": True,
                }
            ],
        },
    ]


def test_nutrition_without_values():
    assert _nutrition({}) is None
    assert _nutrition({"Nutritional_Values": []}) is None


def test_nutrition_skips_invalid_nutrients():
    result = _nutrition({
        "Nutritional_Values": [
            None,
            {},
            {"code": "1", "label": "", "fields": []},
        ]
    })

    assert result is None


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

def test_keywords(raw_product):
    gs = raw_product["details"]["gs"]

    assert _keywords(gs, {GTIN}) == [
        "סוכריות",
        "ממתקים",
    ]


def test_keywords_removes_duplicates_and_empty_values():
    assert _keywords(
        {"Search_Tags": ["one", "", None, "one", "two"]},
        set(),
    ) == ["one", "two"]


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------

def test_description_uses_full_description():
    assert _description_he({
        "full_desc": "<p>תיאור מלא</p>",
        "short_desc": "תיאור קצר",
    }) == "תיאור מלא"


def test_description_falls_back_to_short_description():
    assert _description_he({
        "full_desc": "",
        "short_desc": "<p>תיאור קצר</p>",
    }) == "תיאור קצר"


def test_description_falls_back_to_properties():
    assert _description_he({
        "full_desc": "",
        "short_desc": "",
        "properties": [
            {
                "property_parent_name": "תיאור מוצר",
                "value": "<p>תיאור מתוך מאפיינים</p>",
            },
            {
                "property_parent_name": "אחר",
                "value": "לא לכלול",
            },
        ],
    }) == "תיאור מתוך מאפיינים"


def test_description_without_content():
    assert _description_he({}) is None


# ---------------------------------------------------------------------------
# parse_product
# ---------------------------------------------------------------------------

def test_parse_product(raw_product):
    product = parse_product(raw_product)

    assert product["barcode"] == GTIN
    assert product["local_barcode"] is None

    assert product["product_id"] == 402149
    assert product["id"] == 402149

    assert product["local_name"] == "מוצר לדוגמה 700 גרם"
    assert product["name_he"] == "מוצר לדוגמה 700 גרם"

    assert product["brand_name_he"] == "מותג לדוגמה"
    assert product["description_en"] == "Example product"

    assert product["ingredients_he"] == "סוכר, סירופ גלוקוז"

    assert product["department_id"] == 56
    assert product["department_name"] == "חטיפים ומתוקים"

    assert product["family_id"] == 301
    assert product["family_name_he"] == "סוכריות ומסטיקים"

    assert product["category_ids"] == [56, 301, 395]
    assert product["category_path_ids"] == [56, 301, 395]
    assert product["category_path_he"] == [
        "חטיפים ומתוקים",
        "סוכריות ומסטיקים",
        "סוכריות ג'לי",
    ]

    assert product["search_keywords"] == ["סוכריות", "ממתקים"]
    assert product["family_search_keywords"] == []

    assert product["nutrition_facts"] is None
    assert product["nutrition_values"] is not None

    assert product["main_image_url"] == (
        "https://cdn.example.test/product/large.jpg"
    )

    assert len(product["images"]) == 4
    assert product["images"][0]["is_default"] is True


def test_parse_product_with_invalid_barcode(raw_product):
    raw_product["details"]["barcode"] = 32147231
    raw_product["item_code"] = "32147231"

    product = parse_product(raw_product)

    assert product["barcode"] is None
    assert product["local_barcode"] == "32147231"


def test_parse_product_without_images(raw_product):
    raw_product["images"] = []
    raw_product["details"]["images"] = {}

    product = parse_product(raw_product)

    assert product["images"] == []
    assert product["main_image_url"] is None


def test_parse_product_without_nutrition(raw_product):
    raw_product["details"]["gs"]["Nutritional_Values"] = []

    product = parse_product(raw_product)

    assert product["nutrition_values"] is None


def test_parse_product_with_missing_details():
    product = parse_product({
        "item_code": GTIN,
        "name": "מוצר",
    })

    assert product["barcode"] == GTIN
    assert product["local_name"] == "מוצר"
    assert product["name_he"] == "מוצר"
    assert product["images"] == []
    assert product["nutrition_values"] is None


# ---------------------------------------------------------------------------
# iter_products
# ---------------------------------------------------------------------------

def test_iter_products_single_product(tmp_path, raw_product):
    path = tmp_path / "product.json"
    path.write_text(
        json.dumps(raw_product, ensure_ascii=False),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 1
    assert products[0]["barcode"] == GTIN


def test_iter_products_products_layout(tmp_path, raw_product):
    path = tmp_path / "products.json"
    path.write_text(
        json.dumps({"products": [raw_product, raw_product]}, ensure_ascii=False),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 2


def test_iter_products_list_layout(tmp_path, raw_product):
    path = tmp_path / "products.json"
    path.write_text(
        json.dumps([raw_product, raw_product], ensure_ascii=False),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 2


def test_iter_products_skips_non_mapping_entries(tmp_path, raw_product):
    path = tmp_path / "products.json"
    path.write_text(
        json.dumps([None, "invalid", raw_product], ensure_ascii=False),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 1
    assert products[0]["barcode"] == GTIN


def test_iter_products_updates_stats(tmp_path, raw_product):
    raw_product["details"]["barcode"] = 32147231
    raw_product["item_code"] = "32147231"

    path = tmp_path / "products.json"
    path.write_text(
        json.dumps([raw_product, raw_product], ensure_ascii=False),
        encoding="utf-8",
    )

    stats = {}
    products = list(iter_products(path, stats=stats))

    assert len(products) == 2
    assert stats["no_valid_gtin"] == 2


def test_iter_products_does_not_count_valid_gtins(tmp_path, raw_product):
    path = tmp_path / "products.json"
    path.write_text(
        json.dumps([raw_product], ensure_ascii=False),
        encoding="utf-8",
    )

    stats = {}
    list(iter_products(path, stats=stats))

    assert stats == {}


def test_iter_products_unrecognized_layout(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps({"unexpected": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unrecognised type_2 layout"):
        list(iter_products(path))