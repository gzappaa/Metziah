# tests/utils/prices/test_update_prices.py

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

import utils.prices.update_prices as module
from database.records import PriceRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHAIN_ID = "7290000000001"
STORE_ID = "1"


def make_price_record(
    chain_id=CHAIN_ID,
    store_id=STORE_ID,
    item_code="123",
    price=Decimal("10.00"),
    unit_price=Decimal("10.00"),
    quantity=Decimal("1"),
    unit_qty="1",
    unit_measure="unit",
    weighted=False,
    package_quantity=None,
    allow_discount=True,
    status=None,
    price_update_time=None,
    last_sale_datetime=None,
):
    return PriceRecord(
        chain_id=chain_id,
        store_id=store_id,
        item_code=item_code,
        price=price,
        unit_price=unit_price,
        quantity=quantity,
        unit_qty=unit_qty,
        unit_measure=unit_measure,
        weighted=weighted,
        package_quantity=package_quantity,
        allow_discount=allow_discount,
        status=status,
        price_update_time=price_update_time,
        last_sale_datetime=last_sale_datetime,
    )


def make_path(tmp_path, file_type="Price"):
    feeds_dir = tmp_path / "feeds"

    directory = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / (
            "pricesfull"
            if file_type == "PriceFull"
            else "prices"
        )
    )

    directory.mkdir(parents=True)

    filepath = (
        directory
        / f"{file_type}{CHAIN_ID}-001-20260924.xml"
    )

    return feeds_dir, filepath


def patch_common(monkeypatch):
    monkeypatch.setattr(
        module,
        "ensure_chain",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "update_store_subchain",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "parse_filename",
        Mock(
            return_value={
                "chain_id": CHAIN_ID,
                "sub_chain_id": "001",
            }
        ),
    )


# ---------------------------------------------------------------------------
# _dedupe_price_records
# ---------------------------------------------------------------------------

def test_dedupe_keeps_unique_records():
    records = [
        make_price_record(item_code="1"),
        make_price_record(item_code="2"),
    ]

    result = module._dedupe_price_records(records)

    assert len(result) == 2
    assert {record.item_code for record in result} == {
        "1",
        "2",
    }


def test_dedupe_latest_timestamp_wins():
    older = make_price_record(
        item_code="1",
        price=Decimal("10.00"),
        price_update_time=datetime(
            2026, 9, 24, 10, 0
        ),
    )

    newer = make_price_record(
        item_code="1",
        price=Decimal("20.00"),
        price_update_time=datetime(
            2026, 9, 24, 11, 0
        ),
    )

    result = module._dedupe_price_records(
        [older, newer]
    )

    assert len(result) == 1
    assert result[0].price == Decimal("20.00")


def test_dedupe_older_timestamp_does_not_replace_newer():
    newer = make_price_record(
        item_code="1",
        price=Decimal("20.00"),
        price_update_time=datetime(
            2026, 9, 24, 11, 0
        ),
    )

    older = make_price_record(
        item_code="1",
        price=Decimal("10.00"),
        price_update_time=datetime(
            2026, 9, 24, 10, 0
        ),
    )

    result = module._dedupe_price_records(
        [newer, older]
    )

    assert len(result) == 1
    assert result[0].price == Decimal("20.00")


def test_dedupe_timestamped_record_replaces_none():
    without_timestamp = make_price_record(
        item_code="1",
        price=Decimal("10.00"),
        price_update_time=None,
    )

    timestamped = make_price_record(
        item_code="1",
        price=Decimal("20.00"),
        price_update_time=datetime(
            2026, 9, 24, 10, 0
        ),
    )

    result = module._dedupe_price_records(
        [without_timestamp, timestamped]
    )

    assert len(result) == 1
    assert result[0].price == Decimal("20.00")


def test_dedupe_none_timestamp_does_not_replace_timestamped():
    timestamped = make_price_record(
        item_code="1",
        price=Decimal("10.00"),
        price_update_time=datetime(
            2026, 9, 24, 10, 0
        ),
    )

    without_timestamp = make_price_record(
        item_code="1",
        price=Decimal("20.00"),
        price_update_time=None,
    )

    result = module._dedupe_price_records(
        [timestamped, without_timestamp]
    )

    assert len(result) == 1
    assert result[0].price == Decimal("10.00")


