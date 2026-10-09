import json

import pytest

from parsers.product_json import iter_products, parse_product


@pytest.fixture
def raw_product():
    return {
        "supplierId": 12345,
        "localBarcode": "7291234567890",
        "id": 987654,
        "productId": 456789,
        "retailerId": 1492,
        "barcode": "7291234567890",
        "localName": "מיץ תפוחים טבעי 1 ליטר",
        "names": {
            "1": {"short": "מיץ תפוחים", "long": "מיץ תפוחים טבעי"},
            "2": {"short": "Apple Juice", "long": "Natural Apple Juice"},
            "4": {"short": "Яблочный сок", "long": "Натуральный яблочный сок"},
        },
        "brand": {
            "id": 321,
            "names": {
                "1": "תפוח הזהב",
                "2": "Golden Apple",
                "4": "Золотое яблоко",
            },
        },
        "department": {
            "id": 100,
            "externalId": 10,
            "name": "משקאות",
        },
        "family": {
            "id": 200,
            "names": {
                "1": {"name": "מיצים"},
                "2": {"name": "Juices"},
                "4": {"name": "Соки"},
            },
            "searchKeywords": ["מיץ", "תפוחים"],
            "categories": [
                {"id": 11},
                {"id": 12},
            ],
            "categoriesPaths": [
                [
                    {
                        "id": 11,
                        "names": {
                            "1": "משקאות",
                            "2": "Beverages",
                            "4": "Напитки",
                        },
                    },
                    {
                        "id": 12,
                        "names": {
                            "1": "מיצים טבעיים",
                            "2": "Natural Juices",
                            "4": "Натуральные соки",
                        },
                    },
                ],
            ],
            "mainCategoryPathIndex": 0,
        },
        "searchKeywords": ["תפוחים", "טבעי"],
        "data": {
            "1": {
                "ingredients": "תפוחים 100%",
                "description": "מיץ תפוחים טבעי ללא תוספת סוכר",
            },
            "2": {
                "ingredients": "100% apples",
                "description": "Natural apple juice with no added sugar",
            },
        },
        "nutritionFacts": {"energy": 46},
        "nutritionValues": {"sugar": 10.3},
        "image": {
            "id": 555,
            "url": "https://example.com/apple-juice.jpg",
            "isDefault": True,
            "source": 1,
            "classification": "product",
            "sort": 0,
            "tag": "front",
            "uploadedOn": "2026-01-15T10:00:00",
            "backupPath": "images/apple-juice.jpg",
        },
        "images": [
            {
                "id": 555,
                "url": "https://example.com/apple-juice.jpg",
                "isDefault": True,
            },
            {
                "id": 556,
                "url": "https://example.com/apple-juice-back.jpg",
                "isDefault": False,
                "sort": 1,
            },
        ],
        "nutritionImageUrl": "https://example.com/apple-juice-nutrition.jpg",
    }


def test_parse_product_maps_identity_and_names(raw_product):
    product = parse_product(raw_product)

    assert product["barcode"] == "7291234567890"
    assert product["local_barcode"] == "7291234567890"
    assert product["product_id"] == 456789
    assert product["id"] == 987654
    assert product["retailer_id"] == 1492
    assert product["supplier_id"] == 12345

    assert product["local_name"] == "מיץ תפוחים טבעי 1 ליטר"
    assert product["name_he"] == "מיץ תפוחים טבעי"
    assert product["name_en"] == "Natural Apple Juice"
    assert product["name_ru"] == "Натуральный яблочный сок"


def test_parse_product_maps_brand_and_categories(raw_product):
    product = parse_product(raw_product)

    assert product["brand_id"] == 321
    assert product["brand_name_he"] == "תפוח הזהב"
    assert product["brand_name_en"] == "Golden Apple"
    assert product["brand_name_ru"] == "Золотое яблоко"

    assert product["department_id"] == 100
    assert product["department_external_id"] == 10
    assert product["department_name"] == "משקאות"

    assert product["family_id"] == 200
    assert product["family_name_he"] == "מיצים"
    assert product["family_name_en"] == "Juices"

    assert product["category_ids"] == [11, 12]
    assert product["category_path_ids"] == [11, 12]
    assert product["category_path_he"] == ["משקאות", "מיצים טבעיים"]
    assert product["category_path_en"] == ["Beverages", "Natural Juices"]


def test_parse_product_maps_images_and_enrichment(raw_product):
    product = parse_product(raw_product)

    assert product["main_image_url"] == "https://example.com/apple-juice.jpg"
    assert len(product["images"]) == 2
    assert product["images"][0]["id"] == 555
    assert product["images"][0]["is_default"] is True
    assert product["nutrition_image_url"] == (
        "https://example.com/apple-juice-nutrition.jpg"
    )

    assert product["ingredients_he"] == "תפוחים 100%"
    assert product["ingredients_en"] == "100% apples"
    assert product["description_he"] == "מיץ תפוחים טבעי ללא תוספת סוכר"
    assert product["description_en"] == (
        "Natural apple juice with no added sugar"
    )

    assert product["nutrition_facts"] == {"energy": 46}
    assert product["nutrition_values"] == {"sugar": 10.3}


def test_parse_product_handles_missing_optional_fields():
    product = parse_product({"barcode": "7290000000000"})

    assert product["barcode"] == "7290000000000"
    assert product["name_he"] is None
    assert product["brand_id"] is None
    assert product["category_ids"] == []
    assert product["category_path_ids"] == []
    assert product["main_image_url"] is None
    assert product["images"] == []


def test_iter_products_reads_products_object(tmp_path, raw_product):
    path = tmp_path / "products.json"
    path.write_text(
        json.dumps({"total": 1, "products": [raw_product]}),
        encoding="utf-8",
    )

    products = list(iter_products(path))

    assert len(products) == 1
    assert products[0]["barcode"] == "7291234567890"


def test_iter_products_reads_top_level_list(tmp_path, raw_product):
    path = tmp_path / "products.json"
    path.write_text(json.dumps([raw_product]), encoding="utf-8")

    products = list(iter_products(path))

    assert len(products) == 1
    assert products[0]["product_id"] == 456789


def test_iter_products_skips_non_dictionary_entries(tmp_path, raw_product, caplog):
    path = tmp_path / "products.json"
    path.write_text(
        json.dumps({"products": [raw_product, None, "invalid", 123]}),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        products = list(iter_products(path))

    assert len(products) == 1
    assert "skipped non-dict product entry" in caplog.text


def test_iter_products_rejects_invalid_structure(tmp_path):
    path = tmp_path / "products.json"
    path.write_text(json.dumps({"items": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="no 'products' list"):
        list(iter_products(path))