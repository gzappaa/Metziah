import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from models.product import Product

logger = logging.getLogger(__name__)


class MachseneiXmlParser:

    def parse_price_file(self, xml_content):

        root = etree.fromstring(xml_content)

        products = []

        chain_id = root.findtext("ChainID")
        sub_chain_id = root.findtext("SubChainID")
        store_id = root.findtext("StoreID")

        for item in root.findall("./Items/Item"):

            item_code = item.findtext("ItemCode")

            try:
                item_type_text = item.findtext("ItemType")
                qty_in_package_text = item.findtext("QtyInPackage")

                products.append(
                    Product(
                        chain_id=chain_id,
                        sub_chain_id=sub_chain_id,
                        store_id=store_id,

                        item_code=item_code,
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
            except Exception as e:
                # One malformed <Item> shouldn't take down the whole file --
                # every other item in this store's price file is still good
                # data and shouldn't be thrown away over one bad row.
                logger.warning(
                    "Skipping malformed item (chain_id=%s store_id=%s item_code=%s): %s",
                    chain_id, store_id, item_code, e,
                )
                continue

        return products


    def parse_datetime(self, value):
        if not value:
            return None

        try:
            return datetime.fromisoformat(value)
        except ValueError:
            # Some feeds send garbage placeholder dates (e.g. all-zero
            # "0000-00-00 00:00:00") for fields like LastSaleDateTime when
            # an item has never sold. That's not a real date -- treat it
            # as missing rather than crashing over one field.
            return None

    def parse_decimal(self, value, field_name):
        try:
            return Decimal(value or "0")
        except InvalidOperation:
            raise ValueError(
                f"Invalid {field_name} format: {value!r}"
            )