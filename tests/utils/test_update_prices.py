# tests/test_update_prices.py
from decimal import Decimal
import gzip
from utils.update_prices import _log_changes
from database.records import PriceRecord
from utils.update_prices import load_files, load_one_file
from parsers.xml import MachseneiXmlParser
from pathlib import Path



def test_price_added_logs(real_store, caplog):
    item_code = "0000000000001"  # doesn't need to pre-exist; existing_prices is empty

    price_record = PriceRecord(
        chain_id=real_store["chain_id"],
        store_id=real_store["store_id_text"],
        item_code=item_code,
        price=Decimal("10.50"),
        unit_price=Decimal("10.50"),
        quantity=Decimal("1"),
        unit_qty="יחידה",
        unit_measure="",
        weighted=False,
        package_quantity=1,
        allow_discount=True,
        status="active",
        price_update_time=None,
        last_sale_datetime=None,
    )

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            real_store["chain_id"],
            real_store["store_id_text"],
            product_records=[],
            store_product_records=[],
            price_records=[price_record],
            existing_products={},
            existing_store_products={},
            existing_prices={},
        )

    assert "PRICE ADDED" in caplog.text
    assert item_code in caplog.text




def test_price_changed_logs(real_store, caplog):
    item_code = "0000000000002"

    price_record = PriceRecord(
        chain_id=real_store["chain_id"],
        store_id=real_store["store_id_text"],
        item_code=item_code,
        price=Decimal("12.00"),
        unit_price=Decimal("12.00"),
        quantity=Decimal("1"),
        unit_qty="יחידה",
        unit_measure="",
        weighted=False,
        package_quantity=1,
        allow_discount=True,
        status="active",
        price_update_time=None,
        last_sale_datetime=None,
    )

    # Simulate that this item already existed with a different price
    existing_prices = {
        item_code: (Decimal("10.00"), Decimal("10.00"))
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            real_store["chain_id"],
            real_store["store_id_text"],
            product_records=[],
            store_product_records=[],
            price_records=[price_record],
            existing_products={},
            existing_store_products={},
            existing_prices=existing_prices,
        )

    assert "PRICE CHANGED" in caplog.text
    assert item_code in caplog.text




def test_price_unchanged_does_not_log(real_store, caplog):
    item_code = "0000000000003"

    price_record = PriceRecord(
        chain_id=real_store["chain_id"],
        store_id=real_store["store_id_text"],
        item_code=item_code,
        price=Decimal("10.00"),
        unit_price=Decimal("10.00"),
        quantity=Decimal("1"),
        unit_qty="יחידה",
        unit_measure="",
        weighted=False,
        package_quantity=1,
        allow_discount=True,
        status="active",
        price_update_time=None,
        last_sale_datetime=None,
    )

    # Same price as what's already "in the DB" -- nothing should log
    existing_prices = {
        item_code: (Decimal("10.00"), Decimal("10.00"))
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            real_store["chain_id"],
            real_store["store_id_text"],
            product_records=[],
            store_product_records=[],
            price_records=[price_record],
            existing_products={},
            existing_store_products={},
            existing_prices=existing_prices,
        )

    assert "PRICE ADDED" not in caplog.text
    assert "PRICE CHANGED" not in caplog.text


def test_item_added_logs_product_metadata(real_store, caplog):
    from database.records import ProductRecord

    item_code = "0000000000004"

    product_record = ProductRecord(
        item_code=item_code,
        name="Test Product",
        manufacturer="Acme",
        manufacturer_country="IL",
        item_type=1,
    )

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            real_store["chain_id"],
            real_store["store_id_text"],
            product_records=[product_record],
            store_product_records=[],
            price_records=[],
            existing_products={},  # nothing existing -- brand new item
            existing_store_products={},
            existing_prices={},
        )

    assert "ITEM ADDED" in caplog.text
    assert item_code in caplog.text


def test_manufacturer_fill_only_fills_blank(real_store, caplog):
    from database.records import ProductRecord

    item_code = "0000000000005"

    product_record = ProductRecord(
        item_code=item_code,
        name="Test Product",
        manufacturer="Acme",       # new value, non-blank
        manufacturer_country="IL",
        item_type=1,
    )

    # Existing row has manufacturer=None (blank) -- should get filled
    existing_products = {
        item_code: ("Test Product", None, None, 1)
        # (name, manufacturer, manufacturer_country, item_type)
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            real_store["chain_id"],
            real_store["store_id_text"],
            product_records=[product_record],
            store_product_records=[],
            price_records=[],
            existing_products=existing_products,
            existing_store_products={},
            existing_prices={},
        )

    assert "ITEM METADATA CHANGED" in caplog.text
    assert item_code in caplog.text

def test_manufacturer_fill_only_does_not_overwrite(real_store, caplog):
    from database.records import ProductRecord

    item_code = "0000000000006"

    product_record = ProductRecord(
        item_code=item_code,
        name="Test Product",
        manufacturer="Different Manufacturer",  # tries to overwrite
        manufacturer_country="IL",
        item_type=1,
    )

    # Existing row already has a manufacturer filled in
    existing_products = {
        item_code: ("Test Product", "Original Manufacturer", "IL", 1)
    }

    with caplog.at_level("INFO", logger="price_changes"):
        _log_changes(
            real_store["chain_id"],
            real_store["store_id_text"],
            product_records=[product_record],
            store_product_records=[],
            price_records=[],
            existing_products=existing_products,
            existing_store_products={},
            existing_prices={},
        )

    # Fill-only means old value wins -- nothing should be reported as changed
    assert "ITEM METADATA CHANGED" not in caplog.text





def test_load_one_file(conn):
    feeds_dir = Path("data/test_feeds")
    filepath = next(feeds_dir.glob("*/*/*/prices/*.gz"))

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prices")
        price_count = cur.fetchone()[0]

    assert price_count > 0


def test_load_one_file_updates_store_subchain(conn):
    feeds_dir = Path("data/test_feeds")
    filepath = next(feeds_dir.glob("*/*/*/prices/*.gz"))

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )

    chain_id, sub_chain_id, store_id = (
        filepath.relative_to(feeds_dir).parts[:3]
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sub_chain_id
            FROM stores
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )

        row = cur.fetchone()

    assert row is not None
    assert row[0] == sub_chain_id


def test_load_one_file_empty_xml_does_nothing(conn, tmp_path):
    feeds_dir = tmp_path

    filepath = (
        feeds_dir
        / "TEST_CHAIN"
        / "001"
        / "001"
        / "prices"
        / "empty.gz"
    )

    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )


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

    class FakeConnection:
        def rollback(self):
            pass

    conn = FakeConnection()

    load_files(
        conn,
        files,
        Path("data/test_feeds"),
    )

    assert processed_files == files


def test_load_files_rolls_back_on_failure(monkeypatch):
    filepath = Path("file.gz")

    class FakeConnection:
        def __init__(self):
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True

    conn = FakeConnection()

    def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(
        "utils.update_prices.load_one_file",
        fail,
    )

    load_files(
        conn,
        [filepath],
        Path("data/test_feeds"),
    )

    assert conn.rolled_back is True