# ---------------------------------------------------------------------------
# _fetch_existing_prices
# ---------------------------------------------------------------------------

def test_fetch_existing_prices():
    conn = MagicMock()

    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("ITEM-1", Decimal("10.00"), Decimal("20.00")),
        ("ITEM-2", Decimal("5.50"), Decimal("11.00")),
    ]

    conn.cursor.return_value.__enter__.return_value = cursor

    result = module._fetch_existing_prices(
        conn,
        CHAIN_ID,
        STORE_ID,
    )

    assert result == {
        "ITEM-1": (Decimal("10.00"), Decimal("20.00")),
        "ITEM-2": (Decimal("5.50"), Decimal("11.00")),
    }

    cursor.execute.assert_called_once()

    query, params = cursor.execute.call_args.args

    assert "SELECT" in query
    assert "item_code" in query
    assert "price" in query
    assert "unit_price" in query
    assert "FROM prices" in query
    assert "chain_id = %s" in query
    assert "store_id = %s" in query
    assert params == (CHAIN_ID, STORE_ID)


# ---------------------------------------------------------------------------
# _log_price_changes
# ---------------------------------------------------------------------------

def test_log_price_changes_logs_added(monkeypatch):
    logger = Mock()

    monkeypatch.setattr(
        module,
        "change_logger",
        logger,
    )

    record = make_price_record(
        item_code="ITEM-1",
        price=Decimal("10.00"),
    )

    module._log_price_changes(
        CHAIN_ID,
        STORE_ID,
        [record],
        {},
    )

    logger.info.assert_called_once()

    args = logger.info.call_args.args

    assert args[0] == (
        "PRICE ADDED "
        "chain_id=%s "
        "store_id=%s "
        "item_code=%s "
        "price=%s"
    )

    assert args[1:] == (
        CHAIN_ID,
        STORE_ID,
        "ITEM-1",
        Decimal("10.00"),
    )


def test_log_price_changes_logs_price_change(monkeypatch):
    logger = Mock()

    monkeypatch.setattr(
        module,
        "change_logger",
        logger,
    )

    record = make_price_record(
        item_code="ITEM-1",
        price=Decimal("20.00"),
        unit_price=Decimal("20.00"),
    )

    module._log_price_changes(
        CHAIN_ID,
        STORE_ID,
        [record],
        {
            "ITEM-1": (
                Decimal("10.00"),
                Decimal("10.00"),
            )
        },
    )

    logger.info.assert_called_once()

    args = logger.info.call_args.args

    assert args[0].startswith("PRICE CHANGED")


def test_log_price_changes_logs_unit_price_change(
    monkeypatch,
):
    logger = Mock()

    monkeypatch.setattr(
        module,
        "change_logger",
        logger,
    )

    record = make_price_record(
        item_code="ITEM-1",
        price=Decimal("10.00"),
        unit_price=Decimal("12.00"),
    )

    module._log_price_changes(
        CHAIN_ID,
        STORE_ID,
        [record],
        {
            "ITEM-1": (
                Decimal("10.00"),
                Decimal("10.00"),
            )
        },
    )

    logger.info.assert_called_once()

    args = logger.info.call_args.args

    assert args[0].startswith("PRICE CHANGED")


def test_log_price_changes_does_not_log_equal_values(
    monkeypatch,
):
    logger = Mock()

    monkeypatch.setattr(
        module,
        "change_logger",
        logger,
    )

    record = make_price_record(
        item_code="ITEM-1",
        price=Decimal("10.00"),
        unit_price=Decimal("10.004"),
    )

    module._log_price_changes(
        CHAIN_ID,
        STORE_ID,
        [record],
        {
            "ITEM-1": (
                Decimal("10.00"),
                Decimal("10.00"),
            )
        },
    )

    logger.info.assert_not_called()


# ---------------------------------------------------------------------------
# load_one_file - validation
# ---------------------------------------------------------------------------

