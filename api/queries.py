"""Read-only database queries for the shopper-facing API."""

from db import get_connection

from datetime import datetime, timezone


def get_product(barcode: str) -> dict | None:
    """Return core product data with optional enrichment fields."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.item_code,
                    p.name,
                    p.manufacturer,
                    p.manufacturer_country,
                    p.item_type,
                    pe.local_name,
                    pe.name_he,
                    pe.name_en,
                    pe.brand_he,
                    pe.brand_en,
                    pe.family_he,
                    pe.family_en,
                    pe.department_he,
                    pe.category_he,
                    pe.subcategory_he,
                    pe.description_he,
                    pe.description_en,
                    pe.ingredients_he,
                    pe.ingredients_en
                FROM products AS p
                LEFT JOIN product_enrichment AS pe
                    ON pe.item_code = p.item_code
                WHERE p.item_code = %s
                """,
                (barcode,),
            )

            row = cur.fetchone()
            if row is None:
                return None

            columns = [column.name for column in cur.description]
            return dict(zip(columns, row))


def get_prices(barcode: str) -> list[dict]:
    """Return current prices and store details for an enriched product."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.item_code,
                    p.chain_id,
                    p.store_id,
                    c.name_he_normalized AS chain_name_he,
                    c.name_en_normalized AS chain_name_en,
                    c.brands,
                    s.store_name,
                    s.address,
                    s.city,
                    s.latitude,
                    s.longitude,
                    p.price,
                    p.unit_price,
                    p.quantity,
                    p.unit_qty,
                    p.unit_measure,
                    p.weighted,
                    p.package_quantity,
                    p.allow_discount,
                    p.status,
                    p.price_update_time,
                    p.last_sale_datetime,
                    p.updated_at
                FROM prices AS p
                JOIN stores AS s
                    ON s.chain_id = p.chain_id
                   AND s.store_id = p.store_id
                JOIN chains AS c
                    ON c.chain_id = p.chain_id
                WHERE p.item_code = %s
                ORDER BY p.price ASC NULLS LAST, p.chain_id, p.store_id
                """,
                (barcode,),
            )

            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]



def get_prices_for_products(item_codes: list[str]) -> dict[str, list[dict]]:
    """Return current prices grouped by product barcode in one query."""
    if not item_codes:
        return {}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.item_code,
                    p.chain_id,
                    p.store_id,
                    p.price
                FROM prices AS p
                WHERE p.item_code = ANY(%s)
                  AND p.price > 0
                ORDER BY
                    p.item_code,
                    p.price ASC,
                    p.chain_id,
                    p.store_id
                """,
                (item_codes,),
            )

            prices_by_item: dict[str, list[dict]] = {
                item_code: [] for item_code in item_codes
            }

            for item_code, chain_id, store_id, price in cur.fetchall():
                prices_by_item[item_code].append(
                    {
                        "item_code": item_code,
                        "chain_id": chain_id,
                        "store_id": store_id,
                        "price": price,
                    }
                )

            return prices_by_item



def get_promotions(barcode: str) -> list[dict]:
    """Return currently valid promotions for a product barcode."""
    now = datetime.now(timezone.utc)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pi.item_code,
                    p.chain_id,
                    p.promotion_id,
                    p.store_id,
                    c.name_he_normalized AS chain_name_he,
                    c.name_en_normalized AS chain_name_en,
                    c.brands,
                    s.store_name,
                    s.address,
                    s.city,
                    p.description,
                    p.start_datetime,
                    p.end_datetime,
                    p.club_id,
                    p.additional_is_coupon,
                    p.allow_multiple_discounts,
                    p.additional_restrictions,
                    p.remarks,
                    pg.group_id,
                    pg.min_purchase_amount,
                    pg.discount_type,
                    pi.min_qty,
                    pi.max_qty,
                    pi.discount_rate,
                    pi.discounted_price,
                    pi.discounted_price_per_mida,
                    pi.is_weighted
                FROM promotion_items AS pi
                JOIN promotion_groups AS pg
                    ON pg.chain_id = pi.chain_id
                   AND pg.promotion_id = pi.promotion_id
                   AND pg.store_id = pi.store_id
                   AND pg.group_id = pi.group_id
                JOIN promotions AS p
                    ON p.chain_id = pi.chain_id
                   AND p.promotion_id = pi.promotion_id
                   AND p.store_id = pi.store_id
                JOIN stores AS s
                    ON s.chain_id = p.chain_id
                   AND s.store_id = p.store_id
                JOIN chains AS c
                    ON c.chain_id = p.chain_id
                WHERE pi.item_code = %s
                  AND (p.start_datetime IS NULL OR p.start_datetime <= %s)
                  AND (p.end_datetime IS NULL OR p.end_datetime >= %s)
                ORDER BY p.end_datetime NULLS LAST, p.chain_id, p.store_id
                """,
                (barcode, now, now),
            )

            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_enrichment(barcode: str) -> dict | None:
    """Return product enrichment and normalized nutrition, or None."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM product_enrichment
                WHERE item_code = %s
                """,
                (barcode,),
            )
            row = cur.fetchone()

            if row is None:
                return None

            columns = [column.name for column in cur.description]
            enrichment = dict(zip(columns, row))

            for field in ("category_path_he", "category_path_en"):
                if enrichment.get(field) is not None:
                    enrichment[field] = [
                        value
                        for value in enrichment[field]
                        if value is not None
                    ]

            cur.execute(
                """
                SELECT
                    source,
                    raw_label,
                    nutrient,
                    amount,
                    unit,
                    bound,
                    basis,
                    basis_raw,
                    flags,
                    is_canonical
                FROM product_nutrition
                WHERE item_code = %s
                ORDER BY source, basis, nutrient NULLS LAST, raw_label
                """,
                (barcode,),
            )
            nutrition_columns = [column.name for column in cur.description]
            enrichment["nutrition"] = [
                dict(zip(nutrition_columns, nutrition_row))
                for nutrition_row in cur.fetchall()
            ]

            return enrichment


