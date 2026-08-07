from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from models.product import Product


class MachseneiXmlParser:

    def parse_price_file(self, xml_content):

        root = etree.fromstring(xml_content)

        products = []

        chain_id = root.findtext("ChainID")
        sub_chain_id = root.findtext("SubChainID")
        store_id = root.findtext("StoreID")

        for item in root.findall("./Items/Item"):

            item_type_text = item.findtext("ItemType")
            qty_in_package_text = item.findtext("QtyInPackage")

            products.append(
                Product(
                    chain_id=chain_id,
                    sub_chain_id=sub_chain_id,
                    store_id=store_id,

                    item_code=item.findtext("ItemCode"),
                    name=item.findtext("ItemName"),

                    price=self.parse_decimal(
                        item.findtext("ItemPrice"), "ItemPrice"
                    ),

                    unit_price=self.parse_decimal(
                        item.findtext("UnitOfMeasurePrice"), "UnitOfMeasurePrice"
                    ),

                    quantity=self.parse_decimal(
                        item.findtext("Quantity"), "Quantity"
                    ),

                    unit_qty=item.findtext("UnitQty"),
                    unit_measure=item.findtext("UnitOfMeasure"),

                    manufacturer=item.findtext("ManufactureName"),
                    manufacturer_country=item.findtext("ManufactureCountry"),

                    price_update_time=self.parse_datetime(
                        item.findtext("PriceUpdateTime")
                    ),

                    last_sale_datetime=self.parse_datetime(
                        item.findtext("LastSaleDateTime")
                    ),

                    weighted=item.findtext("bIsWeighted") == "1",

                    allow_discount=item.findtext("AllowDiscount") == "1",

                    # ItemType=0 is a real, common value (seen ~1600 times),
                    # so we distinguish "present with value 0" from "tag missing"
                    # using presence (is not None), not truthiness.
                    item_type=(
                        int(item_type_text)
                        if item_type_text is not None else None
                    ),

                    # QtyInPackage never legitimately appears as 0 in real data,
                    # so a missing/empty tag maps cleanly to None instead of a
                    # fake 0 that could be confused with a real value later.
                    package_quantity=(
                        int(qty_in_package_text)
                        if qty_in_package_text else None
                    ),

                    status=item.findtext("ItemStatus") or None,
                )
            )

        return products


    def parse_datetime(self, value):
        if not value:
            return None

        return datetime.fromisoformat(value)

    def parse_decimal(self, value, field_name):
        try:
            return Decimal(value or "0")
        except InvalidOperation:
            raise ValueError(
                f"Invalid {field_name} format: {value!r}"
            )