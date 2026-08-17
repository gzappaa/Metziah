from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import load_file_tracking


# ---------------------------------------------------------
# parse_filename
# ---------------------------------------------------------

def test_parse_filename_price():
    result = load_file_tracking.parse_filename(
        "Price7290661400001-001-020-20260816-111700.gz"
    )

    assert result == {
        "chain_id": "7290661400001",
        "sub_chain_id": "001",
        "store_id": "020",
        "file_type": "Price",
        "filename": "Price7290661400001-001-020-20260816-111700.gz",
        "file_date": date(2026, 8, 16),
    }


def test_parse_filename_promofull():
    result = load_file_tracking.parse_filename(
        "PromoFull7290661400001-001-020-20260816-043059.gz"
    )

    assert result["file_type"] == "PromoFull"
    assert result["chain_id"] == "7290661400001"
    assert result["sub_chain_id"] == "001"
    assert result["store_id"] == "020"
    assert result["file_date"] == date(2026, 8, 16)


def test_parse_filename_stores():
    result = load_file_tracking.parse_filename(
        "Stores7290661400001-20260816-043000.gz"
    )

    assert result == {
        "chain_id": "7290661400001",
        "sub_chain_id": None,
        "store_id": None,
        "file_type": "Stores",
        "filename": "Stores7290661400001-20260816-043000.gz",
        "file_date": date(2026, 8, 16),
    }


def test_parse_filename_invalid_raises():
    with pytest.raises(ValueError, match="Unrecognized feed filename"):
        load_file_tracking.parse_filename("garbage.gz")


# ---------------------------------------------------------
# get_local_path
# ---------------------------------------------------------

@pytest.mark.parametrize(
    ("file_type", "directory"),
    [
        ("Price", "prices"),
        ("PriceFull", "pricesfull"),
        ("Promo", "promos"),
        ("PromoFull", "promosfull"),
    ],
)
def test_get_local_path_maps_feed_type(
    monkeypatch,
    tmp_path,
    file_type,
    directory,
):
    monkeypatch.setattr(
        load_file_tracking,
        "FEEDS_DIR",
        tmp_path,
    )

    record = {
        "chain_id": "7290661400001",
        "sub_chain_id": "001",
        "store_id": "020",
        "file_type": file_type,
        "filename": f"{file_type}test.gz",
    }

    result = load_file_tracking.get_local_path(record)

    assert result == (
        tmp_path
        / "7290661400001"
        / "001"
        / "020"
        / directory
        / f"{file_type}test.gz"
    )


def test_get_local_path_rejects_stores():
    record = {
        "chain_id": "7290661400001",
        "sub_chain_id": None,
        "store_id": None,
        "file_type": "Stores",
        "filename": "Stores7290661400001-20260816-043000.gz",
    }

    with pytest.raises(ValueError, match="Stores files are not supported"):
        load_file_tracking.get_local_path(record)


# ---------------------------------------------------------
# get_file_records
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_get_file_records_skips_invalid_files(monkeypatch):
    client = MagicMock()
    client.get_files = AsyncMock(
        return_value=[
            {
                "fileName": (
                    "Price7290661400001-001-020-20260816-111700.gz"
                )
            },
            {
                "fileName": "garbage.gz"
            },
        ]
    )

    monkeypatch.setattr(
        load_file_tracking,
        "LaibcatalogClient",
        MagicMock(return_value=client),
    )

    result = await load_file_tracking.get_file_records(
        "7290661400001"
    )

    assert len(result) == 1
    assert result[0]["file_type"] == "Price"
    assert result[0]["store_id"] == "020"


# ---------------------------------------------------------
# update_file_tracking
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_update_file_tracking_builds_records_and_commits(
    monkeypatch,
    tmp_path,
):
    records = [
        {
            "chain_id": "7290661400001",
            "sub_chain_id": "001",
            "store_id": "020",
            "file_type": "Price",
            "filename": "Price020.gz",
            "file_date": date(2026, 8, 16),
        },
        {
            "chain_id": "7290661400001",
            "sub_chain_id": "001",
            "store_id": "021",
            "file_type": "Promo",
            "filename": "Promo021.gz",
            "file_date": date(2026, 8, 16),
        },
    ]

    async def fake_get_file_records(chain_id):
        return records

    monkeypatch.setattr(
        load_file_tracking,
        "get_file_records",
        fake_get_file_records,
    )

    # First file exists locally, second does not.
    def fake_local_path(record):
        path = tmp_path / record["filename"]

        if record["store_id"] == "020":
            path.touch()

        return path

    monkeypatch.setattr(
        load_file_tracking,
        "get_local_path",
        fake_local_path,
    )

    conn = MagicMock()
    context = MagicMock()
    context.__enter__ = MagicMock(return_value=conn)
    context.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(
        load_file_tracking,
        "get_connection",
        MagicMock(return_value=context),
    )

    insert = MagicMock(return_value=2)

    monkeypatch.setattr(
        load_file_tracking,
        "insert_file_tracking",
        insert,
    )

    # Make the test use exactly one chain.
    monkeypatch.setattr(
        load_file_tracking,
        "CHAINS",
        {
            "machsenei_hashuk": MagicMock(
                name="Machsanei Hashuk",
                chain_id="7290661400001",
            )
        },
    )

    result = await load_file_tracking.update_file_tracking()

    assert result == 2

    inserted_records = insert.call_args[0][1]

    assert inserted_records[0]["downloaded"] is True
    assert inserted_records[1]["downloaded"] is False

    insert.assert_called_once_with(
        conn,
        inserted_records,
    )

    conn.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_file_tracking_no_files_skips_database(
    monkeypatch,
):
    monkeypatch.setattr(
        load_file_tracking,
        "CHAINS",
        {
            "machsenei_hashuk": MagicMock(
                name="Machsanei Hashuk",
                chain_id="7290661400001",
            )
        },
    )

    monkeypatch.setattr(
        load_file_tracking,
        "get_file_records",
        AsyncMock(return_value=[]),
    )

    get_connection = MagicMock()

    monkeypatch.setattr(
        load_file_tracking,
        "get_connection",
        get_connection,
    )

    result = await load_file_tracking.update_file_tracking()

    assert result == 0
    get_connection.assert_not_called()