# tests/downloaders/test_pricesfull.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from downloaders import pricesfull


# ---- parse_filename: pure regex logic ----

def test_parse_filename_valid():
    meta = pricesfull.parse_filename(
        "PriceFull7290661400001-001-020-20260801-042307.gz"
    )
    assert meta == {
        "chain": "7290661400001",
        "subchain": "001",
        "store": "020",
        "date": "20260801",
        "time": "042307",
    }


def test_parse_filename_invalid_returns_none():
    assert pricesfull.parse_filename("NotAMatch.gz") is None


def test_parse_filename_wrong_prefix_returns_none():
    # PromoFull, not PriceFull — should not match
    assert pricesfull.parse_filename(
        "PromoFull7290661400001-001-020-20260801-042307.gz"
    ) is None


def test_parse_filename_rejects_trailing_content():
    assert pricesfull.parse_filename(
        "PriceFull7290661400001-001-020-20260801-042307.gz.bak"
    ) is None


# ---- get_storage_path ----

def test_get_storage_path(monkeypatch, tmp_path):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)

    meta = {"chain": "7290661400001", "subchain": "001", "store": "020"}
    path = pricesfull.get_storage_path(meta)

    assert path == tmp_path / "7290661400001" / "001" / "020" / "pricesfull"


# ---- download_pricefull ----

def make_file_entry(store, date, time_):
    return {
        "fileName": f"PriceFull7290661400001-001-{store}-{date}-{time_}.gz"
    }


@pytest.fixture
def mock_client_class(monkeypatch):
    instance = MagicMock()
    instance.get_files = AsyncMock()
    instance.build_download_url = MagicMock(
        side_effect=lambda filename: f"https://fake/{filename}"
    )
    instance.download_file = AsyncMock(return_value=b"fake gz bytes")

    client_class = MagicMock(return_value=instance)
    monkeypatch.setattr(pricesfull, "LaibcatalogClient", client_class)

    return instance


@pytest.mark.asyncio
async def test_downloads_new_file(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
    ]

    await pricesfull.download_pricefull()

    dest = (
        tmp_path / "7290661400001" / "001" / "020" / "pricesfull"
        / "PriceFull7290661400001-001-020-20260801-042307.gz"
    )
    assert dest.exists()
    assert dest.read_bytes() == b"fake gz bytes"


@pytest.mark.asyncio
async def test_skips_already_downloaded_file(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "pricesfull"
    folder.mkdir(parents=True)
    existing = folder / "PriceFull7290661400001-001-020-20260801-042307.gz"
    existing.write_bytes(b"already here")

    await pricesfull.download_pricefull()

    assert existing.read_bytes() == b"already here"
    mock_client_class.download_file.assert_not_called()


@pytest.mark.asyncio
async def test_keeps_only_latest_per_store_per_day(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("020", "20260801", "090000"),
        make_file_entry("020", "20260801", "050000"),
    ]

    await pricesfull.download_pricefull()

    folder = tmp_path / "7290661400001" / "001" / "020" / "pricesfull"
    remaining = list(folder.glob("PriceFull*.gz"))

    assert len(remaining) == 1
    assert "090000" in remaining[0].name


@pytest.mark.asyncio
async def test_removes_older_same_day_file_when_newer_downloaded(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "pricesfull"
    folder.mkdir(parents=True)
    old_file = folder / "PriceFull7290661400001-001-020-20260801-040000.gz"
    old_file.write_bytes(b"stale")

    await pricesfull.download_pricefull()

    assert not old_file.exists()
    new_file = folder / "PriceFull7290661400001-001-020-20260801-090000.gz"
    assert new_file.exists()


@pytest.mark.asyncio
async def test_ignores_unmatched_filenames(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        {"fileName": "PriceFull_totally_wrong_format.gz"},
    ]

    await pricesfull.download_pricefull()

    assert list(tmp_path.rglob("*.gz")) == []


@pytest.mark.asyncio
async def test_ignores_non_pricefull_files(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
        {"fileName": "PromoFull7290661400001-001-020-20260801-042307.gz"},
    ]

    await pricesfull.download_pricefull()

    all_gz = list(tmp_path.rglob("*.gz"))
    assert len(all_gz) == 1
    assert "PriceFull" in all_gz[0].name


@pytest.mark.asyncio
async def test_dedup_is_per_store_not_global(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("020", "20260801", "090000"),
        make_file_entry("021", "20260801", "050000"),
        make_file_entry("021", "20260801", "060000"),
        make_file_entry("022", "20260801", "070000"),
    ]

    await pricesfull.download_pricefull()

    for store, expected_time in [("020", "090000"), ("021", "060000"), ("022", "070000")]:
        folder = tmp_path / "7290661400001" / "001" / store / "pricesfull"
        remaining = list(folder.glob("PriceFull*.gz"))
        assert len(remaining) == 1
        assert expected_time in remaining[0].name


@pytest.mark.asyncio
async def test_download_failure_does_not_block_remaining_files(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
        make_file_entry("021", "20260801", "042307"),
        make_file_entry("022", "20260801", "042307"),
    ]
    mock_client_class.download_file.side_effect = [
        b"ok bytes",
        Exception("boom"),
        b"ok bytes too",
    ]

    await pricesfull.download_pricefull()

    assert (tmp_path / "7290661400001" / "001" / "020" / "pricesfull"
            / "PriceFull7290661400001-001-020-20260801-042307.gz").exists()
    assert not (tmp_path / "7290661400001" / "001" / "021" / "pricesfull"
                / "PriceFull7290661400001-001-021-20260801-042307.gz").exists()
    assert (tmp_path / "7290661400001" / "001" / "022" / "pricesfull"
            / "PriceFull7290661400001-001-022-20260801-042307.gz").exists()


@pytest.mark.asyncio
async def test_old_same_day_file_preserved_when_download_fails(
    monkeypatch, tmp_path, mock_client_class
):
    # Regression test for the ordering bug: old file must NOT be deleted
    # if the new download fails.
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]
    mock_client_class.download_file.side_effect = Exception("boom")

    folder = tmp_path / "7290661400001" / "001" / "020" / "pricesfull"
    folder.mkdir(parents=True)
    old_file = folder / "PriceFull7290661400001-001-020-20260801-040000.gz"
    old_file.write_bytes(b"still valid")

    await pricesfull.download_pricefull()

    assert old_file.exists()
    assert old_file.read_bytes() == b"still valid"


@pytest.mark.asyncio
async def test_get_files_failure_returns_early(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.side_effect = Exception("api down")

    await pricesfull.download_pricefull()

    assert list(tmp_path.rglob("*.gz")) == []


@pytest.mark.asyncio
async def test_previous_day_file_not_removed_by_same_day_cleanup(
    monkeypatch, tmp_path, mock_client_class
):
    # Cleanup only targets same-day files; a prior day's PriceFull
    # should survive (it's the historical record, per your
    # valid_from/valid_to design).
    monkeypatch.setattr(pricesfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "pricesfull"
    folder.mkdir(parents=True)
    yesterday_file = folder / "PriceFull7290661400001-001-020-20260731-230000.gz"
    yesterday_file.write_bytes(b"yesterday")

    await pricesfull.download_pricefull()

    assert yesterday_file.exists()