import pytest
from decimal import Decimal
from lxml import etree
from datetime import datetime
from parsers.xml import MachseneiXmlParser


@pytest.fixture
def parser():
    return MachseneiXmlParser()


def make_xml(content="", section="Items", sub_chain_id="001", store_id="018"):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Root>
    <ChainID>7290661400001</ChainID>
    <SubChainID>{sub_chain_id}</SubChainID>
    <StoreID>{store_id}</StoreID>
    <BikoretNo>0</BikoretNo>
    <{section}>
        {content}
    </{section}>
</Root>
""".encode("utf-8")


def real_item_xml(
    item_code="50000574438",
    name="חטיף לחתול מעדני הים",
    price="12.9",
    unit="גרם 100",
    weighted="0",
    allow_discount="0",
):
    return f"""
<Item>
    <PriceUpdateTime>2025-07-10T11:06:51.000</PriceUpdateTime>
    <ItemCode>{item_code}</ItemCode>
    <LastSaleDateTime>2026-07-29T09:57:15.000</LastSaleDateTime>
    <ItemType>0</ItemType>
    <ItemName>{name}</ItemName>
    <ManufactureName>נסטלה פורינה פטקר ארצות הברית</ManufactureName>
    <ManufactureCountry>US</ManufactureCountry>
    <ManufactureItemDescription>
        חטיף לחתול Party Mix מעדני הים קראנץ'
    </ManufactureItemDescription>
    <UnitQty>גרם</UnitQty>
    <Quantity>60</Quantity>
    <UnitOfMeasure>{unit}</UnitOfMeasure>
    <bIsWeighted>{weighted}</bIsWeighted>
    <QtyInPackage>1</QtyInPackage>
    <ItemPrice>{price}</ItemPrice>
    <UnitOfMeasurePrice>21.5</UnitOfMeasurePrice>
    <AllowDiscount>{allow_discount}</AllowDiscount>
    <ItemStatus />
</Item>
"""

def real_promo_xml():
    return """
<Promotion>
    <PromotionUpdateTime>2026-08-11T12:04:21.000</PromotionUpdateTime>
    <AllowMultipleDiscounts>0</AllowMultipleDiscounts>
    <PromotionID>1462415</PromotionID>
    <PromotionDescription>*היינקן סליק בירה 330מ"ל פחית ב4.20ש מוגבל 4 יח'</PromotionDescription>
    <PromotionStartDateTime>2026-08-16T00:00:00.000</PromotionStartDateTime>
    <PromotionEndDateTime>2026-08-21T00:00:00.000</PromotionEndDateTime>
    <PromotionStartHour/>
    <PromotionEndHour/>
    <PromotionDays/>
    <RedemptionLimit>4</RedemptionLimit>
    <MinNoOfItemOffered>10</MinNoOfItemOffered>
    <ClubID>0</ClubID>
    <IsGiftItem>4</IsGiftItem>
    <AdditionalIsCoupon>0</AdditionalIsCoupon>
    <AdditionalRestrictions/>
    <Remarks> </Remarks>

    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <MinPurchaseAmount>0</MinPurchaseAmount>
            <DiscountType/>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>7290008464598</ItemCode>
                    <ItemType>1</ItemType>
                    <RewardType>3</RewardType>
                    <MinQty>1</MinQty>
                    <MaxQty/>
                    <DiscountRate>52.44</DiscountRate>
                    <DiscountedPrice>4.2</DiscountedPrice>
                    <DiscountedPricePerMida>1.18</DiscountedPricePerMida>
                    <bIsWeighted>0</bIsWeighted>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""


def test_parse_real_price_item(parser):
    xml = make_xml(real_item_xml())
    products = parser.parse_price_file(xml)
    assert len(products) == 1
    product = products[0]
    assert product.chain_id == "7290661400001"
    assert product.sub_chain_id == "001"
    assert product.store_id == "018"
    assert product.item_code == "50000574438"
    assert product.name == "חטיף לחתול מעדני הים"
    assert product.price == Decimal("12.9")
    assert product.unit_price == Decimal("21.5")
    assert product.quantity == Decimal("60")
    assert product.unit_qty == "גרם"
    assert product.unit_measure == "גרם 100"
    assert product.manufacturer == "נסטלה פורינה פטקר ארצות הברית"
    assert product.manufacturer_country == "US"
    assert product.weighted is False
    assert product.allow_discount is False


