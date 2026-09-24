import json
from datetime import date
from pathlib import Path

import pytest

from utils.file_tracking.parser_file_tracking import (
    FEEDS_DIR,
    extract_time_suffix,
    get_local_path,
    normalize_file,
    parse_filename,
)

BASE_DIR = Path(__file__).resolve().parents[3]

PATTERNS_FILE = (
    BASE_DIR
    / "monitoring"
    / "data"
    / "filename_patterns.json"
)


def load_filename_examples():
    with PATTERNS_FILE.open(encoding="utf-8") as f:
        data = json.load(f)

    examples = []

    for structure in data["structures"]:
        examples.extend(structure["examples"])

    return examples


@pytest.mark.parametrize(
    "filename",
    load_filename_examples(),
)
def test_parse_real_filename_examples(filename):
    result = parse_filename(filename)

    assert result["filename"] == filename
    assert result["chain_id"].isdigit()
    assert len(result["chain_id"]) == 13
    assert result["file_type"] in {
        "Price",
        "PriceFull",
        "Promo",
        "PromoFull",
        "Stores",
    }
    assert result["file_date"] is not None


@pytest.mark.parametrize(
    "filename",
    [
        "invalid.xml",
        "Price-7290058140886-001-001-20260924-070011.gz",
        "Price7290058140886-20260924.gz",
        "Price7290058140886-001-001-20261301-070011.gz",
        "Unknown7290058140886-001-001-20260924-070011.gz",
        "Price123-001-001-20260924-070011.gz",
    ],
)
def test_parse_filename_invalid(filename):
    with pytest.raises(ValueError):
        parse_filename(filename)


@pytest.mark.parametrize(
    "file_type, directory",
    [
        ("Price", "prices"),
        ("PriceFull", "pricesfull"),
        ("Promo", "promos"),
        ("PromoFull", "promosfull"),
    ],
)
def test_get_local_path(file_type, directory):
    filename = (
        f"{file_type}7290058140886-001-001-20260924-070011.gz"
    )

    record = parse_filename(filename)

    assert get_local_path(record) == (
        FEEDS_DIR
        / "7290058140886"
        / "001"
        / directory
        / filename
    )


def test_get_local_path_stores():
    filename = "StoresFull7290058140886-20260924-070011.gz"

    record = parse_filename(filename)

    assert get_local_path(record) == (
        FEEDS_DIR
        / "7290058140886"
        / "stores"
        / filename
    )


def test_normalize_file_invalid_filename():
    assert normalize_file("invalid.xml") is None


def test_normalize_file_old_date():
    filename = "Price7290058140886-001-001-20260923-070011.gz"

    assert normalize_file(filename, file_size=123) is None


def test_normalize_file_today(monkeypatch, tmp_path):
    today = date.today().strftime("%Y%m%d")

    filename = (
        f"Price7290058140886-001-001-{today}-070011.gz"
    )

    monkeypatch.setattr(
        "utils.file_tracking.parser_file_tracking.FEEDS_DIR",
        tmp_path,
    )

    file_path = (
        tmp_path
        / "7290058140886"
        / "001"
        / "prices"
        / filename
    )

    file_path.parent.mkdir(parents=True)
    file_path.touch()

    result = normalize_file(filename, file_size=123)

    assert result["file_size"] == 123
    assert result["downloaded"] is True


@pytest.mark.parametrize(
    "filename, expected",
    [
        (
            "Price7290058140886-001-001-20260924-070011.gz",
            "070011",
        ),
        (
            "Price7290058140886-001-001-20260924-0700.gz",
            "070000",
        ),
        (
            "Price7290058140886-001-001-20260924-070.gz",
            "070000",
        ),
        (
            "Price7290058140886-001-001-20260924-07.gz",
            "070000",
        ),
        (
            "Price7290058140886-001-001-20260924.gz",
            "000000",
        ),
        (
            "invalid.xml",
            "000000",
        ),
    ],
)
def test_extract_time_suffix(filename, expected):
    assert extract_time_suffix(filename) == expected
