import logging
from datetime import datetime
from decimal import Decimal

import pytest
from lxml import etree

from parsers.xml import StoreXmlParser


@pytest.fixture
def parser():
    return StoreXmlParser()


# ============================================================
# Builders
# ============================================================


def make_xml(
    content="",
    section="Items",
    sub_chain_id="001",
    store_id="018",
    chain_id="7290661400001",
):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Root>
    <ChainID>{chain_id}</ChainID>
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
    """A realistic, fully populated <Item> copied from a real feed."""
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


def item_xml(**tags):
    """
    Minimal <Item>. Every keyword is a tag name; pass None to omit the tag.

        item_xml(ItemPrice="abc")      -> invalid price
        item_xml(ItemPrice=None)       -> no <ItemPrice> element at all
    """
    fields = {
        "ItemCode": "123",
        "ItemName": "Test item",
        "ItemPrice": "5.00",
    }
    fields.update(tags)

    inner = "".join(
        f"<{tag}>{value}</{tag}>"
        for tag, value in fields.items()
        if value is not None
    )

    return f"<Item>{inner}</Item>"


def real_promo_xml():
    """A realistic promotion using the explicit Groups/Group layout."""
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


def promo_xml(inner="", promotion_id="100"):
    """Minimal <Promotion>. promotion_id=None omits the ID tag entirely."""
    id_xml = (
        ""
        if promotion_id is None
        else f"<PromotionID>{promotion_id}</PromotionID>"
    )

    return f"<Promotion>{id_xml}{inner}</Promotion>"


def flat_item(code, extra=""):
    """An <Item> for the layout that has no <Groups>."""
    return f"<Item><ItemCode>{code}</ItemCode>{extra}</Item>"


def parse_promos(parser, *promotions, **xml_kwargs):
    return parser.parse_promo_file(
        make_xml(
            "".join(promotions),
            section="Promotions",
            **xml_kwargs,
        )
    )


def parse_one_promo(parser, promotion):
    promotions = parse_promos(parser, promotion)

    assert len(promotions) == 1

    return promotions[0]


# ============================================================
# Price parsing: happy path
# ============================================================


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
    assert product.price_update_time == datetime(2025, 7, 10, 11, 6, 51)
    assert product.last_sale_datetime == datetime(2026, 7, 29, 9, 57, 15)
    assert product.item_type == 0
    assert product.package_quantity == 1
    assert product.status is None


def test_parse_multiple_items_keeps_file_order(parser):
    xml = make_xml(
        real_item_xml(item_code="111")
        + real_item_xml(item_code="222")
    )

    products = parser.parse_price_file(xml)

    assert [p.item_code for p in products] == ["111", "222"]


def test_parse_empty_items_section_returns_empty_list(parser):
    assert parser.parse_price_file(make_xml()) == []


def test_price_parser_ignores_promotion_files(parser):
    xml = make_xml(
        real_promo_xml(),
        section="Promotions",
    )

    assert parser.parse_price_file(xml) == []


def test_comments_and_processing_instructions_are_ignored(parser):
    xml = make_xml(
        "<!-- a comment -->"
        + item_xml(ItemCode="111")
        + "<?some-instruction data?>"
        + item_xml(ItemCode="222")
    )

    products = parser.parse_price_file(xml)

    assert [p.item_code for p in products] == ["111", "222"]


@pytest.mark.parametrize(
    "xml_content",
    [
        b"<Root><Items><Item>",
        b"",
        b"not xml at all",
    ],
    ids=["malformed-xml", "empty-xml", "invalid-text"],
)
def test_invalid_xml_raises(parser, xml_content):
    with pytest.raises(etree.XMLSyntaxError):
        parser.parse_price_file(xml_content)

    with pytest.raises(etree.XMLSyntaxError):
        parser.parse_promo_file(xml_content)


# ============================================================
# Price parsing: root metadata
# ============================================================


def test_missing_root_metadata_is_none(parser):
    xml = (
        b"<Root><Items><Item>"
        b"<ItemCode>123</ItemCode><ItemPrice>5</ItemPrice>"
        b"</Item></Items></Root>"
    )

    product = parser.parse_price_file(xml)[0]

    assert product.chain_id is None
    assert product.sub_chain_id is None
    assert product.store_id is None


def test_root_metadata_is_stripped(parser):
    xml = make_xml(
        real_item_xml(),
        chain_id=" 7290661400001 ",
        sub_chain_id=" 001 ",
        store_id=" 018 ",
    )

    product = parser.parse_price_file(xml)[0]

    assert product.chain_id == "7290661400001"
    assert product.sub_chain_id == "001"
    assert product.store_id == "018"


