import csv
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.file_tracking import load_file_tracking


def test_local_feed_directory():
    assert load_file_tracking._local_feed_directory("Price") == "prices"
    assert load_file_tracking._local_feed_directory("PriceFull") == "pricesfull"
    assert load_file_tracking._local_feed_directory("Promo") == "promos"
    assert load_file_tracking._local_feed_directory("PromoFull") == "promosfull"
    assert load_file_tracking._local_feed_directory("Stores") is None
    assert load_file_tracking._local_feed_directory("Unknown") is None


def test_is_downloaded_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(
        load_file_tracking,
        "FEEDS_DIR",
        tmp_path,
    )

    path = (
        tmp_path
        / "123"
        / "41"
        / "prices"
        / "Price123-001-041-20260924-000000.xml"
    )
    path.parent.mkdir(parents=True)
    path.touch()

    record = {
        "chain_id": "123",
        "store_id": "041",
        "file_type": "Price",
        "filename": "Price123-001-041-20260924-000000.xml",
    }

    assert load_file_tracking._is_downloaded_locally(record) is True


def test_is_downloaded_locally_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        load_file_tracking,
        "FEEDS_DIR",
        tmp_path,
    )

    record = {
        "chain_id": "123",
        "store_id": "041",
        "file_type": "Price",
        "filename": "missing.xml",
    }

    assert load_file_tracking._is_downloaded_locally(record) is False


def test_is_downloaded_locally_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(
        load_file_tracking,
        "FEEDS_DIR",
        tmp_path,
    )

    filename = "Stores123-20260924.xml"

    path = tmp_path / "123" / "stores" / filename
    path.parent.mkdir(parents=True)
    path.touch()

    record = {
        "chain_id": "123",
        "file_type": "Stores",
        "filename": filename,
    }

    assert load_file_tracking._is_downloaded_locally(record) is True


def test_is_downloaded_locally_unknown_file_type(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        load_file_tracking,
        "FEEDS_DIR",
        tmp_path,
    )

    record = {
        "chain_id": "123",
        "store_id": "41",
        "file_type": "Unknown",
        "filename": "test.xml",
    }

    assert load_file_tracking._is_downloaded_locally(record) is False


def test_set_downloaded_status(monkeypatch):
    records = [
        {"filename": "a.xml"},
        {"filename": "b.xml"},
        {"filename": "c.xml"},
    ]

    statuses = iter([True, False, True])

    monkeypatch.setattr(
        load_file_tracking,
        "_is_downloaded_locally",
        lambda record: next(statuses),
    )

    load_file_tracking._set_downloaded_status(records)

    assert records == [
        {"filename": "a.xml", "downloaded": True},
        {"filename": "b.xml", "downloaded": False},
        {"filename": "c.xml", "downloaded": True},
    ]


def test_add_record_normalizes_store_id(monkeypatch):
    records = []

    monkeypatch.setattr(
        load_file_tracking,
        "normalize_file",
        lambda filename, size: {
            "filename": filename,
            "store_id": "041",
        },
    )

    monkeypatch.setattr(
        load_file_tracking,
        "normalize_store_id",
        lambda store_id: "41",
    )

    load_file_tracking._add_record(
        records,
        "Price123-001-041-20260924-000000.xml",
        "test",
        123,
    )

    assert records == [
        {
            "filename": "Price123-001-041-20260924-000000.xml",
            "store_id": "41",
            "source": "test",
        }
    ]


def test_add_record_ignores_invalid_filename(monkeypatch):
    records = []

    monkeypatch.setattr(
        load_file_tracking,
        "normalize_file",
        lambda filename, size: None,
    )

    load_file_tracking._add_record(
        records,
        "invalid.xml",
        "test",
    )

    assert records == []


