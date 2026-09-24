from decimal import Decimal

import pytest

from database.records import (
    PriceRecord,
    ProductRecord,
    StoreProductRecord,
    gtin_checksum_valid,
    is_valid_gtin,
    normalize_store_id,
    split_product,
    split_promotion,
)
from models.product import Product
from models.promo import Promotion, PromotionGroup, PromotionItem


def test_gtin_checksum_valid():
    assert gtin_checksum_valid("96385074")       # EAN-8
    assert gtin_checksum_valid("036000291452")   # UPC-A
    assert gtin_checksum_valid("7290110115227")  # EAN-13
    assert gtin_checksum_valid("10012345678902") # GTIN-14


def test_gtin_checksum_invalid():
    assert not gtin_checksum_valid("96385075")
    assert not gtin_checksum_valid("036000291453")
    assert not gtin_checksum_valid("7290110115228")
    assert not gtin_checksum_valid("10012345678903")


def test_gtin_checksum_rejects_invalid_codes():
    assert not gtin_checksum_valid("ABC12345678")
    assert not gtin_checksum_valid("1234-5678")
    assert not gtin_checksum_valid("1234567")
    assert not gtin_checksum_valid("123456789")
    assert not gtin_checksum_valid("12345678901")
    assert not gtin_checksum_valid("12345678901234")


def test_is_valid_gtin():
    assert is_valid_gtin("7290110115227")
    assert not is_valid_gtin("7290110115228")
    assert not is_valid_gtin("INTERNAL001")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("001", "1"),
        ("018", "18"),
        ("006", "6"),
        ("000", "0"),
        ("123", "123"),
        (" ABC ", "ABC"),
        ("ABC001", "ABC001"),
    ],
)
def test_normalize_store_id(value, expected):
    assert normalize_store_id(value) == expected


