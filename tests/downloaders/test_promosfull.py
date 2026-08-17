# tests/downloaders/test_promosfull.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from downloaders import promosfull


# ---- parse_filename: pure regex logic ----

def test_parse_filename_valid():
    meta = promosfull.parse_filename(
        "PromoFull7290661400001-001-020-20260801-042307.gz"
    )
    assert meta == {
        "chain": "7290661400001",
        "subchain": "001",
        "store": "020",
        "date": "20260801",
        "time": "042307",
    }


def test_parse_filename_invalid_returns_none():
    assert promosfull.parse_filename("NotAMatch.gz") is None


def test_parse_filename_wrong_prefix_returns_none():
    # PriceFull, not PromoFull — should not match
    assert promosfull.parse_filename(
        "PriceFull7290661400001-001-020-20260801-042307.gz"
    ) is None


def test_parse_filename_rejects_trailing_content():
    assert promosfull.parse_filename(
        "PromoFull7290661400001-001-020-20260801-042307.gz.bak"
    ) is None


# ---- get_storage_path: pure, but depends on module-level DATA_DIR ----

def test_get_storage_path(monkeypatch, tmp_path):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)

    meta = {"chain": "7290661400001", "subchain": "001", "store": "020"}
    path = promosfull.get_storage_path(meta)

    assert path == tmp_path / "7290661400001" / "001" / "020" / "promosfull"


# ---- download_promofull: needs client mocked + filesystem isolated ----

def make_file_entry(store, date, time_):
    return {
        "fileName": f"PromoFull7290661400001-001-{store}-{date}-{time_}.gz"
    }


@pytest.fixture
def mock_client_class(monkeypatch):
    """
    download_promofull() instantiates LaibcatalogClient itself, so we
    monkeypatch the class in the module namespace and hand back the
    instance it will produce, pre-wired with AsyncMock methods.
    """
    instance = MagicMock()
    instance.get_files = AsyncMock()
    instance.build_download_url = MagicMock(
        side_effect=lambda filename: f"https://fake/{filename}"
    )
    instance.download_file = AsyncMock(return_value=b"fake gz bytes")

    client_class = MagicMock(return_value=instance)
    monkeypatch.setattr(promosfull, "LaibcatalogClient", client_class)

    return instance


@pytest.mark.asyncio
async def test_downloads_new_file(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
    ]

    await promosfull.download_promofull()

    dest = (
        tmp_path / "7290661400001" / "001" / "020" / "promosfull"
        / "PromoFull7290661400001-001-020-20260801-042307.gz"
    )
    assert dest.exists()
    assert dest.read_bytes() == b"fake gz bytes"


