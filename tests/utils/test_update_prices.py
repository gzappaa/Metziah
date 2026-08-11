# tests/test_update_prices.py
from decimal import Decimal

from utils.update_prices import _log_changes
from database.records import PriceRecord


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