def search(
    q: str,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Search enriched products by barcode or Hebrew/English product name."""
    q = q.strip()

    if not q:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped_q}%"


    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM product_enrichment
                WHERE item_code ILIKE %s ESCAPE E'\\\\'
                   OR name_he ILIKE %s ESCAPE E'\\\\'
                   OR name_en ILIKE %s ESCAPE E'\\\\'
                """,
                (pattern, pattern, pattern),
            )
            total = cur.fetchone()[0]


            cur.execute(
                """
                SELECT
                    item_code,
                    name_he,
                    name_en,
                    brand_he,
                    brand_en,
                    category_he,
                    subcategory_he
                FROM product_enrichment
                WHERE item_code ILIKE %s ESCAPE E'\\\\'
                   OR name_he ILIKE %s ESCAPE E'\\\\'
                   OR name_en ILIKE %s ESCAPE E'\\\\'
                ORDER BY
                    CASE WHEN item_code = %s THEN 0 ELSE 1 END,
                    name_he NULLS LAST,
                    item_code
                LIMIT %s OFFSET %s
                """,
                (pattern, pattern, pattern, q, limit, offset),
            )

            columns = [column.name for column in cur.description]
            items = [dict(zip(columns, row)) for row in cur.fetchall()]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

def get_store_product_categories() -> list[dict]:
    """Return store-product categories in display order with product counts."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.id,
                    c.name,
                    c.sort_order,
                    COUNT(DISTINCT m.item_code) AS count
                FROM store_product_categories AS c
                LEFT JOIN store_product_category_matches AS m
                    ON m.category_id = c.id
                GROUP BY c.id, c.name, c.sort_order
                ORDER BY c.sort_order, c.name
                """
            )
            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_store_product_subcategories(
    category_id: int | None = None,
) -> list[dict]:
    """Return store-product subcategories with product counts."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    sc.id,
                    sc.category_id,
                    c.name AS category,
                    sc.name,
                    sc.sort_order,
                    COUNT(DISTINCT (m.chain_id, m.store_id, m.item_code)) AS count
                FROM store_product_subcategories AS sc
                JOIN store_product_categories AS c
                    ON c.id = sc.category_id
                LEFT JOIN store_product_category_matches AS m
                    ON m.subcategory_id = sc.id
                WHERE (%s::SMALLINT IS NULL OR sc.category_id = %s::SMALLINT)
                GROUP BY
                    sc.id,
                    sc.category_id,
                    c.name,
                    sc.name,
                    sc.sort_order,
                    c.sort_order
                ORDER BY c.sort_order, sc.sort_order, sc.name
                """,
                (category_id, category_id),
            )
            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]





