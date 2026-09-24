from datetime import date
from pathlib import Path

import pytest

from downloaders.full_family import (
    extract_time_suffix,
    find_latest_full_files_per_store,
    get_storage_path,
    _cleanup_old_same_day_files,
    save_full_file,
    save_full_file_async,
)


def test_extract_time_suffix_yyyymmdd_hhmmss():
    assert (
        extract_time_suffix(
            "PriceFull7290661400001-001-001-20260923-123456.gz"
        )
        == "123456"
    )


def test_extract_time_suffix_yyyymmdd_hhmm():
    assert (
        extract_time_suffix(
            "PriceFull7290661400001-001-001-20260923-1234.gz"
        )
        == "123400"
    )


def test_extract_time_suffix_yyyymmddhhmm():
    assert (
        extract_time_suffix(
            "PriceFull7290661400001-001-001-202609231234.gz"
        )
        == "123400"
    )


def test_extract_time_suffix_three_digit_time():
    assert (
        extract_time_suffix(
            "PriceFull7290661400001-001-001-20260923-123.gz"
        )
        == "123000"
    )


def test_extract_time_suffix_invalid_returns_zero():
    assert extract_time_suffix("invalid.xml") == "000000"


def test_find_latest_full_files_per_store(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.full_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": (
                "PriceFull7290661400001-001-001-"
                "20260923-100000.gz"
            ),
        },
        {
            "name": (
                "PriceFull7290661400001-001-001-"
                "20260923-120000.gz"
            ),
        },
        {
            "name": (
                "PriceFull7290661400001-001-002-"
                "20260923-110000.gz"
            ),
        },
    ]

    result = find_latest_full_files_per_store(
        files,
        "PriceFull",
        "name",
    )

    assert len(result) == 2

    assert result[
        ("7290661400001", "001")
    ]["filename"].endswith("120000.gz")

    assert result[
        ("7290661400001", "002")
    ]["filename"].endswith("110000.gz")


def test_find_latest_full_files_ignores_wrong_type(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.full_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": (
                "PromoFull7290661400001-001-001-"
                "20260923-120000.gz"
            ),
        },
    ]

    result = find_latest_full_files_per_store(
        files,
        "PriceFull",
        "name",
    )

    assert result == {}


def test_find_latest_full_files_ignores_old_date(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.full_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": (
                "PriceFull7290661400001-001-001-"
                "20260922-120000.gz"
            ),
        },
    ]

    result = find_latest_full_files_per_store(
        files,
        "PriceFull",
        "name",
    )

    assert result == {}


def test_find_latest_full_files_ignores_invalid_filename():
    result = find_latest_full_files_per_store(
        [{"name": "invalid.xml"}],
        "PriceFull",
        "name",
    )

    assert result == {}


def test_find_latest_full_files_with_date_key(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.full_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": (
                "PriceFull7290661400001-001-001-"
                "20260923-100000.gz"
            ),
            "published": "23/09/2026 10:00",
        },
        {
            "name": (
                "PriceFull7290661400001-001-001-"
                "20260923-110000.gz"
            ),
            "published": "23/09/2026 11:00",
        },
    ]

    result = find_latest_full_files_per_store(
        files,
        "PriceFull",
        "name",
        date_key="published",
        date_format="%d/%m/%Y %H:%M",
    )

    assert (
        result[
            ("7290661400001", "001")
        ]["filename"].endswith("110000.gz")
    )


def test_find_latest_full_files_ignores_invalid_date_key(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.full_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": (
                "PriceFull7290661400001-001-001-"
                "20260923-120000.gz"
            ),
            "published": "not-a-date",
        },
    ]

    result = find_latest_full_files_per_store(
        files,
        "PriceFull",
        "name",
        date_key="published",
        date_format="%d/%m/%Y %H:%M",
    )

    assert result == {}


def test_get_storage_path():
    result = get_storage_path(
        "7290661400001",
        "041",
        Path("/data/feeds"),
        "pricesfull",
    )

    assert result == Path(
        "/data/feeds/7290661400001/41/pricesfull"
    )


def test_cleanup_old_same_day_files(tmp_path):
    keep = (
        "PriceFull7290661400001-001-001-"
        "20260923-120000.gz"
    )
    old = (
        "PriceFull7290661400001-001-001-"
        "20260923-100000.gz"
    )
    different_day = (
        "PriceFull7290661400001-001-001-"
        "20260922-090000.gz"
    )

    for filename in [keep, old, different_day]:
        (tmp_path / filename).write_bytes(b"data")

    _cleanup_old_same_day_files(
        tmp_path,
        keep,
        date(2026, 9, 23),
        "PriceFull",
    )

    assert (tmp_path / keep).exists()
    assert not (tmp_path / old).exists()
    assert (tmp_path / different_day).exists()


def test_cleanup_ignores_other_file_types(tmp_path):
    price = (
        "PriceFull7290661400001-001-001-"
        "20260923-100000.gz"
    )
    promo = (
        "PromoFull7290661400001-001-001-"
        "20260923-100000.gz"
    )

    (tmp_path / price).write_bytes(b"data")
    (tmp_path / promo).write_bytes(b"data")

    _cleanup_old_same_day_files(
        tmp_path,
        "PriceFull7290661400001-001-001-20260923-120000.gz",
        date(2026, 9, 23),
        "PriceFull",
    )

    assert not (tmp_path / price).exists()
    assert (tmp_path / promo).exists()


def test_save_full_file(monkeypatch, tmp_path):
    expected_folder = (
        tmp_path / "CHAIN" / "41" / "pricesfull"
    )

    called = {}

    def fake_save_file(
        folder,
        filename,
        test,
        fetch_content,
        cleanup=None,
    ):
        called["folder"] = folder
        called["filename"] = filename
        called["test"] = test
        called["fetch_content"] = fetch_content
        called["cleanup"] = cleanup
        return folder / filename

    monkeypatch.setattr(
        "downloaders.full_family.save_file",
        fake_save_file,
    )

    fetch_content = lambda: b"data"

    result = save_full_file(
        "CHAIN",
        "041",
        "PriceFull.xml",
        date(2026, 9, 23),
        tmp_path,
        False,
        fetch_content,
        "PriceFull",
        "pricesfull",
    )

    assert result == expected_folder / "PriceFull.xml"
    assert called["folder"] == expected_folder
    assert called["filename"] == "PriceFull.xml"
    assert called["test"] is False
    assert called["fetch_content"] is fetch_content
    assert called["cleanup"] is not None


@pytest.mark.asyncio
async def test_save_full_file_async(monkeypatch, tmp_path):
    expected_folder = (
        tmp_path / "CHAIN" / "41" / "promosfull"
    )

    called = {}

    async def fake_save_file_async(
        folder,
        filename,
        test,
        fetch_content,
        cleanup=None,
    ):
        called["folder"] = folder
        called["filename"] = filename
        called["test"] = test
        called["fetch_content"] = fetch_content
        called["cleanup"] = cleanup
        return folder / filename

    monkeypatch.setattr(
        "downloaders.full_family.save_file_async",
        fake_save_file_async,
    )

    async def fetch_content():
        return b"data"

    result = await save_full_file_async(
        "CHAIN",
        "041",
        "PromoFull.xml",
        date(2026, 9, 23),
        tmp_path,
        True,
        fetch_content,
        "PromoFull",
        "promosfull",
    )

    assert result == expected_folder / "PromoFull.xml"
    assert called["folder"] == expected_folder
    assert called["filename"] == "PromoFull.xml"
    assert called["test"] is True
    assert called["fetch_content"] is fetch_content
    assert called["cleanup"] is not None