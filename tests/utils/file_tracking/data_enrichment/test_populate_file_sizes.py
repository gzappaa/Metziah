from pathlib import Path
from unittest.mock import MagicMock

import pytest

from utils.file_tracking.data_enrichment import populate_file_sizes


def test_get_file_path_pricefull(monkeypatch):
    monkeypatch.setattr(
        populate_file_sizes,
        "FEEDS_DIR",
        Path("/tmp/feeds"),
    )

    path = populate_file_sizes.get_file_path(
        chain_id="123",
        store_id="45",
        file_type="PriceFull",
        filename="prices.xml",
    )

    assert path == Path("/tmp/feeds/123/45/pricesfull/prices.xml")


def test_get_file_path_price(monkeypatch):
    monkeypatch.setattr(
        populate_file_sizes,
        "FEEDS_DIR",
        Path("/tmp/feeds"),
    )

    path = populate_file_sizes.get_file_path(
        chain_id="123",
        store_id="45",
        file_type="Price",
        filename="prices.xml",
    )

    assert path == Path("/tmp/feeds/123/45/prices/prices.xml")


def test_get_file_path_promo_full(monkeypatch):
    monkeypatch.setattr(
        populate_file_sizes,
        "FEEDS_DIR",
        Path("/tmp/feeds"),
    )

    path = populate_file_sizes.get_file_path(
        chain_id="123",
        store_id="45",
        file_type="PromoFull",
        filename="promos.xml",
    )

    assert path == Path("/tmp/feeds/123/45/promosfull/promos.xml")


def test_get_file_path_promo(monkeypatch):
    monkeypatch.setattr(
        populate_file_sizes,
        "FEEDS_DIR",
        Path("/tmp/feeds"),
    )

    path = populate_file_sizes.get_file_path(
        chain_id="123",
        store_id="45",
        file_type="Promo",
        filename="promos.xml",
    )

    assert path == Path("/tmp/feeds/123/45/promos/promos.xml")


def test_get_file_path_stores(monkeypatch):
    monkeypatch.setattr(
        populate_file_sizes,
        "FEEDS_DIR",
        Path("/tmp/feeds"),
    )

    path = populate_file_sizes.get_file_path(
        chain_id="123",
        store_id="45",
        file_type="Stores",
        filename="stores.xml",
    )

    assert path == Path("/tmp/feeds/123/stores/stores.xml")


def test_get_file_path_unsupported_type():
    with pytest.raises(ValueError, match="Unsupported file type: Unknown"):
        populate_file_sizes.get_file_path(
            chain_id="123",
            store_id="45",
            file_type="Unknown",
            filename="test.xml",
        )


def test_get_missing_file_sizes():
    cur = MagicMock()
    cur.fetchall.return_value = [
        (1, "123", "45", "Price", "price.xml"),
        (2, "123", "46", "Promo", "promo.xml"),
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    result = populate_file_sizes.get_missing_file_sizes(conn)

    cur.execute.assert_called_once()

    query = cur.execute.call_args.args[0]

    assert "downloaded = TRUE" in query
    assert "file_size IS NULL" in query
    assert "ORDER BY id" in query

    assert result == [
        (1, "123", "45", "Price", "price.xml"),
        (2, "123", "46", "Promo", "promo.xml"),
    ]


def test_update_file_size():
    cur = MagicMock()

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    populate_file_sizes.update_file_size(
        conn=conn,
        file_tracking_id=123,
        file_size=4567,
    )

    cur.execute.assert_called_once()

    query, params = cur.execute.call_args.args

    assert "UPDATE file_tracking" in query
    assert "SET" in query
    assert "file_size = %s" in query
    assert "updated_at = now()" in query
    assert "WHERE id = %s" in query

    assert params == (4567, 123)


def test_main_updates_existing_files_and_skips_missing(monkeypatch):
    rows = [
        (1, "123", "45", "Price", "exists.xml"),
        (2, "123", "46", "Promo", "missing.xml"),
    ]

    monkeypatch.setattr(
        populate_file_sizes,
        "get_missing_file_sizes",
        lambda conn: rows,
    )

    existing = MagicMock()
    existing.is_file.return_value = True
    existing.stat.return_value.st_size = 1234

    missing = MagicMock()
    missing.is_file.return_value = False

    def get_path(**kwargs):
        if kwargs["filename"] == "exists.xml":
            return existing
        return missing

    monkeypatch.setattr(
        populate_file_sizes,
        "get_file_path",
        get_path,
    )

    update_file_size = MagicMock()

    monkeypatch.setattr(
        populate_file_sizes,
        "update_file_size",
        update_file_size,
    )

    cur = MagicMock()
    cur.fetchone.return_value = (True,)

    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur

    monkeypatch.setattr(
        populate_file_sizes,
        "get_connection",
        lambda: conn,
    )

    result = populate_file_sizes.main()

    assert result is None

    update_file_size.assert_called_once_with(
        conn=conn,
        file_tracking_id=1,
        file_size=1234,
    )

    conn.commit.assert_called_once()

    execute_calls = [
        call.args
        for call in cur.execute.call_args_list
    ]

    assert (
        "SELECT pg_try_advisory_lock(%s)",
        (populate_file_sizes.FILE_SIZE_LOCK_ID,),
    ) in execute_calls

    assert (
        "SELECT pg_advisory_unlock(%s)",
        (populate_file_sizes.FILE_SIZE_LOCK_ID,),
    ) in execute_calls


def test_main_skips_when_lock_unavailable(monkeypatch):
    get_missing = MagicMock()

    monkeypatch.setattr(
        populate_file_sizes,
        "get_missing_file_sizes",
        get_missing,
    )

    cur = MagicMock()
    cur.fetchone.return_value = (False,)

    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur

    monkeypatch.setattr(
        populate_file_sizes,
        "get_connection",
        lambda: conn,
    )

    result = populate_file_sizes.main()

    assert result == 0

    get_missing.assert_not_called()
    conn.commit.assert_not_called()

    cur.execute.assert_called_once_with(
        "SELECT pg_try_advisory_lock(%s)",
        (populate_file_sizes.FILE_SIZE_LOCK_ID,),
    )


def test_main_unlocks_when_processing_fails(monkeypatch):
    monkeypatch.setattr(
        populate_file_sizes,
        "get_missing_file_sizes",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    cur = MagicMock()
    cur.fetchone.return_value = (True,)

    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur

    monkeypatch.setattr(
        populate_file_sizes,
        "get_connection",
        lambda: conn,
    )

    with pytest.raises(RuntimeError, match="boom"):
        populate_file_sizes.main()

    execute_calls = [
        call.args
        for call in cur.execute.call_args_list
    ]

    assert (
        "SELECT pg_advisory_unlock(%s)",
        (populate_file_sizes.FILE_SIZE_LOCK_ID,),
    ) in execute_calls