@pytest.mark.parametrize(
    "tags",
    [
        ("ChainID", "SubChainID", "StoreID"),
        ("ChainId", "SubChainId", "StoreId"),
        ("chainid", "subchainid", "storeid"),
        ("CHAINID", "SUBCHAINID", "STOREID"),
    ],
)
def test_root_metadata_tags_are_case_insensitive(parser, tags):
    chain_tag, sub_chain_tag, store_tag = tags

    xml = f"""
<Root>
    <{chain_tag}>123</{chain_tag}>
    <{sub_chain_tag}>456</{sub_chain_tag}>
    <{store_tag}>789</{store_tag}>
    <Items>
        {item_xml()}
    </Items>
</Root>
""".encode()

    product = parser.parse_price_file(xml)[0]

    assert product.chain_id == "123"
    assert product.sub_chain_id == "456"
    assert product.store_id == "789"


def test_promo_file_root_metadata_is_normalized(parser):
    xml = b"""
<Root>
    <CHAINID> 123 </CHAINID>
    <StoreId> 789 </StoreId>
    <Promotions>
        <Promotion><PromotionID>1</PromotionID></Promotion>
    </Promotions>
</Root>
"""

    promotion = parser.parse_promo_file(xml)[0]

    assert promotion.chain_id == "123"
    assert promotion.store_id == "789"


# ============================================================
# Price parsing: field handling
# ============================================================


@pytest.mark.parametrize(
    "name, expected",
    [
        ("", ""),
        (None, None),
    ],
)
def test_missing_name(parser, name, expected):
    xml = make_xml(item_xml(ItemName=name))

    assert parser.parse_price_file(xml)[0].name == expected


@pytest.mark.parametrize(
    "price, expected",
    [
        ("12.90", Decimal("12.90")),
        ("כ12.90", Decimal("12.90")),
        ("", Decimal("0")),
        (" ", Decimal("0")),
        (None, Decimal("0")),
    ],
)
def test_price_values(parser, price, expected):
    xml = make_xml(item_xml(ItemPrice=price))

    assert parser.parse_price_file(xml)[0].price == expected


@pytest.mark.parametrize("field", ["UnitOfMeasurePrice", "Quantity"])
def test_missing_decimal_fields_default_to_zero(parser, field):
    xml = make_xml(item_xml(**{field: None}))

    product = parser.parse_price_file(xml)[0]

    assert product.unit_price == Decimal("0")
    assert product.quantity == Decimal("0")


@pytest.mark.parametrize(
    "field", ["ItemPrice", "UnitOfMeasurePrice", "Quantity"]
)
@pytest.mark.parametrize("value", ["7,90", "abc"])
def test_item_with_invalid_decimal_field_is_skipped(
    parser,
    field,
    value,
):
    xml = make_xml(item_xml(**{field: value}))

    assert parser.parse_price_file(xml) == []


def test_invalid_item_is_skipped_and_valid_item_is_parsed(
    parser,
    caplog,
):
    xml = make_xml(
        item_xml(ItemCode="111", ItemPrice="abc")
        + item_xml(ItemCode="222", ItemPrice="10.50")
    )

    with caplog.at_level(logging.WARNING, logger="parsers.xml"):
        products = parser.parse_price_file(xml)

    assert [p.item_code for p in products] == ["222"]
    assert products[0].price == Decimal("10.50")

    assert "Skipping malformed item" in caplog.text
    assert "item_code=111" in caplog.text
    assert "store_id=018" in caplog.text


@pytest.mark.parametrize(
    "tag, attribute",
    [
        ("bIsWeighted", "weighted"),
        ("AllowDiscount", "allow_discount"),
    ],
)
@pytest.mark.parametrize(
    "value, expected",
    [
        ("1", True),
        ("0", False),
        ("", False),
        ("true", False),
        (None, False),
    ],
)
def test_boolean_flags_are_true_only_for_one(
    parser,
    tag,
    attribute,
    value,
    expected,
):
    xml = make_xml(item_xml(**{tag: value}))

    product = parser.parse_price_file(xml)[0]

    assert getattr(product, attribute) is expected


