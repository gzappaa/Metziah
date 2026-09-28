from datetime import date
from pathlib import Path

import pytest

from downloaders.delta_family import (
    find_delta_files,
    keep_latest_file_per_store,
    get_storage_path,
    save_delta_file,
    save_delta_file_async,
)


def test_find_delta_files_returns_matching_files(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.delta_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": "Price7290661400001-001-001-20260923-120000.xml",
            "extra": "value",
        },
        {
            "name": "Promo7290661400001-001-001-20260923-130000.xml",
        },
    ]

    result = find_delta_files(
        files,
        "Price",
        "name",
    )

    assert len(result) == 1
    assert result[0]["name"] == files[0]["name"]
    assert result[0]["filename"] == files[0]["name"]
    assert result[0]["file_date"] == today


def test_find_delta_files_ignores_wrong_file_type(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.delta_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": "Promo7290661400001-001-001-20260923-120000.xml",
        },
    ]

    result = find_delta_files(files, "Price", "name")

    assert result == []


def test_find_delta_files_ignores_old_files(monkeypatch):
    today = date(2026, 9, 23)

    monkeypatch.setattr(
        "downloaders.delta_family.date",
        type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }),
    )

    files = [
        {
            "name": "Price7290661400001-001-001-20260922-120000.xml",
        },
    ]

    result = find_delta_files(files, "Price", "name")

    assert result == []


def test_find_delta_files_ignores_invalid_filename():
    files = [
        {"name": "not-a-valid-file.xml"},
        {"name": ""},
        {},
    ]

    result = find_delta_files(files, "Price", "name")

    assert result == []



def test_keep_latest_file_per_store():
    files = [
        {
            "chain_id": "7290661400001",
            "store_id": "1",
            "filename": "Price7290661400001-001-001-20260923-100000.xml",
        },
        {
            "chain_id": "7290661400001",
            "store_id": "1",
            "filename": "Price7290661400001-001-001-20260923-120000.xml",
        },
        {
            "chain_id": "7290661400001",
            "store_id": "2",
            "filename": "Price7290661400001-001-001-20260923-110000.xml",
        },
    ]

    result = keep_latest_file_per_store(files)

    assert len(result) == 2
    assert any(
        file["filename"].endswith("120000.xml")
        for file in result
    )
    assert any(
        file["filename"].endswith("110000.xml")
        for file in result
    )


def test_keep_latest_file_per_store_separates_chains():
    files = [
        {
            "chain_id": "CHAIN_A",
            "store_id": "1",
            "filename": "Price7290661400001-001-001-20260923-100000.xml",
        },
        {
            "chain_id": "CHAIN_B",
            "store_id": "1",
            "filename": "Price7290661400001-001-001-20260923-120000.xml",
        },
    ]

    result = keep_latest_file_per_store(files)

    assert len(result) == 2


def test_get_storage_path():
    result = get_storage_path(
        "7290661400001",
        "041",
        Path("/data/feeds"),
        "prices",
    )

    assert result == Path(
        "/data/feeds/7290661400001/41/prices"
    )


def test_save_delta_file(monkeypatch, tmp_path):
    expected_folder = tmp_path / "CHAIN" / "41" / "prices"

    called = {}

    def fake_save_file(
        folder,
        filename,
        test,
        fetch_content,
    ):
        called["folder"] = folder
        called["filename"] = filename
        called["test"] = test
        called["fetch_content"] = fetch_content
        return expected_folder / filename

    monkeypatch.setattr(
        "downloaders.delta_family.save_file",
        fake_save_file,
    )

    fetch_content = lambda: b"data"

    result = save_delta_file(
        "CHAIN",
        "041",
        "Price.xml",
        date(2026, 9, 23),
        tmp_path,
        True,
        fetch_content,
        "prices",
    )

    assert result == expected_folder / "Price.xml"
    assert called["folder"] == expected_folder
    assert called["filename"] == "Price.xml"
    assert called["test"] is True
    assert called["fetch_content"] is fetch_content


@pytest.mark.asyncio
async def test_save_delta_file_async(monkeypatch, tmp_path):
    expected_folder = tmp_path / "CHAIN" / "41" / "promos"

    called = {}

    async def fake_save_file_async(
        folder,
        filename,
        test,
        fetch_content,
    ):
        called["folder"] = folder
        called["filename"] = filename
        called["test"] = test
        called["fetch_content"] = fetch_content
        return expected_folder / filename

    monkeypatch.setattr(
        "downloaders.delta_family.save_file_async",
        fake_save_file_async,
    )

    async def fetch_content():
        return b"data"

    result = await save_delta_file_async(
        "CHAIN",
        "041",
        "Promo.xml",
        date(2026, 9, 23),
        tmp_path,
        False,
        fetch_content,
        "promos",
    )

    assert result == expected_folder / "Promo.xml"
    assert called["folder"] == expected_folder
    assert called["filename"] == "Promo.xml"
    assert called["test"] is False
    assert called["fetch_content"] is fetch_content