import pytest

from utils.products.load_products_enriched import (
    get_item_code,
    normalize_category_path,
)


def test_get_item_code_normalizes_barcode():
    assert get_item_code({"barcode": " 7290012345678 "}) == "7290012345678"


@pytest.mark.parametrize(
    "barcode",
    [None, "", "   "],
)
def test_get_item_code_returns_none_for_missing_barcode(barcode):
    assert get_item_code({"barcode": barcode}) is None


def test_normalize_category_path_maps_known_category():
    mapping = {
        "ירקות ופירות / ירקות": ("ירקות ופירות", "ירקות"),
    }

    assert normalize_category_path(
        ["ירקות ופירות", "ירקות"],
        mapping,
    ) == ("ירקות ופירות", "ירקות")


@pytest.mark.parametrize(
    "category_path",
    [None, [], ["ירקות ופירות"], "ירקות ופירות / ירקות"],
)
def test_normalize_category_path_returns_none_for_invalid_path(category_path):
    assert normalize_category_path(category_path, {}) == (None, None)


def test_normalize_category_path_returns_none_for_unmapped_category():
    assert normalize_category_path(
        ["קטגוריה לא מוכרת", "תת קטגוריה"],
        {},
    ) == (None, None)