@pytest.mark.parametrize(
    "tag, attribute",
    [
        ("ItemType", "item_type"),
        ("QtyInPackage", "package_quantity"),
    ],
)
@pytest.mark.parametrize(
    "value, expected",
    [
        ("0", 0),
        ("1", 1),
        (None, None),
        ("", None),
        ("לא ידוע", None),
    ],
)
def test_integer_fields(parser, tag, attribute, value, expected):
    xml = make_xml(item_xml(**{tag: value}))

    product = parser.parse_price_file(xml)[0]

    assert getattr(product, attribute) == expected


@pytest.mark.parametrize("tag", ["PriceUpdateTime", "LastSaleDateTime"])
def test_invalid_item_datetimes_become_none_without_skipping_item(
    parser,
    tag,
):
    xml = make_xml(item_xml(**{tag: "0000-00-00 00:00:00"}))

    products = parser.parse_price_file(xml)

    assert len(products) == 1
    assert products[0].price_update_time is None
    assert products[0].last_sale_datetime is None


def test_optional_text_fields_missing_are_none(parser):
    product = parser.parse_price_file(make_xml(item_xml()))[0]

    assert product.manufacturer is None
    assert product.manufacturer_country is None
    assert product.unit_qty is None
    assert product.unit_measure is None


@pytest.mark.parametrize(
    "status, expected",
    [
        ("active", "active"),
        ("", None),
        (None, None),
    ],
)
def test_item_status(parser, status, expected):
    xml = make_xml(item_xml(ItemStatus=status))

    assert parser.parse_price_file(xml)[0].status == expected


# ============================================================
# Tag normalization
# ============================================================


def test_normalize_xml_tags_lowercases_tags_only():
    root = etree.fromstring(
        b'<Root Attr="Keep"><!-- note --><Child>Text</Child>'
        b"<?pi data?></Root>"
    )

    StoreXmlParser.normalize_xml_tags(root)

    assert root.tag == "root"
    assert root[1].tag == "child"
    assert root.get("Attr") == "Keep"
    assert root[1].text == "Text"


# ============================================================
# Scalar converters
# ============================================================


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-07-29T09:57:15.000", datetime(2026, 7, 29, 9, 57, 15)),
        (" 2026-07-29T09:57:15 ", datetime(2026, 7, 29, 9, 57, 15)),
        ("2026-07-29 09:57:15", datetime(2026, 7, 29, 9, 57, 15)),
        ("2026-07-29", datetime(2026, 7, 29)),
        (None, None),
        ("", None),
        ("   ", None),
        ("0000-00-00 00:00:00", None),
        ("not-a-date", None),
        ("2026-99-99T99:99:99", None),
    ],
)
def test_parse_datetime(parser, value, expected):
    assert parser.parse_datetime(value) == expected


@pytest.mark.parametrize(
    "date_value, hour_value, expected",
    [
        (None, None, None),
        ("", "10:00:00", None),
        ("   ", "10:00:00", None),
        ("2026-01-01", None, datetime(2026, 1, 1)),
        ("2026-01-01", "", datetime(2026, 1, 1)),
        ("2026-01-01", "   ", datetime(2026, 1, 1)),
        ("2026-01-01", "12:30", datetime(2026, 1, 1, 12, 30)),
        ("2026-01-01", "12:30:45", datetime(2026, 1, 1, 12, 30, 45)),
        (
            "2026-01-01",
            "12:30:45.5",
            datetime(2026, 1, 1, 12, 30, 45, 500000),
        ),
        ("2026-01-01", " 08:00:00 ", datetime(2026, 1, 1, 8, 0)),
        (" 2026-01-01 ", "08:00:00", datetime(2026, 1, 1, 8, 0)),
        ("2026-01-01", "25:00:00", None),
        ("01/01/2026", None, None),
        ("garbage", "12:00:00", None),
    ],
)
def test_parse_date_and_hour(parser, date_value, hour_value, expected):
    assert parser.parse_date_and_hour(date_value, hour_value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0", 0),
        ("1", 1),
        ("42", 42),
        ("-3", -3),
        (" 7 ", 7),
        ("", None),
        ("   ", None),
        (None, None),
        ("5.0", None),
        ("לא ידוע", None),
        ("abc", None),
    ],
)
def test_parse_int(parser, value, expected):
    assert parser.parse_int(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("12.90", Decimal("12.90")),
        ("0", Decimal("0")),
        ("", Decimal("0")),
        ("   ", Decimal("0")),
        (None, Decimal("0")),
        ("כ12.90", Decimal("12.90")),
        (" כ12.90 ", Decimal("12.90")),
    ],
)
def test_parse_decimal_valid_and_missing(parser, value, expected):
    assert parser.parse_decimal(value, "ItemPrice") == expected