def test_load_one_file_rejects_invalid_file_type(
    tmp_path,
):
    conn = Mock()
    filepath = tmp_path / "test.xml"

    with pytest.raises(
        ValueError,
        match="Unsupported price file type",
    ):
        module.load_one_file(
            conn=conn,
            parser=Mock(),
            filepath=filepath,
            feeds_dir=tmp_path,
            chain_metadata={},
            file_type="Promo",
        )


def test_load_one_file_empty_document_returns_false(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir, filepath = make_path(
        tmp_path,
        "Price",
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [b"<xml/>"],
    )

    parser = Mock()
    parser.parse_price_file.return_value = []

    result = module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        chain_metadata={},
        file_type="Price",
        log_changes=False,
    )

    assert result is False
    parser.parse_price_file.assert_called_once_with(
        b"<xml/>"
    )


def test_load_one_file_unknown_chain_raises_keyerror(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir, filepath = make_path(
        tmp_path,
        "Price",
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [b"<xml/>"],
    )

    product = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    parser = Mock()
    parser.parse_price_file.return_value = [
        product
    ]

    patch_common(monkeypatch)

    with pytest.raises(
        KeyError,
        match=f"Chain {CHAIN_ID} not found",
    ):
        module.load_one_file(
            conn=conn,
            parser=parser,
            filepath=filepath,
            feeds_dir=feeds_dir,
            chain_metadata={},
            file_type="Price",
            log_changes=False,
        )


# ---------------------------------------------------------------------------
# load_one_file - delta/snapshot behavior
# ---------------------------------------------------------------------------

def test_price_delta_does_not_reconcile(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir, filepath = make_path(
        tmp_path,
        "Price",
    )

    product = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    record = make_price_record(
        item_code="ITEM-1"
    )

    parser = Mock()
    parser.parse_price_file.return_value = [
        product
    ]

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [b"<xml/>"],
    )

    patch_common(monkeypatch)

    monkeypatch.setattr(
        module,
        "split_product",
        lambda *args: (
            None,
            None,
            record,
        ),
    )

    upsert = Mock()
    reconcile = Mock()

    monkeypatch.setattr(
        module,
        "upsert_prices",
        upsert,
    )

    monkeypatch.setattr(
        module,
        "reconcile_removed_items",
        reconcile,
    )

    result = module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        chain_metadata={
            CHAIN_ID: {
                "name_he_normalized": "Test",
                "name_en_normalized": "Test",
            }
        },
        file_type="Price",
        snapshot=False,
        log_changes=False,
    )

    assert result is True
    upsert.assert_called_once()
    reconcile.assert_not_called()
    conn.commit.assert_called_once()


def test_price_snapshot_reconciles(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir, filepath = make_path(
        tmp_path,
        "Price",
    )

    product = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    record = make_price_record(
        item_code="ITEM-1"
    )

    parser = Mock()
    parser.parse_price_file.return_value = [
        product
    ]

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [b"<xml/>"],
    )

    patch_common(monkeypatch)

    monkeypatch.setattr(
        module,
        "split_product",
        lambda *args: (
            None,
            None,
            record,
        ),
    )

    monkeypatch.setattr(
        module,
        "upsert_prices",
        Mock(),
    )

    reconcile = Mock(return_value=3)

    monkeypatch.setattr(
        module,
        "reconcile_removed_items",
        reconcile,
    )

    result = module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        chain_metadata={
            CHAIN_ID: {
                "name_he_normalized": "Test",
                "name_en_normalized": "Test",
            }
        },
        file_type="Price",
        snapshot=True,
        log_changes=False,
    )

    assert result is True

    reconcile.assert_called_once_with(
        conn,
        CHAIN_ID,
        STORE_ID,
        {"ITEM-1"},
    )

    conn.commit.assert_called_once()