def test_parse_multiple_items(parser):
    xml = make_xml(real_item_xml(item_code="111") + real_item_xml(item_code="222"))
    products = parser.parse_price_file(xml)
    assert len(products) == 2
    assert [p.item_code for p in products] == ["111", "222"]


def test_parse_empty_items_returns_empty_list(parser):
    xml = make_xml()
    products = parser.parse_price_file(xml)
    assert products == []


def test_parse_preserves_hebrew_text(parser):
    xml = make_xml(real_item_xml())
    product = parser.parse_price_file(xml)[0]
    assert "חתול" in product.name


def test_parse_missing_price_defaults(parser):
    xml = make_xml(real_item_xml(price=""))
    product = parser.parse_price_file(xml)[0]
    assert product.price == Decimal("0")


def test_parse_missing_name(parser):
    xml = make_xml(real_item_xml(name=""))
    product = parser.parse_price_file(xml)[0]
    assert product.name == ""


def test_parse_missing_root_metadata(parser):
    xml = b"""
<Root>
    <Items>
        <Item>
            <ItemCode>123</ItemCode>
            <ItemPrice>5</ItemPrice>
        </Item>
    </Items>
</Root>
"""
    products = parser.parse_price_file(xml)
    assert products[0].chain_id is None
    assert products[0].store_id is None


def test_invalid_xml_raises(parser):
    with pytest.raises(etree.XMLSyntaxError):
        parser.parse_price_file(b"<Root><Items><Item>")


@pytest.mark.parametrize("price", ["7,90", " ", "abc"])
def test_invalid_price_is_skipped(parser, price):
    xml = make_xml(real_item_xml(price=price))
    products = parser.parse_price_file(xml)
    assert products == []


def test_invalid_item_is_skipped_and_valid_item_is_parsed(parser):
    xml = make_xml(
        real_item_xml(item_code="111", price="abc")
        + real_item_xml(item_code="222", price="10.50")
    )

    products = parser.parse_price_file(xml)

    assert len(products) == 1
    assert products[0].item_code == "222"
    assert products[0].price == Decimal("10.50")


# ---- boolean conversions ----


def test_parse_weighted_item(parser):
    xml = make_xml(real_item_xml(weighted="1"))
    product = parser.parse_price_file(xml)[0]
    assert product.weighted is True


def test_parse_discount_allowed(parser):
    xml = make_xml(real_item_xml(allow_discount="1"))
    product = parser.parse_price_file(xml)[0]
    assert product.allow_discount is True


# ---- additional price fields ----

def test_parse_price_item_additional_fields(parser):
    xml = make_xml(real_item_xml())
    product = parser.parse_price_file(xml)[0]

    assert product.price_update_time == datetime.fromisoformat(
        "2025-07-10T11:06:51.000"
    )
    assert product.last_sale_datetime == datetime.fromisoformat(
        "2026-07-29T09:57:15.000"
    )
    assert product.item_type == 0
    assert product.package_quantity == 1
    assert product.status is None


def test_parse_item_type_one(parser):
    xml = make_xml(
        real_item_xml()
        .replace("<ItemType>0</ItemType>", "<ItemType>1</ItemType>")
    )

    product = parser.parse_price_file(xml)[0]

    assert product.item_type == 1


def test_parse_missing_item_type(parser):
    item = real_item_xml().replace("<ItemType>0</ItemType>", "")
    xml = make_xml(item)

    product = parser.parse_price_file(xml)[0]

    assert product.item_type is None


def test_parse_missing_package_quantity(parser):
    item = real_item_xml().replace("<QtyInPackage>1</QtyInPackage>", "")
    xml = make_xml(item)

    product = parser.parse_price_file(xml)[0]

    assert product.package_quantity is None


def test_parse_package_quantity_zero(parser):
    item = real_item_xml().replace(
        "<QtyInPackage>1</QtyInPackage>",
        "<QtyInPackage>0</QtyInPackage>",
    )
    xml = make_xml(item)

    product = parser.parse_price_file(xml)[0]

    assert product.package_quantity == 0


# ---- datetime conversions ----


def test_parse_datetime_valid(parser):
    result = parser.parse_datetime("2026-07-29T09:57:15.000")

    assert result == datetime.fromisoformat("2026-07-29T09:57:15.000")