@pytest.mark.parametrize(
    "value",
    ["abc", "7,90", "not-a-number", "כ"],
)
def test_parse_decimal_invalid_value_names_the_field(parser, value):
    with pytest.raises(
        ValueError,
        match="Invalid ItemPrice format",
    ):
        parser.parse_decimal(value, "ItemPrice")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("12.90", Decimal("12.90")),
        ("0", Decimal("0")),
        ("", None),
        ("   ", None),
        (None, None),
        ("abc", None),
        ("כ12.90", Decimal("12.90")),
        (" כ12.90 ", Decimal("12.90")),
        ("כ", None),
        ("לא ידוע", None),
    ],
)
def test_parse_optional_decimal(parser, value, expected):
    assert parser.parse_optional_decimal(value) == expected


# ============================================================
# Promotion parsing: real feed, explicit Groups/Group layout
# ============================================================


@pytest.fixture
def real_promotion(parser):
    xml = make_xml(
        real_promo_xml(),
        section="Promotions",
        sub_chain_id="003",
        store_id="097",
    )

    promotions = parser.parse_promo_file(xml)

    assert len(promotions) == 1

    return promotions[0]


def test_parse_real_promotion(real_promotion):
    promotion = real_promotion

    assert promotion.chain_id == "7290661400001"
    assert promotion.promotion_id == "1462415"
    assert promotion.store_id == "097"

    assert promotion.description == (
        '*היינקן סליק בירה 330מ"ל פחית ב4.20ש מוגבל 4 יח\''
    )

    assert promotion.start_datetime == datetime(2026, 8, 16)
    assert promotion.end_datetime == datetime(2026, 8, 21)
    assert promotion.update_time == datetime(2026, 8, 11, 12, 4, 21)

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


def test_parse_real_promotion_group(real_promotion):
    assert len(real_promotion.groups) == 1

    group = real_promotion.groups[0]

    assert group.chain_id == "7290661400001"
    assert group.promotion_id == "1462415"
    assert group.store_id == "097"
    assert group.group_id == "1"
    assert group.min_purchase_amount == Decimal("0")
    assert group.discount_type is None


def test_parse_real_promotion_item(real_promotion):
    group = real_promotion.groups[0]

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


def test_promo_file_without_promotions_returns_empty_list(parser):
    assert parser.parse_promo_file(make_xml(section="Promotions")) == []


def test_promotion_without_groups_or_items_has_no_groups(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml("<PromotionDescription>Bare</PromotionDescription>"),
    )

    assert promotion.description == "Bare"
    assert promotion.groups == []


# ============================================================
# Promotion parsing: promotion-level fields
# ============================================================


