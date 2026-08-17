from unittest.mock import AsyncMock, MagicMock

import pytest

from downloaders import promos


# ---- parse_filename: pure regex logic ----

def test_parse_filename_valid():
    meta = promos.parse_filename(
        "Promo7290661400001-001-020-20260801-042307.gz"
    )

    assert meta == {
        "chain": "7290661400001",
        "subchain": "001",
        "store": "020",
        "date": "20260801",
        "time": "042307",
    }


def test_parse_filename_invalid_returns_none():
    assert promos.parse_filename("NotAMatch.gz") is None


def test_parse_filename_rejects_promofull():
    assert promos.parse_filename(
        "PromoFull7290661400001-001-020-20260801-042307.gz"
    ) is None


def test_parse_filename_rejects_trailing_content():
    assert promos.parse_filename(
        "Promo7290661400001-001-020-20260801-042307.gz.bak"
    ) is None


# ---- get_storage_path ----

def test_get_storage_path(tmp_path):
    meta = {
        "chain": "7290661400001",
        "subchain": "001",
        "store": "020",
    }

    path = promos.get_storage_path(meta, tmp_path)

    assert path == (
        tmp_path
        / "7290661400001"
        / "001"
        / "020"
        / "promos"
    )


# ---- download_promos ----

def make_file_entry(store, date, time_):
    return {
        "fileName": (
            f"Promo7290661400001-001-{store}-{date}-{time_}.gz"
        )
    }


@pytest.fixture
def mock_client_class(monkeypatch):
    instance = MagicMock()
    instance.get_files = AsyncMock()
    instance.build_download_url = MagicMock(
        side_effect=lambda filename: f"https://fake/{filename}"
    )
    instance.download_file = AsyncMock(
        return_value=b"fake gz bytes"
    )

    client_class = MagicMock(return_value=instance)
    monkeypatch.setattr(
        promos,
        "LaibcatalogClient",
        client_class,
    )

    return instance


@pytest.mark.asyncio
async def test_downloads_new_file(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promos, "DATA_DIR", tmp_path)

    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
    ]

    result = await promos.download_promos()

    expected = (
        tmp_path
        / "7290661400001"
        / "001"
        / "020"
        / "promos"
        / "Promo7290661400001-001-020-20260801-042307.gz"
    )

    assert expected.exists()
    assert expected.read_bytes() == b"fake gz bytes"
    assert result == [expected]



@pytest.mark.asyncio
async def test_keeps_all_promo_files_without_deduplication(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promos, "DATA_DIR", tmp_path)

    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("020", "20260801", "050000"),
        make_file_entry("020", "20260801", "060000"),
    ]

    result = await promos.download_promos()

    folder = (
        tmp_path
        / "7290661400001"
        / "001"
        / "020"
        / "promos"
    )

    remaining = list(folder.glob("Promo*.gz"))

    assert len(remaining) == 3
    assert len(result) == 3


@pytest.mark.asyncio
async def test_ignores_promofull_files(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promos, "DATA_DIR", tmp_path)

    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "042307"),
        {
            "fileName": (
                "PromoFull7290661400001-001-020-20260801-042307.gz"
            )
        },
    ]

    await promos.download_promos()

    files = list(tmp_path.rglob("*.gz"))

    assert len(files) == 1
    assert files[0].name.startswith("Promo729")


@pytest.mark.asyncio
async def test_skips_existing_file(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promos, "DATA_DIR", tmp_path)

    filename = "Promo7290661400001-001-020-20260801-042307.gz"

    mock_client_class.get_files.return_value = [
        {"fileName": filename},
    ]

    folder = (
        tmp_path
        / "7290661400001"
        / "001"
        / "020"
        / "promos"
    )
    folder.mkdir(parents=True)

    existing = folder / filename
    existing.write_bytes(b"original")

    result = await promos.download_promos()

    assert existing.read_bytes() == b"original"
    assert result == []
    mock_client_class.download_file.assert_not_called()


@pytest.mark.asyncio
async def test_download_failure_does_not_block_remaining_files(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promos, "DATA_DIR", tmp_path)

    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("021", "20260801", "050000"),
        make_file_entry("022", "20260801", "060000"),
    ]

    mock_client_class.download_file.side_effect = [
        b"first",
        Exception("boom"),
        b"third",
    ]

    result = await promos.download_promos()

    assert len(result) == 2

    assert (
        tmp_path
        / "7290661400001"
        / "001"
        / "020"
        / "promos"
        / "Promo7290661400001-001-020-20260801-040000.gz"
    ).exists()

    assert not (
        tmp_path
        / "7290661400001"
        / "001"
        / "021"
        / "promos"
        / "Promo7290661400001-001-021-20260801-050000.gz"
    ).exists()

    assert (
        tmp_path
        / "7290661400001"
        / "001"
        / "022"
        / "promos"
        / "Promo7290661400001-001-022-20260801-060000.gz"
    ).exists()


@pytest.mark.asyncio
async def test_get_files_failure_returns_empty(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promos, "DATA_DIR", tmp_path)

    mock_client_class.get_files.side_effect = Exception("api down")

    result = await promos.download_promos()

    assert result == []
    assert list(tmp_path.rglob("*.gz")) == []


@pytest.mark.asyncio
async def test_ignores_invalid_promo_filename(
    monkeypatch, tmp_path, mock_client_class
):
    monkeypatch.setattr(promos, "DATA_DIR", tmp_path)

    mock_client_class.get_files.return_value = [
        {"fileName": "Promo_totally_wrong_format.gz"},
    ]

    result = await promos.download_promos()

    assert result == []
    assert list(tmp_path.rglob("*.gz")) == []


@pytest.mark.asyncio
async def test_test_mode_keeps_only_existing_test_stores(
    monkeypatch, tmp_path, mock_client_class
):
    test_feeds_dir = tmp_path / "data" / "test_feeds"

    (
        test_feeds_dir
        / "7290661400001"
        / "001"
        / "020"
    ).mkdir(parents=True)

    (
        test_feeds_dir
        / "7290661400001"
        / "001"
        / "021"
    ).mkdir(parents=True)

    monkeypatch.setattr(promos, "BASE_DIR", tmp_path)
    monkeypatch.setattr(promos, "TEST_DATA_DIR", test_feeds_dir)

    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260801", "040000"),
        make_file_entry("021", "20260801", "050000"),
        make_file_entry("022", "20260801", "060000"),
    ]

    result = await promos.download_promos(test=True)

    assert len(result) == 2

    files = list(test_feeds_dir.rglob("Promo*.gz"))

    assert len(files) == 2
    assert sorted(path.parts[-3] for path in files) == [
        "020",
        "021",
    ]

@pytest.mark.asyncio
async def test_test_mode_keeps_all_promo_files_for_existing_store(
    monkeypatch, tmp_path, mock_client_class
):
    test_feeds_dir = tmp_path / "data" / "test_feeds"

    (
        test_feeds_dir
        / "7290661400001"
        / "001"
        / "020"
    ).mkdir(parents=True)

    monkeypatch.setattr(promos, "BASE_DIR", tmp_path)
    monkeypatch.setattr(promos, "TEST_DATA_DIR", test_feeds_dir)

    mock_client_class.get_files.return_value = [
        make_file_entry("020", "20260816", "060000"),
        make_file_entry("020", "20260816", "070000"),
        make_file_entry("020", "20260816", "080000"),
    ]

    result = await promos.download_promos(test=True)

    assert len(result) == 3

    folder = (
        test_feeds_dir
        / "7290661400001"
        / "001"
        / "020"
        / "promos"
    )

    assert len(list(folder.glob("Promo*.gz"))) == 3