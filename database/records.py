"""
DB-shaped records derived from the parser's Product and Promotion models.

Products are split into separate database records because the database
stores product identity, store-specific product data, and price state
separately:

    products
        Real barcodes. Global product identity.

    store_products
        Non-barcode item codes, scoped to chain + store + item_code.

    prices
        Per-store price state for both barcode and non-barcode items.

Promotion objects are also transformed to match the database structure.
The parser represents a promotion as a nested tree:

    Promotion
        └── PromotionGroup
                └── PromotionItem

split_promotion() flattens this into the three database record levels:
the promotion itself, its groups, and its items.

Store-specific selling details such as unit_qty, weighted, and
package_quantity belong to prices because they describe how an item is
sold at a particular store, not what the item is.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.product import Product

# EAN-8 / UPC-A(12) / EAN-13 -- the common real-barcode lengths seen in
# these feeds. Internal/non-barcode item_codes (loose produce, deli,
# bakery) don't match this shape.
_BARCODE_RE = re.compile(r"^\d{8}$|^\d{12}$|^\d{13}$")


def looks_like_barcode(item_code: str) -> bool:
    return bool(_BARCODE_RE.match(item_code))


@dataclass
class ProductRecord:
    """Maps 1:1 to the `products` table (real barcodes only)."""

    item_code: str
    name: str
    manufacturer: str | None
    manufacturer_country: str | None
    item_type: int | None


@dataclass
class StoreProductRecord:
    """
    Maps 1:1 to the `store_products` table (non-barcode item_codes).
    Scoped to (chain_id, store_id, item_code) -- store_id here is the
    text StoreID from the XML (e.g. "018"), same as PriceRecord; the
    repository layer resolves it to stores.id before writing.
    """

    chain_id: str
    store_id: str
    item_code: str
    name: str
    manufacturer: str | None
    manufacturer_country: str | None
    item_type: int | None


@dataclass
class PriceRecord:
    """
    Maps 1:1 to the `prices` table, except store_id here is still the
    text StoreID from the XML (e.g. "018") -- the repository layer
    resolves this to stores.id (the serial) before writing.
    """

    chain_id: str
    store_id: str
    item_code: str
    price: Decimal
    unit_price: Decimal
    quantity: Decimal
    unit_qty: str
    unit_measure: str
    weighted: bool
    package_quantity: int | None
    allow_discount: bool
    status: str | None
    price_update_time: datetime | None
    last_sale_datetime: datetime | None


def split_product(
    product: Product,
) -> tuple[ProductRecord | None, StoreProductRecord | None, PriceRecord]:
    """
    Splits a parsed Product into its DB-table pieces. Exactly one of
    (product_record, store_product_record) is populated, based on
    whether item_code looks like a real barcode -- the other is None.
    price_record is always populated.
    """

    product_record = None
    store_product_record = None

    if looks_like_barcode(product.item_code):
        product_record = ProductRecord(
            item_code=product.item_code,
            name=product.name,
            manufacturer=product.manufacturer,
            manufacturer_country=product.manufacturer_country,
            item_type=product.item_type,
        )
    else:
        store_product_record = StoreProductRecord(
            chain_id=product.chain_id,
            store_id=product.store_id,
            item_code=product.item_code,
            name=product.name,
            manufacturer=product.manufacturer,
            manufacturer_country=product.manufacturer_country,
            item_type=product.item_type,
        )

    price_record = PriceRecord(
        chain_id=product.chain_id,
        store_id=product.store_id,
        item_code=product.item_code,
        price=product.price,
        unit_price=product.unit_price,
        quantity=product.quantity,
        unit_qty=product.unit_qty,
        unit_measure=product.unit_measure,
        weighted=product.weighted,
        package_quantity=product.package_quantity,
        allow_discount=product.allow_discount,
        status=product.status,
        price_update_time=product.price_update_time,
        last_sale_datetime=product.last_sale_datetime,
    )

    return product_record, store_product_record, price_record


def split_promotion(promotion):
    """
    Walks one nested Promotion (with its groups/items) into three flat
    lists for the three promo tables. Unlike split_product, this isn't
    a routing decision -- every PromotionGroup always becomes exactly
    one promotion_groups row, every PromotionItem always becomes
    exactly one promotion_items row. So no new record types needed,
    just tree-flattening -- the .groups/.items attributes are simply
    ignored when building insert tuples in repository.py.
    """
    groups = []
    items = []

    for group in promotion.groups:
        groups.append(group)
        items.extend(group.items)

    return promotion, groups, items