def test_promotion_optional_text_fields_are_preserved(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
            <PromotionStartHour>08:00:00</PromotionStartHour>
            <PromotionEndHour>22:00:00</PromotionEndHour>
            <PromotionDays>1,2,3</PromotionDays>
            <AdditionalRestrictions>Members only</AdditionalRestrictions>
            <Remarks>  see store  </Remarks>
            """
        ),
    )

    assert promotion.start_hour == "08:00:00"
    assert promotion.end_hour == "22:00:00"
    assert promotion.promotion_days == "1,2,3"
    assert promotion.additional_restrictions == "Members only"
    assert promotion.remarks == "see store"


@pytest.mark.parametrize(
    "tag, attribute",
    [
        ("AdditionalIsCoupon", "additional_is_coupon"),
        ("AllowMultipleDiscounts", "allow_multiple_discounts"),
    ],
)
@pytest.mark.parametrize(
    "value, expected",
    [("1", True), ("0", False), (None, False)],
)
def test_promotion_boolean_flags(parser, tag, attribute, value, expected):
    inner = "" if value is None else f"<{tag}>{value}</{tag}>"

    promotion = parse_one_promo(parser, promo_xml(inner))

    assert getattr(promotion, attribute) is expected


def test_invalid_redemption_limit_becomes_none(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml("<RedemptionLimit>unlimited</RedemptionLimit>"),
    )

    assert promotion.redemption_limit is None


@pytest.mark.parametrize(
    "tag",
    [
        "MinNoOfItemOffered",
        "MinNoOfItemsOffered",
        "MinNoOfItemOfered",
    ],
)
def test_min_no_of_items_offered_accepts_typo_variants(parser, tag):
    promotion = parse_one_promo(
        parser,
        promo_xml(f"<{tag}>99999</{tag}>"),
    )

    assert promotion.min_no_of_items_offered == 99999


def test_min_no_of_items_offered_missing_is_none(parser):
    promotion = parse_one_promo(parser, promo_xml())

    assert promotion.min_no_of_items_offered is None


@pytest.mark.parametrize(
    "tag",
    [
        "PromotionID",
        "PromotionId",
        "promotionid",
        "Promotionid",
        "PROMOTIONID",
    ],
)
def test_promotion_id_tag_is_case_insensitive(parser, tag):
    promotion = parse_one_promo(
        parser,
        f"<Promotion><{tag}>12345</{tag}></Promotion>",
    )

    assert promotion.promotion_id == "12345"


@pytest.mark.parametrize("promotion_id", [None, ""])
def test_promotion_without_id_is_skipped(parser, caplog, promotion_id):
    with caplog.at_level(logging.WARNING, logger="parsers.xml"):
        promotions = parse_promos(
            parser,
            promo_xml(
                "<PromotionDescription>No id</PromotionDescription>",
                promotion_id=promotion_id,
            ),
            promo_xml(promotion_id="200"),
        )

    assert [p.promotion_id for p in promotions] == ["200"]
    assert "missing promotion_id" in caplog.text
    assert "No id" in caplog.text


# ============================================================
# Promotion parsing: start / end / update times
# ============================================================


def test_start_and_end_datetime_are_preferred_over_date_and_hour(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
            <PromotionStartDateTime>2026-08-16T00:00:00</PromotionStartDateTime>
            <PromotionEndDateTime>2026-08-21T00:00:00</PromotionEndDateTime>
            <PromotionStartDate>2020-01-01</PromotionStartDate>
            <PromotionEndDate>2020-12-31</PromotionEndDate>
            """
        ),
    )

    assert promotion.start_datetime == datetime(2026, 8, 16)
    assert promotion.end_datetime == datetime(2026, 8, 21)


def test_date_and_hour_fallback(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
            <PromotionStartDate>2026-01-01</PromotionStartDate>
            <PromotionStartHour>00:00:00</PromotionStartHour>
            <PromotionEndDate>2026-12-31</PromotionEndDate>
            <PromotionEndHour>23:59:00</PromotionEndHour>
            """
        ),
    )

    assert promotion.start_datetime == datetime(2026, 1, 1)
    assert promotion.end_datetime == datetime(2026, 12, 31, 23, 59)


def test_date_without_hour_falls_back_to_midnight(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
            <PromotionStartDate>2026-01-01</PromotionStartDate>
            <PromotionEndDate>2026-01-31</PromotionEndDate>
            """
        ),
    )

    assert promotion.start_datetime == datetime(2026, 1, 1)
    assert promotion.end_datetime == datetime(2026, 1, 31)


def test_invalid_start_datetime_falls_back_to_date_and_hour(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
            <PromotionStartDateTime>garbage</PromotionStartDateTime>
            <PromotionStartDate>2026-03-01</PromotionStartDate>
            <PromotionStartHour>09:00:00</PromotionStartHour>
            """
        ),
    )

    assert promotion.start_datetime == datetime(2026, 3, 1, 9, 0)


def test_missing_dates_are_none(parser):
    promotion = parse_one_promo(parser, promo_xml())

    assert promotion.start_datetime is None
    assert promotion.end_datetime is None
    assert promotion.update_time is None


def test_update_time_falls_back_to_update_date(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            "<PromotionUpdateDate>2025-12-31 14:24:00</PromotionUpdateDate>"
        ),
    )

    assert promotion.update_time == datetime(2025, 12, 31, 14, 24)


def test_update_time_is_preferred_over_update_date(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
            <PromotionUpdateTime>2026-01-02T03:04:05</PromotionUpdateTime>
            <PromotionUpdateDate>2020-01-01 00:00:00</PromotionUpdateDate>
            """
        ),
    )

    assert promotion.update_time == datetime(2026, 1, 2, 3, 4, 5)


# ============================================================
# Promotion hierarchy: explicit Groups/Group layout
# ============================================================


