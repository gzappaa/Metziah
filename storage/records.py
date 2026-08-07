"""
DB-shaped records, derived from the parser's Product model.

models.product.Product is a merged view (item metadata + per-store price
in one object), matching what a single <Item> in the XML naturally gives
you. The database splits that into three tables:

  - products        -- real barcodes only (EAN-8/12/13-style item_code).
                        Global identity, shared across chains.
  - store_products   -- internal/non-barcode item_codes (e.g. loose
                        produce, deli). These collide across chains, so
                        they're scoped to (chain_id, item_code) instead
                        of being globally unique.
  - prices           -- per-store price state, for BOTH kinds of item.
                        item_code here is intentionally unconstrained
                        (no FK) since it may point at either products
                        or store_products depending on which kind it is.

unit_qty/weighted/package_quantity live on prices, not products or
store_products -- these can legitimately differ per store for the same
item_code (e.g. sold prepackaged at one branch, loose by weight at
another), so they're "how it's sold here" not "what it is".
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
    Scoped to (chain_id, item_code) -- these codes are assigned per
    retailer's internal catalog, not globally unique like a barcode.
    """

    chain_id: str
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