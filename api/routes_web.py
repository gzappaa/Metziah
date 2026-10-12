
"""HTML routes for the Metziah shopper interface."""

from pathlib import Path
import time
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from config import settings, APP_VERSION
from db import get_connection

from api.queries import (
    get_store_product_categories,
    get_fresh_product_detail,
    get_packaged_product_categories,
    get_packaged_products_by_category,
    get_store_product_subcategories,
    get_store_products_by_subcategory,
)
from api.service import get_product_detail, search_products

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = PROJECT_ROOT / "data" / "images"
BRAND_IMAGES_DIR = IMAGES_DIR / "brands"
PLACEHOLDER_IMAGE = (
    Path(__file__).resolve().parent / "static" / "image-placeholder.svg"
)

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)
templates.env.policies["json.dumps_kwargs"]["ensure_ascii"] = False


_data_updated_cache: tuple[float, str] = (0.0, "—")


def get_data_updated() -> str:
    """Date of the latest loaded price file, cached for 5 minutes."""
    global _data_updated_cache
    ts, value = _data_updated_cache
    if time.monotonic() - ts < 300:
        return value
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(updated_at)::date FROM file_tracking "
                    "WHERE loaded AND file_type IN ('PriceFull', 'Price')"
                )
                row = cur.fetchone()
        value = row[0].isoformat() if row and row[0] else "—"
    except Exception:
        pass  # keep the last known value
    _data_updated_cache = (time.monotonic(), value)
    return value


templates.env.globals["app_version"] = f"{APP_VERSION}-{settings.ENV.upper()}"
templates.env.globals["data_updated"] = get_data_updated

def find_product_image(item_code: str) -> Path | None:
    """Find a product image using its item code across known sources."""
    if not item_code or not item_code.isascii() or not item_code.isalnum():
        return None

    for source in ("tiv taam", "freshmarket", "super yuda"):
        candidate = IMAGES_DIR / source / f"{item_code}_001.jpg"
        if candidate.is_file():
            return candidate

    return None


def get_homepage_stats() -> dict[str, int]:
    """Return the catalog statistics displayed on the homepage."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM stores) AS total_stores,
                    (
                        SELECT COUNT(DISTINCT brand)
                        FROM (
                            SELECT NULLIF(BTRIM(name_he_normalized), '') AS brand
                            FROM chains

                            UNION

                            SELECT NULLIF(BTRIM(b.brand), '') AS brand
                            FROM chains
                            CROSS JOIN LATERAL UNNEST(brands) AS b(brand)
                        ) AS all_brands
                        WHERE brand IS NOT NULL
                    ) AS total_brands,
                    (
                        SELECT COUNT(DISTINCT product_name)
                        FROM store_product_category_matches
                    ) AS total_fresh_products
                """
            )
            row = cur.fetchone()

    return {
        "total_stores": row[0],
        "total_brands": row[1],
        "total_fresh_products": row[2],
    }


@router.get("/img/{item_code}", include_in_schema=False)
def product_image(item_code: str) -> FileResponse:
    """Serve a product image or a placeholder when none exists."""
    image_path = find_product_image(item_code)
    if image_path is not None:
        return FileResponse(image_path, media_type="image/jpeg")

    return FileResponse(PLACEHOLDER_IMAGE, media_type="image/svg+xml")


@router.get("/brand-logo/{brand_name}", include_in_schema=False)
def brand_logo(brand_name: str) -> FileResponse:
    """Serve a brand logo or the neutral image placeholder."""
    brand_name = brand_name.strip()

    if "\x00" in brand_name:
        return FileResponse(PLACEHOLDER_IMAGE, media_type="image/svg+xml")

    try:
        candidate = (BRAND_IMAGES_DIR / f"{brand_name}.jpg").resolve()

        if (
            candidate.parent == BRAND_IMAGES_DIR.resolve()
            and candidate.is_file()
        ):
            return FileResponse(candidate, media_type="image/jpeg")
    except (ValueError, OSError):
        pass

    return FileResponse(PLACEHOLDER_IMAGE, media_type="image/svg+xml")



@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(
    request: Request,
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    """Render the shopper page and the selected category's products."""
    active_tab = request.query_params.get("tab", "")
    active_category = request.query_params.get("category", "")
    active_subcategory = request.query_params.get("subcategory", "")

    page_size = 40
    offset = (page - 1) * page_size

    subcategories = []
    fresh_products = []
    fresh_product_total = 0
    fresh_product_pages = 0

    if active_tab == "packaged":
        categories = get_packaged_product_categories()
    elif active_tab == "fresh":
        categories = get_store_product_categories()

        category_id = None
        subcategory_id = None

        try:
            if active_category:
                category_id = int(active_category)
            if active_subcategory:
                subcategory_id = int(active_subcategory)
        except ValueError:
            active_category = ""
            active_subcategory = ""
            category_id = None
            subcategory_id = None

        if category_id is not None:
            subcategories = get_store_product_subcategories(category_id)

        if subcategory_id is not None:
            valid_subcategory = any(
                int(subcategory["id"]) == subcategory_id
                for subcategory in subcategories
            )

            if valid_subcategory:
                result = get_store_products_by_subcategory(
                    subcategory_id,
                    limit=page_size,
                    offset=offset,
                )
                fresh_products = result["items"]
                fresh_product_total = result["total"]
                fresh_product_pages = (
                    fresh_product_total + page_size - 1
                ) // page_size
            else:
                active_subcategory = ""
    else:
        categories = []

    packaged_result = (
        get_packaged_products_by_category(
            active_category,
            limit=page_size,
            offset=offset,
        )
        if active_tab == "packaged" and active_category
        else {"items": [], "total": 0, "limit": page_size, "offset": offset}
    )

    packaged_product_pages = (
        packaged_result["total"] + page_size - 1
    ) // page_size

    stats = get_homepage_stats()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **stats,
            "categories": categories,
            "active_tab": active_tab,
            "active_category": active_category,
            "products": packaged_result["items"],
            "product_total": packaged_result["total"],
            "product_pages": packaged_product_pages,
            "subcategories": subcategories,
            "active_subcategory": active_subcategory,
            "fresh_products": fresh_products,
            "fresh_product_total": fresh_product_total,
            "fresh_product_pages": fresh_product_pages,
            "page": page,
        },
    )