def test_parse_multiple_groups_and_items(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<Groups>
    <Group>
        <GroupID>1</GroupID>
        <MinPurchaseAmount>10</MinPurchaseAmount>
        <DiscountType>1</DiscountType>
        <PromotionItems>
            <PromotionItem>
                <ItemCode>111</ItemCode>
                <bIsWeighted>0</bIsWeighted>
            </PromotionItem>
            <PromotionItem>
                <ItemCode>222</ItemCode>
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
            </PromotionItem>
        </PromotionItems>
    </Group>
</Groups>
"""
        ),
    )

    group1, group2 = promotion.groups

    assert group1.group_id == "1"
    assert group1.min_purchase_amount == Decimal("10")
    assert group1.discount_type == "1"
    assert [i.item_code for i in group1.items] == ["111", "222"]
    assert [i.is_weighted for i in group1.items] == [False, True]

    assert group2.group_id == "2"
    assert group2.min_purchase_amount == Decimal("20")
    assert group2.discount_type == "2"
    assert [i.item_code for i in group2.items] == ["333"]


def test_group_without_id_is_normalized_to_group_one(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<Groups>
    <Group>
        <PromotionItems>
            <PromotionItem><ItemCode>111</ItemCode></PromotionItem>
        </PromotionItems>
    </Group>
    <Group>
        <GroupID></GroupID>
        <PromotionItems>
            <PromotionItem><ItemCode>222</ItemCode></PromotionItem>
        </PromotionItems>
    </Group>
</Groups>
"""
        ),
    )

    assert len(promotion.groups) == 1
    assert promotion.groups[0].group_id == "1"
    assert [i.item_code for i in promotion.groups[0].items] == [
        "111",
        "222",
    ]


def test_group_with_invalid_min_purchase_amount_has_none(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<Groups>
    <Group>
        <GroupID>1</GroupID>
        <MinPurchaseAmount>abc</MinPurchaseAmount>
        <DiscountType/>
    </Group>
</Groups>
"""
        ),
    )

    group = promotion.groups[0]

    assert group.min_purchase_amount is None
    assert group.discount_type is None
    assert group.items == []


def test_empty_groups_element_falls_back_to_direct_items(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            "<Groups></Groups>"
            f"<PromotionItems>{flat_item('111')}</PromotionItems>"
        ),
    )

    assert [g.group_id for g in promotion.groups] == ["1"]
    assert [i.item_code for i in promotion.groups[0].items] == ["111"]


def test_duplicate_promotion_id_merges_groups_and_keeps_first_values(
    parser,
):
    def promo(group_id, item_code, description):
        return promo_xml(
            f"""
<PromotionDescription>{description}</PromotionDescription>
<Groups>
    <Group>
        <GroupID>{group_id}</GroupID>
        <PromotionItems>
            <PromotionItem><ItemCode>{item_code}</ItemCode></PromotionItem>
        </PromotionItems>
    </Group>
</Groups>
"""
        )

    promotions = parse_promos(
        parser,
        promo("1", "111", "First"),
        promo("2", "222", "Second"),
    )

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.description == "First"
    assert [g.group_id for g in promotion.groups] == ["1", "2"]
    assert [g.items[0].item_code for g in promotion.groups] == [
        "111",
        "222",
    ]


def test_duplicate_group_id_merges_items_and_keeps_first_group_values(
    parser,
):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<Groups>
    <Group>
        <GroupID>1</GroupID>
        <MinPurchaseAmount>10</MinPurchaseAmount>
        <DiscountType>1</DiscountType>
        <PromotionItems>
            <PromotionItem><ItemCode>111</ItemCode></PromotionItem>
        </PromotionItems>
    </Group>
    <Group>
        <GroupID>1</GroupID>
        <MinPurchaseAmount>999</MinPurchaseAmount>
        <DiscountType>999</DiscountType>
        <PromotionItems>
            <PromotionItem><ItemCode>222</ItemCode></PromotionItem>
        </PromotionItems>
    </Group>
</Groups>
"""
        ),
    )

    assert len(promotion.groups) == 1

    group = promotion.groups[0]

    assert group.min_purchase_amount == Decimal("10")
    assert group.discount_type == "1"
    assert [i.item_code for i in group.items] == ["111", "222"]


def test_promotion_item_with_invalid_number_is_kept_with_none(parser):
    """
    parse_int() swallows bad values, so the item is NOT dropped: only the
    unparseable field becomes None. (Items are only skipped when an
    unexpected exception escapes -- see the error-isolation tests below.)
    """
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
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
"""
        ),
    )

    items = promotion.groups[0].items

    assert [i.item_code for i in items] == ["111", "222"]
    assert [i.reward_type for i in items] == [None, 3]


def test_group_and_item_tags_are_case_insensitive(parser):
    promotion = parse_one_promo(
        parser,
        """
