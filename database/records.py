"""
DB-shaped records derived from the parser's Product and Promotion models.

Products are split into separate database records because the database
stores product identity, store-specific product data, and price state
separately:

    products
        Valid GTINs. Global product identity.

    store_products
        Non-GTIN/internal item codes, scoped to chain + store + item_code.

    prices
        Per-store price state for both GTIN and non-GTIN items.

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

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.product import Product
from models.promo import Promotion


# Supported GTIN/EAN/UPC lengths:
#
#   8  = EAN-8
#   12 = UPC-A / GTIN-12
#   13 = EAN-13 / GTIN-13
#   14 = GTIN-14
#
# We do NOT classify a code as a global product merely because it has one
# of these lengths. The GTIN check digit must also be valid.
_GTIN_LENGTHS = {8, 12, 13, 14}


def gtin_checksum_valid(code: str) -> bool:
    """
    Validate a GTIN/EAN/UPC check digit.

    Supported lengths:
        8   EAN-8
        12  UPC-A / GTIN-12
        13  EAN-13 / GTIN-13
        14  GTIN-14

    Returns False for:
        - non-numeric codes
        - unsupported lengths
        - invalid check digits
    """
    if not code.isdigit():
        return False

    if len(code) not in _GTIN_LENGTHS:
        return False

    digits = [int(digit) for digit in code]

    check_digit = digits[-1]
    body = digits[:-1]

    total = 0
    weight = 3

    for digit in reversed(body):
        total += digit * weight
        weight = 1 if weight == 3 else 3

    calculated = (10 - (total % 10)) % 10

    return calculated == check_digit


def is_valid_gtin(item_code: str) -> bool:
    """
    Return True only when item_code is a valid GTIN/EAN/UPC.

    Only valid GTINs are treated as global product identities.

    Everything else -- including numeric codes with an invalid checksum --
    is treated as a store-specific/internal item code.
    """
    return gtin_checksum_valid(item_code)


def normalize_store_id(store_id: str) -> str:
    """
    Normalize a feed StoreID to the canonical database store ID.

    Numeric IDs ignore leading zeroes:
        001 -> 1
        018 -> 18
        006 -> 6

    Non-numeric IDs are returned unchanged.
    """
    store_id = store_id.strip()

    if store_id.isdigit():
        return str(int(store_id))

    return store_id



@dataclass
class ProductRecord:
    """Maps 1:1 to the `products` table (valid GTINs only)."""

    item_code: str
    name: str
    manufacturer: str | None
    manufacturer_country: str | None
    item_type: int | None


@dataclass
class StoreProductRecord:
    """
    Maps 1:1 to the `store_products` table (non-GTIN/internal item_codes).

    Scoped to (chain_id, store_id, item_code).

    store_id is the canonical database store ID. Feed IDs are normalized
    so leading zeroes do not affect store identity.
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
    Maps 1:1 to the `prices` table.

    store_id is the canonical database store ID. Feed IDs are normalized
    so leading zeroes do not affect store identity.
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
    chain_id: str,
    store_id: str,
) -> tuple[ProductRecord | None, StoreProductRecord | None, PriceRecord]:
    """
    Split a parsed Product into its DB-table pieces.

    Routing:

        valid GTIN
            -> ProductRecord
            -> global `products` table

        anything else
            -> StoreProductRecord
            -> store-specific `store_products` table

    A PriceRecord is always created.

    Important:
        The canonical chain_id and store_id are supplied by the loader
        from the feed filepath. XML ChainId and StoreId are not used as
        database identity.

        The GTIN checksum is deliberately validated before a product is
        considered globally identifiable. A numeric 8/12/13/14-digit code
        with an invalid checksum is treated as an internal/store-specific
        code rather than being incorrectly inserted into `products`.
    """

    product_record = None
    store_product_record = None

    if is_valid_gtin(product.item_code):
        product_record = ProductRecord(
            item_code=product.item_code,
            name=product.name,
            manufacturer=product.manufacturer,
            manufacturer_country=product.manufacturer_country,
            item_type=product.item_type,
        )
    else:
        store_product_record = StoreProductRecord(
            chain_id=chain_id,
            store_id=store_id,
            item_code=product.item_code,
            name=product.name,
            manufacturer=product.manufacturer,
            manufacturer_country=product.manufacturer_country,
            item_type=product.item_type,
        )

    price_record = PriceRecord(
        chain_id=chain_id,
        store_id=store_id,
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



def split_promotion(
    promotion: Promotion,
    chain_id: str,
    store_id: str,
):
    """
    Flatten one nested Promotion into:

        promotion
        groups
        items

    Every PromotionGroup becomes one group record and every PromotionItem
    becomes one item record.

    The canonical chain_id and store_id are supplied by the loader from
    the feed filepath. XML IDs are not used as database identity.
    """

    promotion.chain_id = chain_id
    promotion.store_id = store_id

    groups = []
    items = []

    for group in promotion.groups:
        group.chain_id = chain_id
        group.store_id = store_id

        groups.append(group)

        for item in group.items:
            item.chain_id = chain_id
            item.store_id = store_id

            items.append(item)

    return promotion, groups, items