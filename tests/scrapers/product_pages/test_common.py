
from scrapers.product_pages.common import add_field, clean, split_list, unique


# ============================================================
# clean
# ============================================================

def test_clean_collapses_whitespace():
    assert clean("  milk   chocolate \n\t  100g  ") == "milk chocolate 100g"


def test_clean_handles_empty_string():
    assert clean("") == ""


def test_clean_handles_whitespace_only():
    assert clean("  \n\t ") == ""


def test_clean_preserves_text():
    assert clean("Milk 2%") == "Milk 2%"


# ============================================================
# split_list
# ============================================================

def test_split_list_splits_commas():
    assert split_list("milk, bread, eggs") == ["milk", "bread", "eggs"]


def test_split_list_splits_newlines():
    assert split_list("milk\nbread\neggs") == ["milk", "bread", "eggs"]


def test_split_list_cleans_whitespace():
    assert split_list("  milk  , \n bread  , eggs  ") == [
        "milk",
        "bread",
        "eggs",
    ]


def test_split_list_removes_empty_items():
    assert split_list("milk,,\nbread, ,eggs") == [
        "milk",
        "bread",
        "eggs",
    ]


def test_split_list_handles_empty_string():
    assert split_list("") == []


def test_split_list_handles_single_item():
    assert split_list("milk") == ["milk"]

def test_split_list_splits_html_breaks():
    assert split_list("milk<br>bread<br/>eggs") == [
        "milk",
        "bread",
        "eggs",
    ]


# ============================================================
# unique
# ============================================================

def test_unique_removes_duplicates():
    assert unique(["milk", "bread", "milk", "eggs"]) == [
        "milk",
        "bread",
        "eggs",
    ]


def test_unique_preserves_order():
    assert unique(["b", "a", "c", "a", "b"]) == ["b", "a", "c"]


def test_unique_removes_falsy_values():
    assert unique(["milk", None, "", "bread", None, ""]) == [
        "milk",
        "bread",
    ]


def test_unique_handles_empty_list():
    assert unique([]) == []


def test_unique_handles_all_falsy_values():
    assert unique([None, "", None, ""]) == []


# ============================================================
# add_field
# ============================================================

def test_add_field_creates_new_label():
    fields = {}

    add_field(fields, "Brand", "Example")

    assert fields == {"Brand": ["Example"]}


def test_add_field_appends_repeated_labels():
    fields = {}

    add_field(fields, "Kashrut", "First certification")
    add_field(fields, "Kashrut", "Second certification")

    assert fields == {
        "Kashrut": [
            "First certification",
            "Second certification",
        ]
    }


def test_add_field_preserves_other_labels():
    fields = {"Brand": ["Example"]}

    add_field(fields, "Weight", "500 g")
    add_field(fields, "Brand", "Another brand")

    assert fields == {
        "Brand": ["Example", "Another brand"],
        "Weight": ["500 g"],
    }


def test_add_field_ignores_empty_label():
    fields = {}

    add_field(fields, "", "Example")

    assert fields == {}


def test_add_field_ignores_empty_value():
    fields = {}

    add_field(fields, "Brand", "")

    assert fields == {}


def test_add_field_ignores_none_label_or_value():
    fields = {}

    add_field(fields, None, "Example")
    add_field(fields, "Brand", None)

    assert fields == {}
