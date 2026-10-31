import pytest

from utils.processing.delete_suspicious_products import (
    DELETE_SEVERITIES,
    determine_severity,
    is_placeholder_name,
    normalize,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" Milk ", "Milk"),
        (123, "123"),
    ],
)
def test_normalize(value, expected):
    assert normalize(value) == expected


@pytest.mark.parametrize(
    "name",
    [
        "לא ידוע",
        "לא ידוע.",
        "UNKNOWN",
        "unk",
        "n/a",
        "NA",
        "none",
        "null",
        "לא זמין",
        "ללא שם",
    ],
)
def test_is_placeholder_name(name):
    assert is_placeholder_name(name)


@pytest.mark.parametrize(
    "name",
    [None, "", "Milk", "123", "Unknown product"],
)
def test_is_not_placeholder_name(name):
    assert not is_placeholder_name(name)


@pytest.mark.parametrize(
    ("conditions", "expected"),
    [
        (
            {
                "appear_once": True,
                "zero_price": True,
                "missing_name": True,
            },
            "delete",
        ),
        (
            {
                "appear_once": True,
                "zero_price": True,
                "missing_name": False,
            },
            "ultra_high",
        ),
        (
            {
                "all_prices_zero": True,
                "appear_once": False,
            },
            "very_high",
        ),
        (
            {
                "appear_once": True,
                "missing_name": True,
            },
            "high",
        ),
        (
            {"placeholder_name": True},
            "high",
        ),
        (
            {"missing_name": True},
            "medium",
        ),
        (
            {"only_null_prices": True},
            "medium",
        ),
        (
            {"short_name": True},
            "medium",
        ),
        (
            {"numeric_only_name": True},
            "medium",
        ),
        (
            {"completely_unused": True},
            "medium",
        ),
        ({}, None),
    ],
)
def test_determine_severity(conditions, expected):
    defaults = {
        "appear_once": False,
        "zero_price": False,
        "all_prices_zero": False,
        "missing_name": False,
        "placeholder_name": False,
        "completely_unused": False,
        "only_null_prices": False,
        "short_name": False,
        "numeric_only_name": False,
    }
    defaults.update(conditions)

    assert determine_severity(**defaults) == expected


def test_only_delete_and_ultra_high_are_deletion_severities():
    assert DELETE_SEVERITIES == {"delete", "ultra_high"}