<Promotion>
    <promotionid>100</promotionid>
    <GROUPS>
        <gRoUp>
            <gRoUpId>1</gRoUpId>
            <PROMOTIONITEMS>
                <pRoMoTiOnItEm>
                    <iTeMcOdE>123</iTeMcOdE>
                    <iTeMtYpE>1</iTeMtYpE>
                    <rEwArDtYpE>3</rEwArDtYpE>
                </pRoMoTiOnItEm>
            </PROMOTIONITEMS>
        </gRoUp>
    </GROUPS>
</Promotion>
""",
    )

    assert promotion.promotion_id == "100"

    group = promotion.groups[0]
    item = group.items[0]

    assert group.group_id == "1"
    assert item.item_code == "123"
    assert item.item_type == 1
    assert item.reward_type == 3


# ============================================================
# Promotion hierarchy: layouts without <Groups>
# ============================================================


def test_direct_item_elements_are_normalized_into_group_one(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            "<PromotionItems>"
            + "".join(
                flat_item(code, "<ItemType>1</ItemType>")
                for code in ("111", "222", "333", "444")
            )
            + "</PromotionItems>",
            promotion_id="23",
        ),
    )

    assert len(promotion.groups) == 1

    group = promotion.groups[0]

    assert group.group_id == "1"
    assert [i.item_code for i in group.items] == [
        "111",
        "222",
        "333",
        "444",
    ]
    assert all(i.item_type == 1 for i in group.items)


def test_direct_promotion_item_elements_are_normalized_into_group_one(
    parser,
):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<PromotionItems>
    <PromotionItem>
        <ItemCode>7290103682279</ItemCode>
        <ItemType>1</ItemType>
        <RewardType>3</RewardType>
        <MinQty>2</MinQty>
        <MaxQty>2</MaxQty>
        <DiscountRate>22.93</DiscountRate>
        <DiscountedPrice>40.00</DiscountedPrice>
        <DiscountedPricePerMida>40.00</DiscountedPricePerMida>
        <bIsWeighted>0</bIsWeighted>
    </PromotionItem>
    <PromotionItem>
        <ItemCode>7290103682262</ItemCode>
    </PromotionItem>
</PromotionItems>
""",
            promotion_id="883089",
        ),
    )

    assert promotion.promotion_id == "883089"
    assert len(promotion.groups) == 1

    group = promotion.groups[0]

    assert group.group_id == "1"
    assert [i.item_code for i in group.items] == [
        "7290103682279",
        "7290103682262",
    ]
    assert group.items[0].reward_type == 3
    assert group.items[0].discounted_price == Decimal("40.00")


def test_mixed_promotion_item_and_item_elements_are_all_collected(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            "<PromotionItems>"
            + flat_item("item-1")
            + "<PromotionItem><ItemCode>promo-item-1</ItemCode></PromotionItem>"
            + flat_item("item-2")
            + "</PromotionItems>"
        ),
    )

    # <PromotionItem> elements are collected first, then <Item> elements.
    assert [i.item_code for i in promotion.groups[0].items] == [
        "promo-item-1",
        "item-1",
        "item-2",
    ]


def test_duplicate_promotion_without_groups_appends_to_group_one(parser):
    promotions = parse_promos(
        parser,
        promo_xml(f"<PromotionItems>{flat_item('111')}</PromotionItems>"),
        promo_xml(f"<PromotionItems>{flat_item('222')}</PromotionItems>"),
    )

    assert len(promotions) == 1
    assert len(promotions[0].groups) == 1
    assert [i.item_code for i in promotions[0].groups[0].items] == [
        "111",
        "222",
    ]


