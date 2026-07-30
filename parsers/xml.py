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

            products.append(
                Product(
                    chain_id=chain_id,
                    sub_chain_id=sub_chain_id,
                    store_id=store_id,
                    item_code=item.findtext("ItemCode"),
                    name=item.findtext("ItemName"),
                    price=float(item.findtext("ItemPrice") or 0),
                    unit=item.findtext("UnitOfMeasure"),
                )
            )

        return products