@pytest.mark.asyncio
async def test_get_carrefour_files(monkeypatch):
    client = MagicMock()
    client.get_files = AsyncMock(
        return_value={
            "files": [
                "Price123-001-001-20260924-000000.xml",
                {
                    "name": "Promo123-001-001-20260924-000000.xml",
                    "size": "1234",
                },
                {
                    "fileName": "PriceFull123-001-001-20260924-000000.xml",
                    "size": "2 KB",
                },
                {
                    "Name": "PromoFull123-001-001-20260924-000000.xml",
                },
                {
                    "name": None,
                },
            ]
        }
    )

    monkeypatch.setattr(
        load_file_tracking,
        "CarrefourClient",
        lambda: client,
    )

    monkeypatch.setattr(
        load_file_tracking,
        "normalize_file",
        lambda filename, size: {
            "filename": filename,
            "file_size": size,
        },
    )

    records = await load_file_tracking.get_carrefour_files()

    assert len(records) == 4
    assert all(
        record["source"] == "carrefour"
        for record in records
    )


@pytest.mark.asyncio
async def test_get_mishnatyosef_files(monkeypatch):
    client = MagicMock()
    client.get_files = AsyncMock(
        return_value=[
            {
                "name": "Price123-001-001-20260924-000000.xml",
                "size": "100 KB",
            },
            {
                "filename": "Promo123-001-001-20260924-000000.xml",
                "size": "200 KB",
            },
            "PriceFull123-001-001-20260924-000000.xml",
            None,
        ]
    )

    monkeypatch.setattr(
        load_file_tracking,
        "MishnatYosefClient",
        lambda: client,
    )

    monkeypatch.setattr(
        load_file_tracking,
        "normalize_file",
        lambda filename, size: {
            "filename": filename,
            "file_size": size,
        },
    )

    records = await load_file_tracking.get_mishnatyosef_files()

    assert len(records) == 3
    assert all(
        record["source"] == "mishnat yosef"
        for record in records
    )


@pytest.mark.asyncio
async def test_get_wolt_files_only_today(monkeypatch):
    client = MagicMock()

    client.get_date_pages = AsyncMock(
        return_value=[
            "2026-09-23",
            "2026-09-24",
        ]
    )

    client.get_files = AsyncMock(
        return_value=[
            "https://example.com/Price123.xml",
            "https://example.com/Promo123.xml",
        ]
    )

    monkeypatch.setattr(
        load_file_tracking,
        "WoltClient",
        lambda: client,
    )

    class FakeDate:
        @classmethod
        def today(cls):
            from datetime import date

            return date(2026, 9, 24)

    monkeypatch.setattr(
        load_file_tracking,
        "date",
        FakeDate,
    )

    monkeypatch.setattr(
        load_file_tracking,
        "normalize_file",
        lambda filename, size=None: {
            "filename": filename,
        },
    )

    records = await load_file_tracking.get_wolt_files()

    assert len(records) == 2
    assert client.get_files.await_count == 1
    assert all(
        record["source"] == "wolt"
        for record in records
    )


@pytest.mark.asyncio
async def test_collect_all_files(monkeypatch):
    async def collector_one(slow=False):
        return [{"filename": "a.xml"}]

    async def collector_two(slow=False):
        return [{"filename": "b.xml"}]

    async def collector_three(slow=False):
        return [{"filename": "c.xml"}]

    async def empty_collector(slow=False):
        return []

    monkeypatch.setattr(
        load_file_tracking,
        "get_publishedprices_files",
        collector_one,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_binaprojects_files",
        collector_two,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_laibcatalog_files",
        collector_three,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_carrefour_files",
        empty_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_html_files",
        empty_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_mishnatyosef_files",
        empty_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_wolt_files",
        empty_collector,
    )

    records = await load_file_tracking.collect_all_files()

    assert records == [
        {"filename": "a.xml"},
        {"filename": "b.xml"},
        {"filename": "c.xml"},
    ]


