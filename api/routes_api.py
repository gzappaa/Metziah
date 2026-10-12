"""JSON API: everything the shopper UI does, without the HTML."""

from fastapi import APIRouter, HTTPException, Path, Query

from api import queries, service
from api.schemas import (
    CatalogStats,
    FreshCategory,
    FreshProductDetail,
    FreshProductPage,
    FreshSubcategory,
    PackagedCategory,
    ProductDetail,
    ProductSearchPage,
    SearchResult,
    StoreProductSearchResult,
)
from api.service import get_product_detail

router = APIRouter(prefix="/api/v1")

SMALLINT_MAX = 32767
INT_MAX = 2_147_483_647


# ----------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------

@router.get("/stats", response_model=CatalogStats, tags=["Catalog"])
def stats() -> dict:
    """Catalog totals shown on the homepage."""
    return queries.get_catalog_stats()


# ----------------------------------------------------------------
# Packaged (barcoded) products
# ----------------------------------------------------------------

@router.get(
    "/categories/packaged",
    response_model=list[PackagedCategory],
    tags=["Packaged products"],
)
def packaged_categories() -> list[dict]:
    """Packaged-product categories with counts and their subcategories."""
    return queries.get_packaged_product_categories()


@router.get("/products", response_model=SearchResult, tags=["Packaged products"])
def products_by_category(
    category: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Enriched packaged products in one category (by category name)."""
    return queries.get_packaged_products_by_category(
        category, limit=limit, offset=offset
    )


@router.get(
    "/products/search",
    response_model=ProductSearchPage,
    tags=["Packaged products"],
)
def search_products(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Search enriched products; each hit has its cheapest price and store count."""
    result = service.search_products(q.strip(), limit=limit, offset=offset)
    return {
        "items": result["products"],
        "total": result["total"],
        "limit": result["limit"],
        "offset": result["offset"],
    }


@router.get(
    "/products/unenriched",
    response_model=SearchResult,
    tags=["Packaged products"],
)
def list_unenriched(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Browse (no q) or search (q) products that have no enrichment data."""
    if q.strip():
        return queries.search_unenriched_products(q, limit=limit, offset=offset)
    return queries.get_unenriched_products(limit=limit, offset=offset)


# NOTE: must stay after /products/search and /products/unenriched.
@router.get(
    "/products/{barcode}",
    response_model=ProductDetail,
    tags=["Packaged products"],
)
def product_detail(barcode: str) -> ProductDetail:
    """Full detail for any barcode, enriched or not."""
    detail = get_product_detail(barcode)
    if detail is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return detail


# ----------------------------------------------------------------
# Fresh products (produce, butcher, fish, bakery)
# ----------------------------------------------------------------

@router.get(
    "/fresh/categories",
    response_model=list[FreshCategory],
    tags=["Fresh products"],
)
def fresh_categories() -> list[dict]:
    """Fresh-product categories in display order, with product counts."""
    return queries.get_store_product_categories()


@router.get(
    "/fresh/categories/{category_id}/subcategories",
    response_model=list[FreshSubcategory],
    tags=["Fresh products"],
)
def fresh_subcategories(
    category_id: int = Path(ge=1, le=SMALLINT_MAX),
) -> list[dict]:
    """Subcategories of one fresh category, with product counts."""
    return queries.get_store_product_subcategories(category_id)


@router.get(
    "/fresh/products",
    response_model=FreshProductPage,
    tags=["Fresh products"],
)
def fresh_products(
    subcategory_id: int = Query(ge=1, le=INT_MAX),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Distinct fresh products in a subcategory, cheapest first."""
    return queries.get_store_products_by_subcategory(
        subcategory_id, limit=limit, offset=offset
    )


@router.get(
    "/fresh/products/detail",
    response_model=FreshProductDetail,
    tags=["Fresh products"],
)
def fresh_product_detail(
    name: str = Query(min_length=1, max_length=300),
    subcategory_id: int = Query(ge=1, le=INT_MAX),
) -> FreshProductDetail:
    """A fresh product's price and active promotions in every store."""
    detail = service.get_fresh_product_detail(name, subcategory_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Fresh product not found")
    return detail


@router.get(
    "/fresh/search",
    response_model=StoreProductSearchResult,
    tags=["Fresh products"],
)
def fresh_search(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Search fresh (unbarcoded) store products by name or item code."""
    return service.search_store_products(q, limit=limit, offset=offset)