@pytest.mark.parametrize("value", [None, ""])
def test_parse_datetime_missing_value(parser, value):
    assert parser.parse_datetime(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "0000-00-00 00:00:00",
        "not-a-date",
        "2026-99-99T99:99:99",
    ],
)
def test_parse_datetime_invalid_value(parser, value):
    assert parser.parse_datetime(value) is None


# ---- decimal conversions ----


@pytest.mark.parametrize(
    "value, expected",
    [
        ("12.90", Decimal("12.90")),
        ("0", Decimal("0")),
        ("", Decimal("0")),
        (None, Decimal("0")),
    ],
)
def test_parse_decimal_valid_and_missing(parser, value, expected):
    assert parser.parse_decimal(value, "ItemPrice") == expected


@pytest.mark.parametrize("value", ["abc", "7,90", "not-a-number"])
def test_parse_decimal_invalid_value(parser, value):
    with pytest.raises(ValueError, match="Invalid ItemPrice format"):
        parser.parse_decimal(value, "ItemPrice")


# ---- optional decimal conversions ----


@pytest.mark.parametrize(
    "value, expected",
    [
        ("12.90", Decimal("12.90")),
        ("0", Decimal("0")),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_parse_optional_decimal(parser, value, expected):
    assert parser.parse_optional_decimal(value) == expected

# ---- promotion parsing ----


def test_parse_real_promotion(parser):
    xml = make_xml(
        real_promo_xml(),
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.chain_id == "7290661400001"
    assert promotion.promotion_id == "1462415"
    assert promotion.store_id == "097"

    assert promotion.description == (
        '*היינקן סליק בירה 330מ"ל פחית ב4.20ש מוגבל 4 יח\''
    )

    assert promotion.start_datetime == datetime.fromisoformat(
        "2026-08-16T00:00:00.000"
    )
    assert promotion.end_datetime == datetime.fromisoformat(
        "2026-08-21T00:00:00.000"
    )
    assert promotion.update_time == datetime.fromisoformat(
        "2026-08-11T12:04:21.000"
    )

    assert promotion.start_hour is None
    assert promotion.end_hour is None
    assert promotion.promotion_days is None

    assert promotion.redemption_limit == 4
    assert promotion.min_no_of_items_offered == 10

    assert promotion.club_id == "0"
    assert promotion.is_gift_item == "4"

    assert promotion.additional_is_coupon is False
    assert promotion.allow_multiple_discounts is False

    assert promotion.additional_restrictions is None
    assert promotion.remarks is None


def test_parse_promotion_group(parser):
    xml = make_xml(
        real_promo_xml(),
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotion = parser.parse_promo_file(xml)[0]

    assert len(promotion.groups) == 1

    group = promotion.groups[0]

    assert group.chain_id == "7290661400001"
    assert group.promotion_id == "1462415"
    assert group.store_id == "097"
    assert group.group_id == "1"

    assert group.min_purchase_amount == Decimal("0")
    assert group.discount_type is None


def test_parse_promotion_item(parser):
    xml = make_xml(
        real_promo_xml(),
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotion = parser.parse_promo_file(xml)[0]
    group = promotion.groups[0]

    assert len(group.items) == 1

    item = group.items[0]

    assert item.chain_id == "7290661400001"
    assert item.promotion_id == "1462415"
    assert item.store_id == "097"
    assert item.group_id == "1"

    assert item.item_code == "7290008464598"
    assert item.item_type == 1
    assert item.reward_type == 3

    assert item.min_qty == Decimal("1")
    assert item.max_qty is None
    assert item.discount_rate == Decimal("52.44")
    assert item.discounted_price == Decimal("4.2")
    assert item.discounted_price_per_mida == Decimal("1.18")

    assert item.is_weighted is False

# ---- promotion hierarchy ----


def test_parse_multiple_promotion_groups_and_items(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>

    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <MinPurchaseAmount>10</MinPurchaseAmount>
            <DiscountType>1</DiscountType>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>111</ItemCode>
                    <ItemType>1</ItemType>
                    <RewardType>2</RewardType>
                    <MinQty>1</MinQty>
                    <MaxQty>2</MaxQty>
                    <DiscountRate>10</DiscountRate>
                    <DiscountedPrice>9</DiscountedPrice>
                    <DiscountedPricePerMida>9</DiscountedPricePerMida>
                    <bIsWeighted>0</bIsWeighted>
                </PromotionItem>
                <PromotionItem>
                    <ItemCode>222</ItemCode>
                    <ItemType>0</ItemType>
                    <RewardType>3</RewardType>
                    <MinQty>2</MinQty>
                    <MaxQty>4</MaxQty>
                    <DiscountRate>20</DiscountRate>
                    <DiscountedPrice>8</DiscountedPrice>
                    <DiscountedPricePerMida>8</DiscountedPricePerMida>
                    <bIsWeighted>1</bIsWeighted>
                </PromotionItem>
            </PromotionItems>
        </Group>

        <Group>
            <GroupID>2</GroupID>
            <MinPurchaseAmount>20</MinPurchaseAmount>
            <DiscountType>2</DiscountType>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>333</ItemCode>
                    <ItemType>1</ItemType>
                    <RewardType>1</RewardType>
                    <MinQty>1</MinQty>
                    <MaxQty>1</MaxQty>
                    <DiscountRate>5</DiscountRate>
                    <DiscountedPrice>15</DiscountedPrice>
                    <DiscountedPricePerMida>15</DiscountedPricePerMida>
                    <bIsWeighted>0</bIsWeighted>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert len(promotion.groups) == 2

    group1 = promotion.groups[0]
    group2 = promotion.groups[1]

    assert group1.group_id == "1"
    assert group1.min_purchase_amount == Decimal("10")
    assert group1.discount_type == "1"
    assert len(group1.items) == 2

    assert [item.item_code for item in group1.items] == ["111", "222"]
    assert group1.items[0].is_weighted is False
    assert group1.items[1].is_weighted is True

    assert group2.group_id == "2"
    assert group2.min_purchase_amount == Decimal("20")
    assert group2.discount_type == "2"
    assert len(group2.items) == 1
    assert group2.items[0].item_code == "333"

# ---- duplicate promotion IDs ----


def test_parse_duplicate_promotion_id_merges_groups(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>
    <PromotionDescription>Test promotion</PromotionDescription>
    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <MinPurchaseAmount>10</MinPurchaseAmount>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>111</ItemCode>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>

<Promotion>
    <PromotionID>100</PromotionID>
    <PromotionDescription>Test promotion</PromotionDescription>
    <Groups>
        <Group>
            <GroupID>2</GroupID>
            <MinPurchaseAmount>20</MinPurchaseAmount>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>222</ItemCode>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.promotion_id == "100"
    assert len(promotion.groups) == 2
    assert [group.group_id for group in promotion.groups] == ["1", "2"]

    assert [group.items[0].item_code for group in promotion.groups] == [
        "111",
        "222",
    ]

# ---- duplicate promotion group IDs ----


def test_parse_duplicate_group_id_merges_items(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>

    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <MinPurchaseAmount>10</MinPurchaseAmount>
            <DiscountType>1</DiscountType>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>111</ItemCode>
                </PromotionItem>
            </PromotionItems>
        </Group>

        <Group>
            <GroupID>1</GroupID>
            <MinPurchaseAmount>999</MinPurchaseAmount>
            <DiscountType>999</DiscountType>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>222</ItemCode>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert len(promotion.groups) == 1

    group = promotion.groups[0]

    assert group.group_id == "1"

    # First group metadata is preserved.
    assert group.min_purchase_amount == Decimal("10")
    assert group.discount_type == "1"

    # Items from both occurrences are merged.
    assert len(group.items) == 2
    assert [item.item_code for item in group.items] == ["111", "222"]



# ---- malformed promotion items ----


def test_invalid_promotion_item_is_skipped_and_valid_item_is_parsed(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>
    <PromotionDescription>Test promotion</PromotionDescription>
    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <PromotionItems>

                <PromotionItem>
                    <ItemCode>111</ItemCode>
                    <RewardType>not-a-number</RewardType>
                </PromotionItem>

                <PromotionItem>
                    <ItemCode>222</ItemCode>
                    <RewardType>3</RewardType>
                </PromotionItem>

            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.promotion_id == "100"
    assert promotion.description == "Test promotion"

    assert len(promotion.groups) == 1

    group = promotion.groups[0]

    assert len(group.items) == 1
    assert group.items[0].item_code == "222"
    assert group.items[0].reward_type == 3


# ---- optional promotion fields ----


def test_parse_missing_optional_promotion_fields(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>
    <PromotionDescription></PromotionDescription>
    <PromotionStartHour></PromotionStartHour>
    <PromotionEndHour></PromotionEndHour>
    <PromotionDays></PromotionDays>
    <AdditionalRestrictions></AdditionalRestrictions>
    <Remarks>   </Remarks>

    <RedemptionLimit></RedemptionLimit>
    <MinNoOfItemOffered></MinNoOfItemOffered>

    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <MinPurchaseAmount></MinPurchaseAmount>
            <DiscountType></DiscountType>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.description == ""
    assert promotion.start_hour is None
    assert promotion.end_hour is None
    assert promotion.promotion_days is None

    assert promotion.redemption_limit is None
    assert promotion.min_no_of_items_offered is None

    assert promotion.additional_restrictions is None
    assert promotion.remarks is None

    group = promotion.groups[0]

    assert group.min_purchase_amount is None
    assert group.discount_type is None


# ---- missing identifiers ----


def test_parse_missing_promotion_id(parser):
    promo_xml = """
<Promotion>
    <PromotionDescription>Missing ID</PromotionDescription>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1
    assert promotions[0].promotion_id is None


def test_parse_missing_item_code(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>
    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <PromotionItems>
                <PromotionItem>
                    <RewardType>3</RewardType>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1
    assert len(promotions[0].groups[0].items) == 1
    assert promotions[0].groups[0].items[0].item_code is None


def test_parse_missing_group_id(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>
    <Groups>
        <Group>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>111</ItemCode>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert len(promotion.groups) == 1

    group = promotion.groups[0]

    assert group.group_id is None
    assert len(group.items) == 1
    assert group.items[0].item_code == "111"

# ---- promotion collection ----


def test_parse_multiple_promotions(parser):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>
    <PromotionDescription>First promotion</PromotionDescription>
</Promotion>

<Promotion>
    <PromotionID>200</PromotionID>
    <PromotionDescription>Second promotion</PromotionDescription>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 2
    assert [p.promotion_id for p in promotions] == ["100", "200"]


def test_parse_empty_promotions_returns_empty_list(parser):
    xml = make_xml(
        "",
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert promotions == []


def test_parse_missing_promotions_section_returns_empty_list(parser):
    xml = make_xml(
        "",
        section="Items",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert promotions == []


# ---- promotion boolean conversions ----


@pytest.mark.parametrize(
    "coupon, multiple, expected_coupon, expected_multiple",
    [
        ("0", "0", False, False),
        ("1", "0", True, False),
        ("0", "1", False, True),
        ("1", "1", True, True),
    ],
)
def test_parse_promotion_boolean_fields(
    parser,
    coupon,
    multiple,
    expected_coupon,
    expected_multiple,
):
    promo_xml = f"""
<Promotion>
    <PromotionID>100</PromotionID>
    <AdditionalIsCoupon>{coupon}</AdditionalIsCoupon>
    <AllowMultipleDiscounts>{multiple}</AllowMultipleDiscounts>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotion = parser.parse_promo_file(xml)[0]

    assert promotion.additional_is_coupon is expected_coupon
    assert promotion.allow_multiple_discounts is expected_multiple

# ---- logging behavior ----


def test_malformed_price_item_logs_warning(parser, caplog):
    xml = make_xml(
        real_item_xml(item_code="111", price="abc")
    )

    with caplog.at_level("WARNING", logger="parsers.xml"):
        products = parser.parse_price_file(xml)

    assert products == []

    assert "Skipping malformed item" in caplog.text
    assert "chain_id=7290661400001" in caplog.text
    assert "store_id=018" in caplog.text
    assert "item_code=111" in caplog.text

def test_malformed_promotion_item_logs_warning(parser, caplog):
    promo_xml = """
<Promotion>
    <PromotionID>100</PromotionID>
    <PromotionDescription>Test promotion</PromotionDescription>
    <Groups>
        <Group>
            <GroupID>1</GroupID>
            <PromotionItems>
                <PromotionItem>
                    <ItemCode>111</ItemCode>
                    <RewardType>not-a-number</RewardType>
                </PromotionItem>
            </PromotionItems>
        </Group>
    </Groups>
</Promotion>
"""

    xml = make_xml(
        promo_xml,
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    with caplog.at_level("WARNING", logger="parsers.xml"):
        promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1
    assert len(promotions[0].groups[0].items) == 0

    assert "Skipping malformed promotion item" in caplog.text
    assert "chain_id=7290661400001" in caplog.text
    assert "store_id=097" in caplog.text
    assert "promotion_id=100" in caplog.text
    assert "item_code=111" in caplog.text