@pytest.mark.asyncio
async def test_collect_all_files_continues_after_failure(
    monkeypatch,
):
    async def failing_collector(slow=False):
        raise RuntimeError("boom")

    async def working_collector(slow=False):
        return [{"filename": "working.xml"}]

    async def empty_collector(slow=False):
        return []

    monkeypatch.setattr(
        load_file_tracking,
        "get_publishedprices_files",
        failing_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_binaprojects_files",
        working_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_laibcatalog_files",
        empty_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_carrefour_files",
        empty_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_html_files",
        empty_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_mishnatyosef_files",
        empty_collector,
    )
    monkeypatch.setattr(
        load_file_tracking,
        "get_wolt_files",
        empty_collector,
    )

    records = await load_file_tracking.collect_all_files()

    assert records == [
        {"filename": "working.xml"},
    ]


def test_generate_report(tmp_path, monkeypatch):
    monkeypatch.setattr(
        load_file_tracking,
        "REPORTS_DIR",
        tmp_path,
    )

    records = [
        {
            "filename": "Price123.xml",
            "source": "test",
            "file_type": "Price",
            "chain_id": "123",
            "sub_chain_id": "001",
            "store_id": "41",
            "file_date": "2026-09-24",
            "file_size": 100,
            "downloaded": True,
        },
        {
            "filename": "Promo123.xml",
            "source": "test",
            "file_type": "Promo",
            "chain_id": "123",
            "sub_chain_id": "001",
            "store_id": "41",
            "file_date": "2026-09-24",
            "file_size": None,
            "downloaded": False,
        },
    ]

    report_path = load_file_tracking.generate_report(records)

    assert report_path == (
        tmp_path / "file_tracking.csv"
    )
    assert report_path.exists()

    with report_path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 2
    assert rows[0]["filename"] == "Price123.xml"
    assert rows[0]["downloaded"] == "True"
    assert rows[1]["filename"] == "Promo123.xml"


@pytest.mark.asyncio
async def test_update_file_tracking_no_records(monkeypatch):
    async def empty_collect(slow=False):
        return []

    monkeypatch.setattr(
        load_file_tracking,
        "collect_all_files",
        empty_collect,
    )

    result = await load_file_tracking.update_file_tracking()

    assert result == 0


@pytest.mark.asyncio
async def test_update_file_tracking_report(monkeypatch):
    records = [
        {"filename": "a.xml"},
        {"filename": "b.xml"},
    ]

    async def collect(slow=False):
        return records

    monkeypatch.setattr(
        load_file_tracking,
        "collect_all_files",
        collect,
    )

    monkeypatch.setattr(
        load_file_tracking,
        "_is_downloaded_locally",
        lambda record: True,
    )

    generate_report = MagicMock()

    monkeypatch.setattr(
        load_file_tracking,
        "generate_report",
        generate_report,
    )

    result = await load_file_tracking.update_file_tracking(
        generate_report_file=True,
    )

    assert result == 2
    generate_report.assert_called_once_with(records)

    assert all(
        record["downloaded"] is True
        for record in records
    )

@pytest.mark.asyncio
async def test_update_file_tracking_deduplicates_by_filename(
    monkeypatch,
):
    records = [
        {
            "filename": "same.xml",
            "source": "first",
        },
        {
            "filename": "same.xml",
            "source": "second",
        },
    ]

    async def collect(slow=False):
        return records

    monkeypatch.setattr(
        load_file_tracking,
        "collect_all_files",
        collect,
    )

    monkeypatch.setattr(
        load_file_tracking,
        "_set_downloaded_status",
        lambda records: [
            record.update(downloaded=True)
            for record in records
        ],
    )

    generate_report = MagicMock()

    monkeypatch.setattr(
        load_file_tracking,
        "generate_report",
        generate_report,
    )

    result = await load_file_tracking.update_file_tracking(
        generate_report_file=True,
    )

    assert result == 1

    report_records = generate_report.call_args.args[0]

    assert len(report_records) == 1
    assert report_records[0]["filename"] == "same.xml"
    assert report_records[0]["source"] == "second"