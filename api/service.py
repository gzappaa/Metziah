"""Business logic for shopper-facing API responses."""

from api import queries
from api.schemas import (
    Price,
    Product,
    ProductDetail,
    ProductEnrichment,
    Promotion,
    SearchResult,
    StoreProduct,
    StoreProductCategory,
    StoreProductSearchResult,
    StoreProductSubcategory,
)
from utils.brand_resolution import resolve_shopper_brand


def get_product_detail(barcode: str) -> ProductDetail | None:
    """Combine product, price, promotion, and enrichment data."""
    product_data = queries.get_product(barcode)

    if product_data is None:
        return None

    prices = []
    for row in queries.get_prices(barcode):
        row = dict(row)

        # Exclude missing, zero, and negative regular prices.
        if row.get("price") is None or row["price"] <= 0:
            continue

        row["shopper_brand"] = resolve_shopper_brand(
            row.get("store_name"),
            row.get("brands"),
            row.get("chain_name_he"),
        )
        prices.append(Price.model_validate(row))

    promotions = []
    for row in queries.get_promotions(barcode):
        row = dict(row)

        discounted_price = row.get("discounted_price")
        if discounted_price is None or discounted_price <= 0:
            continue

        row["shopper_brand"] = resolve_shopper_brand(
            row.get("store_name"),
            row.get("brands"),
            row.get("chain_name_he"),
        )
        promotions.append(Promotion.model_validate(row))

    enrichment_data = queries.get_enrichment(barcode)

    return ProductDetail(
        product=Product.model_validate(product_data),
        prices=prices,
        promotions=promotions,
        enrichment=(
            ProductEnrichment.model_validate(enrichment_data)
            if enrichment_data is not None
            else None
        ),
    )


def search_products(
    q: str,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Search products and prepare results for the shopper HTML template."""
    result = queries.search(q, limit=limit, offset=offset)
    products = []

    for item in result["items"]:
        product = Product.model_validate(item)
        prices = queries.get_prices(product.item_code)

        available_prices = [
            price["price"]
            for price in prices
            if price.get("price") is not None
        ]

        products.append(
            {
                "identifier": product.item_code,
                "brand": product.brand_he or product.brand_en,
                "category": (
                    product.category_he
                    or product.subcategory_he
                    or product.family_he
                    or ""
                ),
                "name": product.name_he or product.name_en or product.item_code,
                "min_price": min(available_prices) if available_prices else None,
                "store_count": len(
                    {
                        (price["chain_id"], price["store_id"])
                        for price in prices
                    }
                ),
            }
        )

    return {
        "products": products,
        "total": result["total"],
        "limit": result["limit"],
        "offset": result["offset"],
    }

def get_store_product_categories() -> list[StoreProductCategory]:
    """Return store-product categories in display order."""
    return [
        StoreProductCategory.model_validate(row)
        for row in queries.get_store_product_categories()
    ]


def get_store_product_subcategories(
    category_id: int | None = None,
) -> list[StoreProductSubcategory]:
    """Return subcategories, optionally filtered by category."""
    return [
        StoreProductSubcategory.model_validate(row)
        for row in queries.get_store_product_subcategories(category_id)
    ]


def get_store_products_by_subcategory(
    subcategory_id: int,
    limit: int = 20,
    offset: int = 0,
) -> StoreProductSearchResult:
    """Return store products matched to a subcategory."""
    result = queries.get_store_products_by_subcategory(
        subcategory_id,
        limit=limit,
        offset=offset,
    )

    items = []
    for row in result["items"]:
        row = dict(row)
        row["shopper_brand"] = resolve_shopper_brand(
            row.get("store_name"),
            row.get("brands"),
            row.get("chain_name_he"),
        )
        items.append(StoreProduct.model_validate(row))

    return StoreProductSearchResult(
        items=items,
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


def search_store_products(
    q: str,
    limit: int = 20,
    offset: int = 0,
) -> StoreProductSearchResult:
    """Search store products and validate the paginated response."""
    result = queries.search_store_products(
        q,
        limit=limit,
        offset=offset,
    )

    items = []
    for row in result["items"]:
        row = dict(row)
        row["shopper_brand"] = resolve_shopper_brand(
            row.get("store_name"),
            row.get("brands"),
            row.get("chain_name_he"),
        )
        items.append(StoreProduct.model_validate(row))

    return StoreProductSearchResult(
        items=items,
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )

def make_fresh_identifier(item_code: str) -> str:
    """Create an identifier for an enriched barcode product."""
    if not item_code or not item_code.strip() or ":" in item_code:
        raise ValueError("item_code must be non-empty and cannot contain ':'")

    return f"fresh:{item_code}"


def make_store_product_identifier(
    chain_id: str,
    store_id: str,
    item_code: str,
) -> str:
    """Create an identifier for a store-specific product."""
    parts = {
        "chain_id": chain_id,
        "store_id": store_id,
        "item_code": item_code,
    }

    for name, value in parts.items():
        if not value or not value.strip() or ":" in value:
            raise ValueError(
                f"{name} must be non-empty and cannot contain ':'"
            )

    return f"sp:{chain_id}:{store_id}:{item_code}"


def parse_product_identifier(identifier: str) -> dict[str, str]:
    """Parse a fresh or store-product identifier."""
    if not identifier or not identifier.strip():
        raise ValueError("identifier must be non-empty")

    parts = identifier.split(":")

    if len(parts) == 2 and parts[0] == "fresh":
        item_code = parts[1]
        if not item_code.strip():
            raise ValueError("item_code must be non-empty")

        return {
            "type": "fresh",
            "item_code": item_code,
        }

    if len(parts) == 4 and parts[0] == "sp":
        _, chain_id, store_id, item_code = parts

        if not all(part.strip() for part in (chain_id, store_id, item_code)):
            raise ValueError(
                "chain_id, store_id, and item_code must be non-empty"
            )

        return {
            "type": "store_product",
            "chain_id": chain_id,
            "store_id": store_id,
            "item_code": item_code,
        }

    raise ValueError(f"Invalid product identifier: {identifier!r}")