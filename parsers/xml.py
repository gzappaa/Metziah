from lxml import etree

from models.product import Product


class MahsaneiXmlParser:


    def parse_products(self, xml_bytes):

        root = etree.fromstring(xml_bytes)

        products = []


        for item in root.xpath("//Items/*"):

            product = Product(
                chain_id=root.findtext("ChainID"),
                barcode=item.findtext("ItemCode"),
                name=item.findtext("ItemName"),
                price=float(
                    item.findtext("ItemPrice")
                )
            )

            products.append(product)


        return products