def test_pricefull_always_reconciles(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir, filepath = make_path(
        tmp_path,
        "PriceFull",
    )

    product = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    record = make_price_record(
        item_code="ITEM-1"
    )

    parser = Mock()
    parser.parse_price_file.return_value = [
        product
    ]

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [b"<xml/>"],
    )

    patch_common(monkeypatch)

    monkeypatch.setattr(
        module,
        "split_product",
        lambda *args: (
            None,
            None,
            record,
        ),
    )

    monkeypatch.setattr(
        module,
        "upsert_prices",
        Mock(),
    )

    reconcile = Mock(return_value=2)

    monkeypatch.setattr(
        module,
        "reconcile_removed_items",
        reconcile,
    )

    result = module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        chain_metadata={
            CHAIN_ID: {
                "name_he_normalized": "Test",
                "name_en_normalized": "Test",
            }
        },
        file_type="PriceFull",
        snapshot=False,
        log_changes=False,
    )

    assert result is True

    reconcile.assert_called_once_with(
        conn,
        CHAIN_ID,
        STORE_ID,
        {"ITEM-1"},
    )

    conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Deduplication inside load_one_file
# ---------------------------------------------------------------------------

def test_duplicate_item_codes_are_deduped_before_upsert(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir, filepath = make_path(
        tmp_path,
        "Price",
    )

    product_1 = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    product_2 = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    record_1 = make_price_record(
        item_code="ITEM-1",
        price=Decimal("10.00"),
        price_update_time=datetime(
            2026, 9, 24, 10, 0
        ),
    )

    record_2 = make_price_record(
        item_code="ITEM-1",
        price=Decimal("20.00"),
        price_update_time=datetime(
            2026, 9, 24, 11, 0
        ),
    )

    parser = Mock()
    parser.parse_price_file.return_value = [
        product_1,
        product_2,
    ]

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [b"<xml/>"],
    )

    patch_common(monkeypatch)

    records = iter([
        record_1,
        record_2,
    ])

    monkeypatch.setattr(
        module,
        "split_product",
        lambda *args: (
            None,
            None,
            next(records),
        ),
    )

    upsert = Mock()

    monkeypatch.setattr(
        module,
        "upsert_prices",
        upsert,
    )

    result = module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        chain_metadata={
            CHAIN_ID: {
                "name_he_normalized": "Test",
                "name_en_normalized": "Test",
            }
        },
        file_type="Price",
        snapshot=False,
        log_changes=False,
    )

    assert result is True

    upsert.assert_called_once()

    upsert_records = upsert.call_args.args[1]

    assert len(upsert_records) == 1
    assert upsert_records[0].item_code == "ITEM-1"
    assert upsert_records[0].price == Decimal("20.00")


# ---------------------------------------------------------------------------
# Multiple XML documents
# ---------------------------------------------------------------------------

def test_multiple_xml_documents_are_processed(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir, filepath = make_path(
        tmp_path,
        "Price",
    )

    product_1 = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    product_2 = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
    )

    parser = Mock()
    parser.parse_price_file.side_effect = [
        [product_1],
        [product_2],
    ]

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [
            b"<xml>1</xml>",
            b"<xml>2</xml>",
        ],
    )

    patch_common(monkeypatch)

    records = iter([
        make_price_record(item_code="ITEM-1"),
        make_price_record(item_code="ITEM-2"),
    ])

    monkeypatch.setattr(
        module,
        "split_product",
        lambda *args: (
            None,
            None,
            next(records),
        ),
    )

    upsert = Mock()

    monkeypatch.setattr(
        module,
        "upsert_prices",
        upsert,
    )

    result = module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        chain_metadata={
            CHAIN_ID: {
                "name_he_normalized": "Test",
                "name_en_normalized": "Test",
            }
        },
        file_type="Price",
        snapshot=False,
        log_changes=False,
    )

    assert result is True

    assert parser.parse_price_file.call_count == 2
    assert upsert.call_count == 2
    assert conn.commit.call_count == 2


# ---------------------------------------------------------------------------
# Path / filename metadata
# ---------------------------------------------------------------------------

