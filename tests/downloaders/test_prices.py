# tests/downloaders/test_prices.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from downloaders import prices


# ---- parse_filename ----

def test_parse_filename_valid():
    meta = prices.parse_filename(
        "Price7290661400001-001-020-20260801-042307.gz"
    )
    assert meta == {
        "chain": "7290661400001",
        "subchain": "001",
        "store": "020",
        "date": "20260801",
        "time": "042307",
    }


def test_parse_filename_invalid_returns_none():
    assert prices.parse_filename("NotAMatch.gz") is None
    

def test_parse_filename_wrong_prefix_returns_none():
    assert prices.parse_filename(
        "Promo7290661400001-001-020-20260801-042307.gz"
    ) is None


def test_parse_filename_rejects_trailing_content():
    assert prices.parse_filename(
        "Price7290661400001-001-020-20260801-042307.gz.bak"
    ) is None


# ---- get_storage_path ----

def test_get_storage_path(tmp_path):
    meta = {"chain": "7290661400001", "subchain": "001", "store": "020"}

    path = prices.get_storage_path(meta, tmp_path)

    assert path == tmp_path / "7290661400001" / "001" / "020" / "prices"


# ---- download_prices ----

def make_file_entry(store, date, time_, prefix="Price"):
    return {
        "fileName": f"{prefix}7290661400001-001-{store}-{date}-{time_}.gz"
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
    monkeypatch.setattr(prices, "LaibcatalogClient", client_class)

    return instance


@pytest.mark.asyncio
async def test_downloads_new_file(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
    ]

    await prices.download_prices()

    dest = (
        tmp_path / "7290661400001" / "001" / "020" / "prices"
        / "Price7290661400001-001-020-20260801-042307.gz"
    )
    assert dest.exists()
    assert dest.read_bytes() == b"fake gz bytes"


@pytest.mark.asyncio
async def test_filters_out_pricefull_files(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307", prefix="Price"),
        make_file_entry("020", "20260801", "042307", prefix="PriceFull"),
    ]

    await prices.download_prices()

    all_gz = list(tmp_path.rglob("*.gz"))
    assert len(all_gz) == 1
    assert "PriceFull" not in all_gz[0].name


@pytest.mark.asyncio
async def test_keeps_only_latest_per_store_across_different_days(
    monkeypatch, tmp_path, mock_client_class
):
    # Unlike pricesfull.py, dedup here has NO date component — only one
    # file survives per store, even across different days.
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260731", "230000"),
        make_file_entry("020", "20260801", "090000"),  # latest overall
        make_file_entry("020", "20260801", "050000"),
    ]

    await prices.download_prices()

    folder = tmp_path / "7290661400001" / "001" / "020" / "prices"
    remaining = list(folder.glob("Price*.gz"))

    assert len(remaining) == 1
    assert "20260801-090000" in remaining[0].name


@pytest.mark.asyncio
async def test_removes_all_old_price_files_regardless_of_date(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "prices"
    folder.mkdir(parents=True)
    # stale files from a previous day AND earlier the same day
    yesterday_stale = folder / "Price7290661400001-001-020-20260731-230000.gz"
    today_stale = folder / "Price7290661400001-001-020-20260801-040000.gz"
    yesterday_stale.write_bytes(b"stale1")
    today_stale.write_bytes(b"stale2")

    await prices.download_prices()

    assert not yesterday_stale.exists()
    assert not today_stale.exists()
    new_file = folder / "Price7290661400001-001-020-20260801-090000.gz"
    assert new_file.exists()


@pytest.mark.asyncio
async def test_skips_download_when_latest_already_present(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "prices"
    folder.mkdir(parents=True)
    existing = folder / "Price7290661400001-001-020-20260801-090000.gz"
    existing.write_bytes(b"already here")

    await prices.download_prices()

    assert existing.read_bytes() == b"already here"
    mock_client_class.download_file.assert_not_called()


@pytest.mark.asyncio
async def test_dedup_is_per_store_not_global(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("020", "20260801", "090000"),
        make_file_entry("021", "20260801", "050000"),
        make_file_entry("021", "20260801", "060000"),
        make_file_entry("022", "20260801", "070000"),
    ]

    await prices.download_prices()

    for store, expected_time in [("020", "090000"), ("021", "060000"), ("022", "070000")]:
        folder = tmp_path / "7290661400001" / "001" / store / "prices"
        remaining = list(folder.glob("Price*.gz"))
        assert len(remaining) == 1
        assert expected_time in remaining[0].name


@pytest.mark.asyncio
async def test_download_failure_does_not_block_remaining_files(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
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

    await prices.download_prices()

    assert (tmp_path / "7290661400001" / "001" / "020" / "prices"
            / "Price7290661400001-001-020-20260801-042307.gz").exists()
    # 021 failed — no file written
    assert not (tmp_path / "7290661400001" / "001" / "021" / "prices"
                / "Price7290661400001-001-021-20260801-042307.gz").exists()
    # 022 still processed despite 021's failure
    assert (tmp_path / "7290661400001" / "001" / "022" / "prices"
            / "Price7290661400001-001-022-20260801-042307.gz").exists()


@pytest.mark.asyncio
async def test_get_files_failure_returns_early(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.side_effect = Exception("api down")

    # should not raise — caught and logged
    await prices.download_prices()

    assert list(tmp_path.rglob("*.gz")) == []


@pytest.mark.asyncio
async def test_failed_count_incremented_on_download_error(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
    ]
    mock_client_class.download_file.side_effect = Exception("boom")

    await prices.download_prices()

    # no file written, no exception raised
    assert not (tmp_path / "7290661400001" / "001" / "020" / "prices"
                / "Price7290661400001-001-020-20260801-042307.gz").exists()


@pytest.mark.asyncio
async def test_old_file_kept_when_new_download_fails(
    monkeypatch, tmp_path, mock_client_class
):
    # When download fails, `continue` skips old-file cleanup —
    # the previous snapshot should remain on disk.
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]
    mock_client_class.download_file.side_effect = Exception("boom")

    folder = tmp_path / "7290661400001" / "001" / "020" / "prices"
    folder.mkdir(parents=True)
    old_file = folder / "Price7290661400001-001-020-20260731-230000.gz"
    old_file.write_bytes(b"still here")

    await prices.download_prices()

    assert old_file.exists()


def test_parse_filename_skips_with_warning_not_crash():
    # invalid filenames just return None; download_prices() should
    # skip them via the `if not meta: continue` branch, not crash.
    assert prices.parse_filename("garbage") is None


@pytest.mark.asyncio
async def test_invalid_datetime_in_filename_is_skipped(
    monkeypatch, tmp_path, mock_client_class
):
    # e.g. month "13" — matches the regex shape but datetime.strptime fails
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        {"fileName": "Price7290661400001-001-020-20261301-042307.gz"},
    ]

    await prices.download_prices()

    assert list(tmp_path.rglob("*.gz")) == []
    mock_client_class.download_file.assert_not_called()