def test_group_one_takes_its_values_from_the_promotion(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<MinPurchaseAmount>50</MinPurchaseAmount>
<DiscountType>7</DiscountType>
<PromotionItems><Item><ItemCode>111</ItemCode></Item></PromotionItems>
"""
        ),
    )

    group = promotion.groups[0]

    assert group.min_purchase_amount == Decimal("50")
    assert group.discount_type == "7"


def test_group_one_accepts_min_purchase_amount_typo(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            "<MinPurchaseAmnt>35.5</MinPurchaseAmnt>"
            f"<PromotionItems>{flat_item('111')}</PromotionItems>"
        ),
    )

    assert promotion.groups[0].min_purchase_amount == Decimal("35.5")


def test_direct_items_inherit_values_from_promotion(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<RewardType>1</RewardType>
<MinQty>4</MinQty>
<MaxQty>0</MaxQty>
<DiscountRate>10.5</DiscountRate>
<DiscountedPrice>12.00</DiscountedPrice>
<DiscountedPricePerMida>3.00</DiscountedPricePerMida>
<IsWeightedPromo>1</IsWeightedPromo>
<PromotionItems>
    <Item>
        <ItemCode>72940761</ItemCode>
        <ItemType>1</ItemType>
    </Item>
</PromotionItems>
""",
            promotion_id="14",
        ),
    )

    item = promotion.groups[0].items[0]

    assert item.item_code == "72940761"
    assert item.item_type == 1
    assert item.reward_type == 1
    assert item.min_qty == Decimal("4")
    assert item.max_qty == Decimal("0")
    assert item.discount_rate == Decimal("10.5")
    assert item.discounted_price == Decimal("12.00")
    assert item.discounted_price_per_mida == Decimal("3.00")
    assert item.is_weighted is True


def test_direct_item_values_override_promotion_values(parser):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            """
<RewardType>1</RewardType>
<MinQty>4</MinQty>
<DiscountRate>10</DiscountRate>
<DiscountedPrice>20</DiscountedPrice>
<PromotionItems>
    <Item>
        <ItemCode>111</ItemCode>
        <RewardType>3</RewardType>
        <MinQty>2</MinQty>
        <DiscountRate>5</DiscountRate>
        <DiscountedPrice>15</DiscountedPrice>
    </Item>
</PromotionItems>
"""
        ),
    )

    item = promotion.groups[0].items[0]

    assert item.reward_type == 3
    assert item.min_qty == Decimal("2")
    assert item.discount_rate == Decimal("5")
    assert item.discounted_price == Decimal("15")


@pytest.mark.parametrize(
    "item_extra, promo_extra, expected",
    [
        ("<bIsWeighted>1</bIsWeighted>", "", True),
        ("<blsWeighted>1</blsWeighted>", "", True),
        ("", "<IsWeightedPromo>1</IsWeightedPromo>", True),
        ("", "<IsWeightedPromo>0</IsWeightedPromo>", False),
        (
            "<bIsWeighted>0</bIsWeighted>",
            "<IsWeightedPromo>1</IsWeightedPromo>",
            False,
        ),
        ("", "", False),
    ],
)
def test_is_weighted_sources_and_precedence(
    parser,
    item_extra,
    promo_extra,
    expected,
):
    promotion = parse_one_promo(
        parser,
        promo_xml(
            promo_extra
            + f"<PromotionItems>{flat_item('111', item_extra)}</PromotionItems>"
        ),
    )

    assert promotion.groups[0].items[0].is_weighted is expected


# ============================================================
# Error isolation
# ============================================================


def test_unexpected_error_in_one_promotion_does_not_drop_the_others(
    parser,
    monkeypatch,
    caplog,
):
    real_parse_datetime = parser.parse_datetime

    def flaky_parse_datetime(value):
        if value == "explode":
            raise RuntimeError("boom")

        return real_parse_datetime(value)

    monkeypatch.setattr(parser, "parse_datetime", flaky_parse_datetime)

    with caplog.at_level(logging.WARNING, logger="parsers.xml"):
        promotions = parse_promos(
            parser,
            promo_xml(
                "<PromotionStartDateTime>explode</PromotionStartDateTime>",
                promotion_id="1",
            ),
            promo_xml(promotion_id="2"),
        )

    assert [p.promotion_id for p in promotions] == ["2"]
    assert "Skipping malformed promotion" in caplog.text
    assert "promotion_id=1" in caplog.text


def test_unexpected_error_in_one_item_does_not_drop_the_others(
    parser,
    monkeypatch,
    caplog,
):
    real_parse_int = parser.parse_int

    def flaky_parse_int(value):
        if value == "boom":
            raise RuntimeError("boom")

        return real_parse_int(value)

    monkeypatch.setattr(parser, "parse_int", flaky_parse_int)

    promotion_xml = promo_xml(
        "<PromotionItems>"
        + flat_item("111", "<ItemType>boom</ItemType>")
        + flat_item("222", "<ItemType>1</ItemType>")
        + "</PromotionItems>"
    )

    with caplog.at_level(logging.WARNING, logger="parsers.xml"):
        promotion = parse_one_promo(parser, promotion_xml)

    assert [i.item_code for i in promotion.groups[0].items] == ["222"]
    assert "Skipping malformed promotion item" in caplog.text
    assert "item_code=111" in caplog.text