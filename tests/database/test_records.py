from decimal import Decimal

from models.product import Product
from database.records import (
    PriceRecord,
    ProductRecord,
    StoreProductRecord,
    looks_like_barcode,
    split_product,
)


def test_looks_like_barcode():
    assert looks_like_barcode("12345678")
    assert looks_like_barcode("123456789012")
    assert looks_like_barcode("1234567890123")

    assert not looks_like_barcode("1234567")
    assert not looks_like_barcode("123456789")
    assert not looks_like_barcode("12345678901234")
    assert not looks_like_barcode("ABC12345678")
    assert not looks_like_barcode("1234-5678")


def test_split_product_barcode():
    product = Product(
        chain_id="7290661400001",
        sub_chain_id="001",
        store_id="001",
        item_code="1234567890123",
        name="Milk",
        price=Decimal("10.50"),
        unit_price=Decimal("10.50"),
        quantity=Decimal("1"),
        unit_qty="1",
        unit_measure="unit",
        manufacturer="Test Manufacturer",
        manufacturer_country="Israel",
        price_update_time=None,
        last_sale_datetime=None,
        weighted=False,
        allow_discount=True,
        item_type=1,
        package_quantity=None,
        status="Active",
    )

    product_record, store_product_record, price_record = split_product(product)

    assert product_record == ProductRecord(
        item_code="1234567890123",
        name="Milk",
        manufacturer="Test Manufacturer",
        manufacturer_country="Israel",
        item_type=1,
    )

    assert store_product_record is None

    assert price_record == PriceRecord(
        chain_id="7290661400001",
        store_id="001",
        item_code="1234567890123",
        price=Decimal("10.50"),
        unit_price=Decimal("10.50"),
        quantity=Decimal("1"),
        unit_qty="1",
        unit_measure="unit",
        weighted=False,
        package_quantity=None,
        allow_discount=True,
        status="Active",
        price_update_time=None,
        last_sale_datetime=None,
    )


def test_split_product_non_barcode():
    product = Product(
        chain_id="7290661400001",
        sub_chain_id="001",
        store_id="018",
        item_code="PRODUCE001",
        name="Tomatoes",
        price=Decimal("8.90"),
        unit_price=Decimal("8.90"),
        quantity=Decimal("1"),
        unit_qty="kg",
        unit_measure="kg",
        manufacturer=None,
        manufacturer_country=None,
        price_update_time=None,
        last_sale_datetime=None,
        weighted=True,
        allow_discount=False,
        item_type=0,
        package_quantity=None,
        status="Active",
    )

    product_record, store_product_record, price_record = split_product(product)

    assert product_record is None

    assert store_product_record == StoreProductRecord(
        chain_id="7290661400001",
        store_id="018",
        item_code="PRODUCE001",
        name="Tomatoes",
        manufacturer=None,
        manufacturer_country=None,
        item_type=0,
    )

    assert price_record.item_code == "PRODUCE001"
    assert price_record.store_id == "018"
    assert price_record.price == Decimal("8.90")