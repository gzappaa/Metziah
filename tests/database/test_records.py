from decimal import Decimal
from database.records import split_promotion
from models.product import Product
from database.records import (
    PriceRecord,
    ProductRecord,
    StoreProductRecord,
    looks_like_barcode,
    split_product,
    split_promotion,
)
from models.promo import Promotion, PromotionGroup, PromotionItem


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


def test_split_product_non_barcode_preserves_all_store_product_fields():
    product = Product(
        chain_id="7290661400001",
        sub_chain_id="001",
        store_id="018",
        item_code="INTERNAL001",
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

    product_record, store_product_record, price_record = split_product(product)

    assert product_record is None

    assert store_product_record == StoreProductRecord(
        chain_id="7290661400001",
        store_id="018",
        item_code="INTERNAL001",
        name="Tomatoes",
        manufacturer="Test Farm",
        manufacturer_country="Israel",
        item_type=0,
    )

    assert price_record == PriceRecord(
        chain_id="7290661400001",
        store_id="018",
        item_code="INTERNAL001",
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
        chain_id="7290661400001",
        promotion_id="PROMO1",
        store_id="018",
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
        chain_id="7290661400001",
        promotion_id="PROMO1",
        store_id="018",
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
        chain_id="7290661400001",
        promotion_id="PROMO1",
        store_id="018",
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
        chain_id="7290661400001",
        promotion_id="PROMO1",
        store_id="018",
        group_id="GROUP1",
        min_purchase_amount=Decimal("20.00"),
        discount_type="PERCENT",
        items=[item1, item2],
    )

    group2 = PromotionGroup(
        chain_id="7290661400001",
        promotion_id="PROMO1",
        store_id="018",
        group_id="GROUP2",
        min_purchase_amount=None,
        discount_type="FIXED",
        items=[item3],
    )

    promotion = Promotion(
        chain_id="7290661400001",
        promotion_id="PROMO1",
        store_id="018",
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

    result_promotion, groups, items = split_promotion(promotion)

    assert result_promotion is promotion
    assert groups == [group1, group2]
    assert items == [item1, item2, item3]


def test_split_promotion_with_no_groups():
    promotion = Promotion(
        chain_id="7290661400001",
        promotion_id="PROMO1",
        store_id="018",
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
    )

    result_promotion, groups, items = split_promotion(promotion)

    assert result_promotion is promotion
    assert groups == []
    assert items == []