def test_split_product_gtin():
    product = Product(
        chain_id="xml-chain",
        sub_chain_id="001",
        store_id="001",
        item_code="7290110115227",
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

    product_record, store_product_record, price_record = split_product(
        product,
        chain_id="canonical-chain",
        store_id="1",
    )

    assert product_record == ProductRecord(
        item_code="7290110115227",
        name="Milk",
        manufacturer="Test Manufacturer",
        manufacturer_country="Israel",
        item_type=1,
    )

    assert store_product_record is None

    assert price_record == PriceRecord(
        chain_id="canonical-chain",
        store_id="1",
        item_code="7290110115227",
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


def test_split_product_invalid_gtin_becomes_store_product():
    product = Product(
        chain_id="xml-chain",
        sub_chain_id="001",
        store_id="018",
        item_code="1234567890123",
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

    product_record, store_product_record, price_record = split_product(
        product,
        chain_id="canonical-chain",
        store_id="18",
    )

    assert product_record is None

    assert store_product_record == StoreProductRecord(
        chain_id="canonical-chain",
        store_id="18",
        item_code="1234567890123",
        name="Tomatoes",
        manufacturer=None,
        manufacturer_country=None,
        item_type=0,
    )

    assert price_record.item_code == "1234567890123"
    assert price_record.chain_id == "canonical-chain"
    assert price_record.store_id == "18"
    assert price_record.price == Decimal("8.90")


def test_split_product_non_gtin():
    product = Product(
        chain_id="xml-chain",
        sub_chain_id="001",
        store_id="018",
        item_code="PRODUCE001",
        name="Tomatoes",
        price=Decimal("8.90"),
        unit_price=Decimal("8.90"),
        quantity=Decimal("2"),
        unit_qty="kg",
        unit_measure="kg",
        manufacturer="Test Farm",
        manufacturer_country="Israel",
        price_update_time=None,
        last_sale_datetime=None,
        weighted=True,
        allow_discount=False,
        item_type=0,
        package_quantity=3,
        status="Active",
    )

    product_record, store_product_record, price_record = split_product(
        product,
        chain_id="7290661400001",
        store_id="18",
    )

    assert product_record is None

    assert store_product_record == StoreProductRecord(
        chain_id="7290661400001",
        store_id="18",
        item_code="PRODUCE001",
        name="Tomatoes",
        manufacturer="Test Farm",
        manufacturer_country="Israel",
        item_type=0,
    )

    assert price_record == PriceRecord(
        chain_id="7290661400001",
        store_id="18",
        item_code="PRODUCE001",
        price=Decimal("8.90"),
        unit_price=Decimal("8.90"),
        quantity=Decimal("2"),
        unit_qty="kg",
        unit_measure="kg",
        weighted=True,
        package_quantity=3,
        allow_discount=False,
        status="Active",
        price_update_time=None,
        last_sale_datetime=None,
    )


def test_split_promotion_flattens_groups_and_items():
    item1 = PromotionItem(
        chain_id="xml-chain",
        promotion_id="PROMO1",
        store_id="xml-store",
        group_id="GROUP1",
        item_code="1234567890123",
        item_type=1,
        reward_type=1,
        min_qty=Decimal("2"),
        max_qty=Decimal("10"),
        discount_rate=Decimal("20"),
        discounted_price=Decimal("8.00"),
        discounted_price_per_mida=Decimal("8.00"),
        is_weighted=False,
    )

    item2 = PromotionItem(
        chain_id="xml-chain",
        promotion_id="PROMO1",
        store_id="xml-store",
        group_id="GROUP1",
        item_code="4567890123456",
        item_type=1,
        reward_type=1,
        min_qty=Decimal("1"),
        max_qty=None,
        discount_rate=None,
        discounted_price=Decimal("5.00"),
        discounted_price_per_mida=None,
        is_weighted=False,
    )

    item3 = PromotionItem(
        chain_id="xml-chain",
        promotion_id="PROMO1",
        store_id="xml-store",
        group_id="GROUP2",
        item_code="INTERNAL001",
        item_type=0,
        reward_type=2,
        min_qty=None,
        max_qty=None,
        discount_rate=Decimal("10"),
        discounted_price=None,
        discounted_price_per_mida=None,
        is_weighted=True,
    )

    group1 = PromotionGroup(
        chain_id="xml-chain",
        promotion_id="PROMO1",
        store_id="xml-store",
        group_id="GROUP1",
        min_purchase_amount=Decimal("20.00"),
        discount_type="PERCENT",
        items=[item1, item2],
    )

    group2 = PromotionGroup(
        chain_id="xml-chain",
        promotion_id="PROMO1",
        store_id="xml-store",
        group_id="GROUP2",
        min_purchase_amount=None,
        discount_type="FIXED",
        items=[item3],
    )

    promotion = Promotion(
        chain_id="xml-chain",
        promotion_id="PROMO1",
        store_id="xml-store",
        description="Test promotion",
        start_datetime=None,
        end_datetime=None,
        start_hour=None,
        end_hour=None,
        promotion_days=None,
        update_time=None,
        club_id=None,
        is_gift_item=None,
        additional_is_coupon=None,
        allow_multiple_discounts=None,
        redemption_limit=None,
        min_no_of_items_offered=None,
        additional_restrictions=None,
        remarks=None,
        groups=[group1, group2],
    )

    result_promotion, groups, items = split_promotion(
        promotion,
        chain_id="canonical-chain",
        store_id="18",
    )

    assert result_promotion is promotion
    assert groups == [group1, group2]
    assert items == [item1, item2, item3]

    assert promotion.chain_id == "canonical-chain"
    assert promotion.store_id == "18"

    assert all(group.chain_id == "canonical-chain" for group in groups)
    assert all(group.store_id == "18" for group in groups)

    assert all(item.chain_id == "canonical-chain" for item in items)
    assert all(item.store_id == "18" for item in items)


def test_split_promotion_with_no_groups():
    promotion = Promotion(
        chain_id="xml-chain",
        promotion_id="PROMO1",
        store_id="xml-store",
        description="Empty promotion",
        start_datetime=None,
        end_datetime=None,
        start_hour=None,
        end_hour=None,
        promotion_days=None,
        update_time=None,
        club_id=None,
        is_gift_item=None,
        additional_is_coupon=None,
        allow_multiple_discounts=None,
        redemption_limit=None,
        min_no_of_items_offered=None,
        additional_restrictions=None,
        remarks=None,
        groups=[],
    )

    result_promotion, groups, items = split_promotion(
        promotion,
        chain_id="canonical-chain",
        store_id="18",
    )

    assert result_promotion is promotion
    assert groups == []
    assert items == []

    assert promotion.chain_id == "canonical-chain"
    assert promotion.store_id == "18"