def get_store_products_by_subcategory(
    subcategory_id: int,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Return distinct fresh products with store counts and best prices."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH matched AS (
                    SELECT
                        m.product_name,
                        m.chain_id,
                        m.store_id,
                        m.item_code,
                        p.price,
                        (
                            SELECT MIN(pi.discounted_price)
                            FROM promotion_items AS pi
                            JOIN promotions AS promo
                              ON promo.chain_id = pi.chain_id
                             AND promo.promotion_id = pi.promotion_id
                             AND promo.store_id = pi.store_id
                            WHERE pi.chain_id = m.chain_id
                              AND pi.store_id = m.store_id
                              AND pi.item_code = m.item_code
                              AND pi.discounted_price > 0
                              AND (
                                  promo.start_datetime IS NULL
                                  OR promo.start_datetime <= NOW()
                              )
                              AND (
                                  promo.end_datetime IS NULL
                                  OR promo.end_datetime >= NOW()
                              )
                        ) AS promo_price
                    FROM store_product_category_matches AS m
                    LEFT JOIN prices AS p
                      ON p.chain_id = m.chain_id
                     AND p.store_id = m.store_id
                     AND p.item_code = m.item_code
                    WHERE m.subcategory_id = %s
                ),
                grouped AS (
                    SELECT
                        product_name,
                        COUNT(DISTINCT (chain_id, store_id)) AS store_count,
                        MIN(price) FILTER (
                            WHERE price > 0
                        ) AS lowest_price,
                        MIN(promo_price) FILTER (
                            WHERE promo_price > 0
                        ) AS cheapest_promotion
                    FROM matched
                    GROUP BY product_name
                )
                SELECT COUNT(*) FROM grouped
                """,
                (subcategory_id,),
            )
            total = cur.fetchone()[0]

            cur.execute(
                """
                WITH matched AS (
                    SELECT
                        m.product_name,
                        m.chain_id,
                        m.store_id,
                        m.item_code,
                        p.price,
                        (
                            SELECT MIN(pi.discounted_price)
                            FROM promotion_items AS pi
                            JOIN promotions AS promo
                              ON promo.chain_id = pi.chain_id
                             AND promo.promotion_id = pi.promotion_id
                             AND promo.store_id = pi.store_id
                            WHERE pi.chain_id = m.chain_id
                              AND pi.store_id = m.store_id
                              AND pi.item_code = m.item_code
                              AND pi.discounted_price > 0
                              AND (
                                  promo.start_datetime IS NULL
                                  OR promo.start_datetime <= NOW()
                              )
                              AND (
                                  promo.end_datetime IS NULL
                                  OR promo.end_datetime >= NOW()
                              )
                        ) AS promo_price
                    FROM store_product_category_matches AS m
                    LEFT JOIN prices AS p
                      ON p.chain_id = m.chain_id
                     AND p.store_id = m.store_id
                     AND p.item_code = m.item_code
                    WHERE m.subcategory_id = %s
                )
                SELECT
                    product_name,
                    COUNT(DISTINCT (chain_id, store_id)) AS store_count,
                    MIN(price) FILTER (
                        WHERE price > 0
                    ) AS lowest_price,
                    MIN(promo_price) FILTER (
                        WHERE promo_price > 0
                    ) AS cheapest_promotion
                FROM matched
                GROUP BY product_name
                ORDER BY
                    CASE WHEN MIN(price) FILTER (
                        WHERE price > 0
                    ) IS NULL THEN 1 ELSE 0 END,
                    MIN(price) FILTER (
                        WHERE price > 0
                    ) ASC,
                    product_name ASC
                LIMIT %s OFFSET %s
                """,
                (subcategory_id, limit, offset),
            )

            columns = [column.name for column in cur.description]
            items = [
                dict(zip(columns, row))
                for row in cur.fetchall()
            ]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def search_store_products(
    q: str,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Search unbarcoded store products by name or item code."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    q = q.strip()
    if not q:
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }

    escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped_q}%"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM store_products
                WHERE name ILIKE %s ESCAPE E'\\\\'
                   OR item_code ILIKE %s ESCAPE E'\\\\'
                """,
                (pattern, pattern),
            )
            total = cur.fetchone()[0]

            cur.execute(
                """
                SELECT
                    sp.chain_id,
                    sp.store_id,
                    sp.item_code,
                    sp.name AS product_name,
                    c.name_he_normalized AS chain_name_he,
                    c.name_en_normalized AS chain_name_en,
                    c.brands,
                    s.store_name,
                    s.address,
                    s.city,
                    s.latitude,
                    s.longitude
                FROM store_products AS sp
                JOIN chains AS c
                    ON c.chain_id = sp.chain_id
                JOIN stores AS s
                    ON s.chain_id = sp.chain_id
                   AND s.store_id = sp.store_id
                WHERE sp.name ILIKE %s ESCAPE E'\\\\'
                   OR sp.item_code ILIKE %s ESCAPE E'\\\\'
                ORDER BY
                    CASE
                        WHEN sp.name ILIKE %s ESCAPE E'\\\\' THEN 0
                        ELSE 1
                    END,
                    sp.name,
                    sp.chain_id,
                    sp.store_id,
                    sp.item_code
                LIMIT %s OFFSET %s
                """,
                (
                    pattern,
                    pattern,
                    pattern,
                    limit,
                    offset,
                ),
            )
            columns = [column.name for column in cur.description]
            items = [
                dict(zip(columns, row))
                for row in cur.fetchall()
            ]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

