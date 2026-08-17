# tests/utils/test_update_prices.py

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from database.records import PriceRecord, ProductRecord
from utils.update_prices import (
    _dedupe_price_records,
    _log_changes,
    load_files,
    load_one_file,
)


CHAIN_ID = "TEST_CHAIN"
STORE_ID = "TEST_STORE"


def make_price_record(
    item_code="ITEM_001",
    price="10.00",
    update_time=None,
):
    return PriceRecord(
        chain_id=CHAIN_ID,
        store_id=STORE_ID,
        item_code=item_code,
        price=Decimal(price),
        unit_price=Decimal(price),
        quantity=Decimal("1"),
        unit_qty="יחידה",
        unit_measure="",
        weighted=False,
        package_quantity=1,
        allow_discount=True,
        status="active",
        price_update_time=update_time,
        last_sale_datetime=None,
    )


# ---------------------------------------------------------------------------
# _log_changes
# ---------------------------------------------------------------------------


def test_price_added_logs(caplog):
    item_code = "ITEM_001"
    price_record = make_price_record(item_code=item_code, price="10.50")

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            product_records=[],
            store_product_records=[],
            price_records=[price_record],
            existing_products={},
            existing_store_products={},
            existing_prices={},
        )

    assert "PRICE ADDED" in caplog.text
    assert item_code in caplog.text


def test_price_changed_logs(caplog):
    item_code = "ITEM_002"
    price_record = make_price_record(item_code=item_code, price="12.00")

    existing_prices = {
        item_code: (Decimal("10.00"), Decimal("10.00"))
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            product_records=[],
            store_product_records=[],
            price_records=[price_record],
            existing_products={},
            existing_store_products={},
            existing_prices=existing_prices,
        )

    assert "PRICE CHANGED" in caplog.text
    assert item_code in caplog.text


def test_price_unchanged_does_not_log(caplog):
    item_code = "ITEM_003"
    price_record = make_price_record(item_code=item_code, price="10.00")

    existing_prices = {
        item_code: (Decimal("10.00"), Decimal("10.00"))
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            product_records=[],
            store_product_records=[],
            price_records=[price_record],
            existing_products={},
            existing_store_products={},
            existing_prices=existing_prices,
        )

    assert "PRICE ADDED" not in caplog.text
    assert "PRICE CHANGED" not in caplog.text


def test_item_added_logs_product_metadata(caplog):
    item_code = "ITEM_004"

    product_record = ProductRecord(
        item_code=item_code,
        name="Test Product",
        manufacturer="Acme",
        manufacturer_country="IL",
        item_type=1,
    )

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            product_records=[product_record],
            store_product_records=[],
            price_records=[],
            existing_products={},
            existing_store_products={},
            existing_prices={},
        )

    assert "ITEM ADDED" in caplog.text
    assert item_code in caplog.text


def test_manufacturer_fill_only_fills_blank(caplog):
    item_code = "ITEM_005"

    product_record = ProductRecord(
        item_code=item_code,
        name="Test Product",
        manufacturer="Acme",
        manufacturer_country="IL",
        item_type=1,
    )

    existing_products = {
        item_code: ("Test Product", None, None, 1)
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            product_records=[product_record],
            store_product_records=[],
            price_records=[],
            existing_products=existing_products,
            existing_store_products={},
            existing_prices={},
        )

    assert "ITEM METADATA CHANGED" in caplog.text
    assert item_code in caplog.text


def test_manufacturer_fill_only_does_not_overwrite(caplog):
    item_code = "ITEM_006"

    product_record = ProductRecord(
        item_code=item_code,
        name="Test Product",
        manufacturer="Different Manufacturer",
        manufacturer_country="US",
        item_type=1,
    )

    existing_products = {
        item_code: ("Test Product", "Original Manufacturer", "IL", 1)
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            product_records=[product_record],
            store_product_records=[],
            price_records=[],
            existing_products=existing_products,
            existing_store_products={},
            existing_prices={},
        )

    assert "ITEM METADATA CHANGED" not in caplog.text


# ---------------------------------------------------------------------------
# load_files
# ---------------------------------------------------------------------------


def test_load_files_continues_after_file_failure(monkeypatch):
    files = [
        Path("file1.gz"),
        Path("file2.gz"),
    ]

    processed_files = []

    def fake_load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
        log_changes=True,
    ):
        processed_files.append(filepath)

        if filepath == files[0]:
            raise RuntimeError("test failure")

    monkeypatch.setattr(
        "utils.update_prices.load_one_file",
        fake_load_one_file,
    )

    monkeypatch.setattr(
        "utils.update_prices.mark_files_loaded",
        lambda conn, filenames: None,
    )

    class FakeConnection:
        def rollback(self):
            pass

        def commit(self):
            pass

    conn = FakeConnection()

    loaded = load_files(
        conn,
        files,
        Path("data/test_feeds"),
    )

    assert processed_files == files
    assert loaded == [files[1]]


