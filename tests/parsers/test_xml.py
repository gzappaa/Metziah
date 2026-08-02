# tests/parsers/test_xml.py

import pytest
from lxml import etree

from parsers.xml import MachseneiXmlParser


@pytest.fixture
def parser():
    return MachseneiXmlParser()


def make_xml(item_xml=""):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Root>
    <ChainID>7290661400001</ChainID>
    <SubChainID>001</SubChainID>
    <StoreID>018</StoreID>
    <BikoretNo>0</BikoretNo>
    <Items>
        {item_xml}
    </Items>
</Root>
""".encode("utf-8")


def real_item_xml(
    item_code="50000574438",
    name="חטיף לחתול מעדני הים",
    price="12.9",
    unit="גרם 100",
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
    <bIsWeighted>0</bIsWeighted>
    <QtyInPackage>1</QtyInPackage>
    <ItemPrice>{price}</ItemPrice>
    <UnitOfMeasurePrice>21.5</UnitOfMeasurePrice>
    <AllowDiscount>0</AllowDiscount>
    <ItemStatus />
</Item>
"""


# ---- happy path ----


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

    assert product.price == 12.9
    assert product.unit == "גרם 100"


def test_parse_multiple_items(parser):
    xml = make_xml(
        real_item_xml(item_code="111")
        + real_item_xml(item_code="222")
    )

    products = parser.parse_price_file(xml)

    assert len(products) == 2
    assert [p.item_code for p in products] == [
        "111",
        "222",
    ]


def test_parse_empty_items_returns_empty_list(parser):
    xml = make_xml()

    products = parser.parse_price_file(xml)

    assert products == []


# ---- fields ----


def test_parse_preserves_hebrew_text(parser):
    xml = make_xml(real_item_xml())

    product = parser.parse_price_file(xml)[0]

    assert "חתול" in product.name


def test_parse_missing_price_defaults(parser):
    xml = make_xml(
        real_item_xml(price="")
    )

    product = parser.parse_price_file(xml)[0]

    assert product.price == 0.0


def test_parse_missing_name(parser):
    xml = make_xml(
        real_item_xml(name="")
    )

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


# ---- malformed input ----


def test_invalid_xml_raises(parser):
    with pytest.raises(etree.XMLSyntaxError):
        parser.parse_price_file(
            b"<Root><Items><Item>"
        )


# ---- price edge cases ----


def test_invalid_price_format_raises(parser):
    xml = make_xml(
        real_item_xml(price="7,90")
    )

    with pytest.raises(ValueError):
        parser.parse_price_file(xml)