@router.get("/search", response_class=HTMLResponse, include_in_schema=False)
@router.get(
    "/partials/search-results",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def search_results(
    request: Request,
    q: str = Query(default="", max_length=200),
) -> HTMLResponse:
    """Return HTML search results for HTMX."""
    query = q.strip()

    result = (
        search_products(query, limit=20, offset=0)
        if query
        else {"products": [], "total": 0, "limit": 20, "offset": 0}
    )

    return templates.TemplateResponse(
        request=request,
        name="partials/search_results.html",
        context={
            "products": result["products"],
            "total": result["total"],
            "query": query,
        },
    )


@router.get(
    "/product/{barcode}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def product_detail(request: Request, barcode: str) -> HTMLResponse:
    """Render packaged-product details, regular prices, and promotions."""
    detail = get_product_detail(barcode)

    if detail is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product = detail.product
    enrichment = detail.enrichment

    sorted_prices = sorted(
        (
            price
            for price in detail.prices
            if price.price is not None and price.price > 0
        ),
        key=lambda price: price.price,
    )

    lowest_price = sorted_prices[0].price if sorted_prices else None

    prices_view = [
        {
            **price.model_dump(),
            "resolved_brand": price.shopper_brand or price.chain_name_he or "",
        }
        for price in sorted_prices
    ]

    promotions_view = [
        {
            **promo.model_dump(),
            "resolved_brand": promo.shopper_brand or promo.chain_name_he or "",
        }
        for promo in detail.promotions
        if promo.discounted_price is not None and promo.discounted_price > 0
    ]

    product_view = {
        "item_code": product.item_code,
        "name": (
            (enrichment.name_he if enrichment else None)
            or (enrichment.local_name if enrichment else None)
            or product.name_he
            or product.name_en
            or product.name
            or product.item_code
        ),
        "brand": (
            (enrichment.brand_he if enrichment else None)
            or product.brand_he
            or product.brand_en
        ),
        "category": (
            (enrichment.category_he if enrichment else None)
            or product.category_he
            or product.family_he
            or ""
        ),
        "subcategory": (
            (enrichment.subcategory_he if enrichment else None)
            or product.subcategory_he
            or ""
        ),
        "quantity": next(
            (p.get("quantity") for p in prices_view if p.get("quantity") is not None),
            None,
        ),
        "unit_qty": next(
            (p.get("unit_qty") for p in prices_view if p.get("unit_qty")),
            None,
        ),
        "manufacturer": product.manufacturer,
        "prices": prices_view,
        "promotions": promotions_view,
        "enrichment": enrichment,
    }

    return templates.TemplateResponse(
        request=request,
        name="product_detail.html",
        context={
            "product": product_view,
            "sorted_prices": prices_view,
            "lowest_price": lowest_price,
        },
    )


@router.get(
    "/fresh-product",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def fresh_product_detail(
    request: Request,
    name: str = Query(min_length=1, max_length=300),
    subcategory_id: int = Query(gt=0),
) -> HTMLResponse:
    """Render a fresh product's prices and active promotions by store."""
    product_name = name.strip()

    if not product_name:
        raise HTTPException(status_code=404, detail="Fresh product not found")

    stores = get_fresh_product_detail(
        product_name=product_name,
        subcategory_id=subcategory_id,
    )

    if not stores:
        raise HTTPException(status_code=404, detail="Fresh product not found")

    first_store = stores[0]

    valid_prices = [
        store["price"]
        for store in stores
        if store.get("price") is not None and store["price"] > 0
    ]
    lowest_price = min(valid_prices) if valid_prices else None

    promotions = [
        {
            **promotion,
            "store_name": store.get("store_name"),
            "chain_name_he": store.get("chain_name_he"),
        }
        for store in stores
        for promotion in (store.get("promotions") or [])
        if promotion.get("discounted_price") is not None
        and promotion["discounted_price"] > 0
    ]

    lowest_promotion = (
        min(promotions, key=lambda promotion: promotion["discounted_price"])
        if promotions
        else None
    )


    return templates.TemplateResponse(
        request=request,
        name="fresh_product_detail.html",
        context={
            "product_name": product_name,
            "category_id": first_store["category_id"],
            "subcategory_id": first_store["subcategory_id"],
            "category": first_store["category"],
            "subcategory": first_store["subcategory"],
            "stores": stores,
            "promotions": promotions,
            "lowest_price": lowest_price,
            "lowest_promotion": lowest_promotion,
        },
    )