def test_load_files_rolls_back_on_failure(monkeypatch):
    filepath = Path("file.gz")

    class FakeConnection:
        def __init__(self):
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            pass

    conn = FakeConnection()

    def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(
        "utils.update_prices.load_one_file",
        fail,
    )

    monkeypatch.setattr(
        "utils.update_prices.mark_files_loaded",
        lambda conn, filenames: None,
    )

    loaded = load_files(
        conn,
        [filepath],
        Path("data/test_feeds"),
    )

    assert conn.rolled_back is True
    assert loaded == []


# ---------------------------------------------------------------------------
# load_one_file -- mocked dependencies
# ---------------------------------------------------------------------------


def test_load_one_file_log_changes_false_skips_snapshots(
    monkeypatch,
    tmp_path,
):
    filepath = (
        tmp_path
        / CHAIN_ID
        / "001"
        / STORE_ID
        / "prices"
        / "test.gz"
    )
    filepath.parent.mkdir(parents=True)

    import gzip

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    class FakeProduct:
        chain_id = CHAIN_ID
        store_id = STORE_ID
        item_code = "ITEM_001"

    price = make_price_record()

    class FakeParser:
        def parse_price_file(self, xml_content):
            return [FakeProduct()]

    # These MUST NOT be called when log_changes=False.
    def fail(*args, **kwargs):
        raise AssertionError("snapshot query should not be called")

    monkeypatch.setattr(
        "utils.update_prices._fetch_existing_prices",
        fail,
    )
    monkeypatch.setattr(
        "utils.update_prices._fetch_existing_products",
        fail,
    )
    monkeypatch.setattr(
        "utils.update_prices._fetch_existing_store_products",
        fail,
    )

    monkeypatch.setattr(
        "utils.update_prices.split_product",
        lambda product: (None, None, price),
    )
    monkeypatch.setattr(
        "utils.update_prices.ensure_chain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.update_store_subchain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.upsert_products",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.upsert_store_products",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.upsert_prices",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.reconcile_removed_items",
        lambda *args, **kwargs: 0,
    )

    class FakeConnection:
        def commit(self):
            pass

    load_one_file(
        FakeConnection(),
        FakeParser(),
        filepath,
        tmp_path,
        log_changes=False,
    )


def test_load_one_file_log_changes_false_does_not_log_changes(
    monkeypatch,
    caplog,
    tmp_path,
):
    filepath = (
        tmp_path
        / CHAIN_ID
        / "001"
        / STORE_ID
        / "prices"
        / "test.gz"
    )
    filepath.parent.mkdir(parents=True)

    import gzip

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    class FakeProduct:
        chain_id = CHAIN_ID
        store_id = STORE_ID
        item_code = "ITEM_001"

    price = make_price_record()

    class FakeParser:
        def parse_price_file(self, xml_content):
            return [FakeProduct()]

    monkeypatch.setattr(
        "utils.update_prices.split_product",
        lambda product: (None, None, price),
    )
    monkeypatch.setattr(
        "utils.update_prices.ensure_chain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.update_store_subchain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.upsert_products",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.upsert_store_products",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.upsert_prices",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_prices.reconcile_removed_items",
        lambda *args, **kwargs: 0,
    )

    class FakeConnection:
        def commit(self):
            pass

    with caplog.at_level("INFO", logger="price_changes"):
        load_one_file(
            FakeConnection(),
            FakeParser(),
            filepath,
            tmp_path,
            log_changes=False,
        )

    assert "PRICE ADDED" not in caplog.text
    assert "PRICE CHANGED" not in caplog.text
    assert "ITEM ADDED" not in caplog.text
    assert "ITEM REMOVED" not in caplog.text
# ---------------------------------------------------------------------------
# _dedupe_price_records
# ---------------------------------------------------------------------------


def test_dedupe_price_records_keeps_latest_update():
    older = make_price_record(
        price="10.00",
        update_time=datetime(
            2026,
            8,
            17,
            10,
            0,
            tzinfo=timezone.utc,
        ),
    )

    newer = make_price_record(
        price="12.00",
        update_time=datetime(
            2026,
            8,
            17,
            11,
            0,
            tzinfo=timezone.utc,
        ),
    )

    result = _dedupe_price_records([older, newer])

    assert len(result) == 1
    assert result[0].price == Decimal("12.00")


def test_dedupe_price_records_is_independent_of_input_order():
    older = make_price_record(
        price="10.00",
        update_time=datetime(
            2026,
            8,
            17,
            10,
            0,
            tzinfo=timezone.utc,
        ),
    )

    newer = make_price_record(
        price="12.00",
        update_time=datetime(
            2026,
            8,
            17,
            11,
            0,
            tzinfo=timezone.utc,
        ),
    )

    result = _dedupe_price_records([newer, older])

    assert len(result) == 1
    assert result[0].price == Decimal("12.00")