def get_packaged_product_categories() -> list[dict]:
    """Return packaged-product categories, excluding store products."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pe.category_he AS name,
                    COUNT(*) AS count,
                    ARRAY_AGG(DISTINCT pe.subcategory_he ORDER BY pe.subcategory_he)
                        FILTER (
                            WHERE pe.subcategory_he IS NOT NULL
                              AND BTRIM(pe.subcategory_he) <> ''
                        ) AS subcategories
                FROM product_enrichment AS pe
                WHERE pe.category_he IS NOT NULL
                  AND BTRIM(pe.category_he) <> ''
                  AND EXISTS (
                      SELECT 1
                      FROM products AS p
                      WHERE p.item_code = pe.item_code
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM store_products AS sp
                      WHERE sp.item_code = pe.item_code
                  )
                GROUP BY pe.category_he
                ORDER BY pe.category_he
                """
            )
            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_fresh_product_detail(
    product_name: str,
    subcategory_id: int,
) -> list[dict]:
    """Return a fresh product's store prices and all active promotions."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.chain_id,
                    m.store_id,
                    m.item_code,
                    m.product_name,
                    m.category_id,
                    m.category,
                    m.subcategory_id,
                    m.subcategory,
                    c.name_he_normalized AS chain_name_he,
                    c.name_en_normalized AS chain_name_en,
                    c.brands,
                    s.store_name,
                    s.address,
                    s.city,
                    s.latitude,
                    s.longitude,
                    p.price,
                    p.unit_price,
                    COALESCE(
                        (
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'promotion_id', promo.promotion_id,
                                    'description', promo.description,
                                    'discounted_price', pi.discounted_price,
                                    'discount_rate', pi.discount_rate,
                                    'min_qty', pi.min_qty,
                                    'max_qty', pi.max_qty,
                                    'group_id', pi.group_id,
                                    'club_id', promo.club_id,
                                    'start_datetime', promo.start_datetime,
                                    'end_datetime', promo.end_datetime
                                )
                                ORDER BY pi.discounted_price ASC NULLS LAST
                            )
                            FROM promotion_items pi
                            JOIN promotions promo
                              ON promo.chain_id = pi.chain_id
                             AND promo.store_id = pi.store_id
                             AND promo.promotion_id = pi.promotion_id
                            WHERE pi.chain_id = m.chain_id
                              AND pi.store_id = m.store_id
                              AND pi.item_code = m.item_code
                              AND pi.discounted_price > 0
                              AND (
                                  promo.start_datetime IS NULL
                                  OR promo.start_datetime <= %s
                              )
                              AND (
                                  promo.end_datetime IS NULL
                                  OR promo.end_datetime >= %s
                              )
                        ),
                        '[]'::jsonb
                    ) AS promotions
                FROM store_product_category_matches m
                JOIN chains c
                  ON c.chain_id = m.chain_id
                JOIN stores s
                  ON s.chain_id = m.chain_id
                 AND s.store_id = m.store_id
                LEFT JOIN prices p
                  ON p.chain_id = m.chain_id
                 AND p.store_id = m.store_id
                 AND p.item_code = m.item_code
                WHERE m.product_name = %s
                  AND m.subcategory_id = %s
                ORDER BY
                    CASE WHEN p.price > 0 THEN 0 ELSE 1 END,
                    p.price ASC NULLS LAST,
                    c.name_he_normalized NULLS LAST,
                    s.store_name NULLS LAST,
                    m.chain_id,
                    m.store_id
                """,
                (now, now, product_name, subcategory_id),
            )

            columns = [column.name for column in cur.description]
            return [
                dict(zip(columns, row))
                for row in cur.fetchall()
            ]



def get_packaged_products_by_category(
    category: str,
    limit: int = 40,
    offset: int = 0,
) -> dict:
    """Return packaged products in a category, excluding store products."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    category = category.strip()
    if not category:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM product_enrichment AS pe
                WHERE pe.category_he = %s
                  AND EXISTS (
                      SELECT 1
                      FROM products AS p
                      WHERE p.item_code = pe.item_code
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM store_products AS sp
                      WHERE sp.item_code = pe.item_code
                  )
                """,
                (category,),
            )
            total = cur.fetchone()[0]

            cur.execute(
                """
                SELECT
                    pe.item_code,
                    pe.name_he,
                    pe.name_en,
                    pe.brand_he,
                    pe.brand_en,
                    pe.category_he,
                    pe.subcategory_he
                FROM product_enrichment AS pe
                WHERE pe.category_he = %s
                  AND EXISTS (
                      SELECT 1
                      FROM products AS p
                      WHERE p.item_code = pe.item_code
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM store_products AS sp
                      WHERE sp.item_code = pe.item_code
                  )
                ORDER BY pe.name_he NULLS LAST, pe.item_code
                LIMIT %s OFFSET %s
                """,
                (category, limit, offset),
            )
            columns = [column.name for column in cur.description]
            items = [dict(zip(columns, row)) for row in cur.fetchall()]

    return {"items": items, "total": total, "limit": limit, "offset": offset}