@pytest.mark.asyncio
async def test_skips_already_downloaded_file(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "promosfull"
    folder.mkdir(parents=True)
    existing = folder / "PromoFull7290661400001-001-020-20260801-042307.gz"
    existing.write_bytes(b"already here")

    await promosfull.download_promofull()

    # File wasn't re-downloaded, content untouched
    assert existing.read_bytes() == b"already here"
    mock_client_class.download_file.assert_not_called()


@pytest.mark.asyncio
async def test_keeps_only_latest_per_store_per_day(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("020", "20260801", "090000"),  # latest
        make_file_entry("020", "20260801", "050000"),
    ]

    await promosfull.download_promofull()

    folder = tmp_path / "7290661400001" / "001" / "020" / "promosfull"
    remaining = list(folder.glob("PromoFull*.gz"))

    assert len(remaining) == 1
    assert "090000" in remaining[0].name


@pytest.mark.asyncio
async def test_removes_older_same_day_file_when_newer_downloaded(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "promosfull"
    folder.mkdir(parents=True)
    old_file = folder / "PromoFull7290661400001-001-020-20260801-040000.gz"
    old_file.write_bytes(b"stale")

    await promosfull.download_promofull()

    assert not old_file.exists()
    new_file = folder / "PromoFull7290661400001-001-020-20260801-090000.gz"
    assert new_file.exists()


@pytest.mark.asyncio
async def test_ignores_unmatched_filenames(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        {"fileName": "PromoFull_totally_wrong_format.gz"},
    ]

    await promosfull.download_promofull()

    # Nothing should have been written anywhere
    assert list(tmp_path.rglob("*.gz")) == []


@pytest.mark.asyncio
async def test_ignores_non_promofull_files(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
        {"fileName": "PriceFull7290661400001-001-020-20260801-042307.gz"},
    ]

    await promosfull.download_promofull()

    all_gz = list(tmp_path.rglob("*.gz"))
    assert len(all_gz) == 1
    assert "PromoFull" in all_gz[0].name



@pytest.mark.asyncio
async def test_dedup_is_per_store_not_global(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("020", "20260801", "090000"),  # 020 latest
        make_file_entry("021", "20260801", "050000"),
        make_file_entry("021", "20260801", "060000"),  # 021 latest
        make_file_entry("022", "20260801", "070000"),  # 022 only one
    ]

    await promosfull.download_promofull()

    for store, expected_time in [("020", "090000"), ("021", "060000"), ("022", "070000")]:
        folder = tmp_path / "7290661400001" / "001" / store / "promosfull"
        remaining = list(folder.glob("PromoFull*.gz"))
        assert len(remaining) == 1
        assert expected_time in remaining[0].name


@pytest.mark.asyncio
async def test_download_failure_does_not_block_remaining_files(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
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

    await promosfull.download_promofull()

    assert (tmp_path / "7290661400001" / "001" / "020" / "promosfull"
            / "PromoFull7290661400001-001-020-20260801-042307.gz").exists()
    assert not (tmp_path / "7290661400001" / "001" / "021" / "promosfull"
                / "PromoFull7290661400001-001-021-20260801-042307.gz").exists()
    assert (tmp_path / "7290661400001" / "001" / "022" / "promosfull"
            / "PromoFull7290661400001-001-022-20260801-042307.gz").exists()


@pytest.mark.asyncio
async def test_old_same_day_file_preserved_when_download_fails(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]
    mock_client_class.download_file.side_effect = Exception("boom")

    folder = tmp_path / "7290661400001" / "001" / "020" / "promosfull"
    folder.mkdir(parents=True)
    old_file = folder / "PromoFull7290661400001-001-020-20260801-040000.gz"
    old_file.write_bytes(b"still valid")

    await promosfull.download_promofull()

    assert old_file.exists()
    assert old_file.read_bytes() == b"still valid"


@pytest.mark.asyncio
async def test_get_files_failure_returns_early(monkeypatch, tmp_path, mock_client_class):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.side_effect = Exception("api down")

    await promosfull.download_promofull()

    assert list(tmp_path.rglob("*.gz")) == []


@pytest.mark.asyncio
async def test_previous_day_file_not_removed_by_same_day_cleanup(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)
    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "090000"),
    ]

    folder = tmp_path / "7290661400001" / "001" / "020" / "promosfull"
    folder.mkdir(parents=True)
    yesterday_file = folder / "PromoFull7290661400001-001-020-20260731-230000.gz"
    yesterday_file.write_bytes(b"yesterday")

    await promosfull.download_promofull()

    assert yesterday_file.exists()


@pytest.mark.asyncio
async def test_test_mode_keeps_only_existing_test_stores(
    monkeypatch, tmp_path, mock_client_class
):
    test_feeds_dir = tmp_path / "data" / "test_feeds"

    # Existing test stores: 020 and 021
    (test_feeds_dir / "7290661400001" / "001" / "020").mkdir(parents=True)
    (test_feeds_dir / "7290661400001" / "001" / "021").mkdir(parents=True)

    monkeypatch.setattr(promosfull, "BASE_DIR", tmp_path)

    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
        make_file_entry("021", "20260801", "042307"),
        make_file_entry("022", "20260801", "042307"),
        make_file_entry("023", "20260801", "042307"),
    ]

    downloaded = await promosfull.download_promofull(test=True)

    assert len(downloaded) == 2

    files = list(test_feeds_dir.rglob("PromoFull*.gz"))

    assert len(files) == 2
    assert sorted(path.parts[-3] for path in files) == ["020", "021"]


@pytest.mark.asyncio
async def test_test_mode_uses_store_directories_regardless_of_feed_type(
    monkeypatch, tmp_path, mock_client_class
):
    test_feeds_dir = tmp_path / "data" / "test_feeds"

    # Store exists because it has a prices directory.
    store_dir = (
        test_feeds_dir
        / "7290661400001"
        / "001"
        / "058"
    )
    (store_dir / "prices").mkdir(parents=True)

    monkeypatch.setattr(promosfull, "BASE_DIR", tmp_path)

    mock_client_class.get_files.return_value = [
        make_file_entry("058", "20260801", "042307"),
        make_file_entry("059", "20260801", "042307"),
    ]

    await promosfull.download_promofull(test=True)

    assert (
        test_feeds_dir
        / "7290661400001"
        / "001"
        / "058"
        / "promosfull"
        / "PromoFull7290661400001-001-058-20260801-042307.gz"
    ).exists()

    assert not (
        test_feeds_dir
        / "7290661400001"
        / "001"
        / "059"
        / "promosfull"
    ).exists()

@pytest.mark.asyncio
async def test_returns_downloaded_paths(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promosfull, "DATA_DIR", tmp_path)

    filename = "PromoFull7290661400001-001-020-20260801-042307.gz"

    mock_client_class.get_files.return_value = [
        {"fileName": filename},
    ]

    result = await promosfull.download_promofull()

    expected = (
        tmp_path
        / "7290661400001"
        / "001"
        / "020"
        / "promosfull"
        / filename
    )

    assert result == [expected]