def test_path_chain_and_store_are_authoritative(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    feeds_dir = tmp_path / "feeds"

    filepath = (
        feeds_dir
        / CHAIN_ID
        / "004"
        / "prices"
        / f"Price{CHAIN_ID}-001-20260924.xml"
    )

    filepath.parent.mkdir(parents=True)

    product = SimpleNamespace(
        chain_id=CHAIN_ID,
        store_id="004",
    )

    record = make_price_record(
        chain_id=CHAIN_ID,
        store_id="004",
    )

    parser = Mock()
    parser.parse_price_file.return_value = [
        product
    ]

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [b"<xml/>"],
    )

    patch_common(monkeypatch)

    monkeypatch.setattr(
        module,
        "split_product",
        lambda *args: (
            None,
            None,
            record,
        ),
    )

    monkeypatch.setattr(
        module,
        "upsert_prices",
        Mock(),
    )

    module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        chain_metadata={
            CHAIN_ID: {
                "name_he_normalized": "Test",
                "name_en_normalized": "Test",
            }
        },
        file_type="Price",
        snapshot=False,
        log_changes=False,
    )

    module.ensure_chain.assert_called_once_with(
        conn,
        CHAIN_ID,
        "Test",
        "Test",
    )

    module.update_store_subchain.assert_called_once_with(
        conn,
        CHAIN_ID,
        "004",
        "001",
    )


# ---------------------------------------------------------------------------
# load_files
# ---------------------------------------------------------------------------

def test_load_files_marks_successfully_loaded_file(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    filepath = tmp_path / "Price.xml"

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {},
    )

    monkeypatch.setattr(
        module,
        "load_one_file",
        Mock(return_value=True),
    )

    monkeypatch.setattr(
        module,
        "mark_files_loaded",
        Mock(),
    )

    result = module.load_files(
        conn,
        [(filepath, "Price", False)],
        tmp_path,
        log_changes=False,
    )

    assert result == [filepath]

    module.load_one_file.assert_called_once_with(
        conn,
        module.load_one_file.call_args.args[1],
        filepath,
        tmp_path,
        {},
        "Price",
        snapshot=False,
        log_changes=False,
    )

    module.mark_files_loaded.assert_called_once_with(
        conn,
        ["Price.xml"],
    )

    conn.commit.assert_called_once()


def test_load_files_does_not_mark_empty_file(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    filepath = tmp_path / "Price.xml"

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {},
    )

    monkeypatch.setattr(
        module,
        "load_one_file",
        Mock(return_value=False),
    )

    monkeypatch.setattr(
        module,
        "mark_files_loaded",
        Mock(),
    )

    result = module.load_files(
        conn,
        [(filepath, "Price", False)],
        tmp_path,
        log_changes=False,
    )

    assert result == []

    module.mark_files_loaded.assert_not_called()


def test_load_files_rolls_back_on_keyerror(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    filepath = tmp_path / "Price.xml"

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {},
    )

    monkeypatch.setattr(
        module,
        "load_one_file",
        Mock(side_effect=KeyError("unknown chain")),
    )

    result = module.load_files(
        conn,
        [(filepath, "Price", False)],
        tmp_path,
        log_changes=False,
    )

    assert result == []
    conn.rollback.assert_called_once()


def test_load_files_rolls_back_on_exception(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    filepath = tmp_path / "Price.xml"

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {},
    )

    monkeypatch.setattr(
        module,
        "load_one_file",
        Mock(side_effect=RuntimeError("boom")),
    )

    result = module.load_files(
        conn,
        [(filepath, "Price", False)],
        tmp_path,
        log_changes=False,
    )

    assert result == []
    conn.rollback.assert_called_once()


def test_load_files_continues_after_failed_file(
    tmp_path,
    monkeypatch,
):
    conn = Mock()

    first = tmp_path / "first.xml"
    second = tmp_path / "second.xml"

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {},
    )

    load_one_file = Mock(
        side_effect=[
            RuntimeError("failed"),
            True,
        ]
    )

    monkeypatch.setattr(
        module,
        "load_one_file",
        load_one_file,
    )

    monkeypatch.setattr(
        module,
        "mark_files_loaded",
        Mock(),
    )

    result = module.load_files(
        conn,
        [
            (first, "Price", False),
            (second, "Price", False),
        ],
        tmp_path,
        log_changes=False,
    )

    assert result == [second]
    assert load_one_file.call_count == 2
    assert conn.rollback.call_count == 1