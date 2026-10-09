-- ============================================================
-- 005_store_product_categories.sql
--
-- Apply after 004_product_enrichment.sql.
-- Adds category/subcategory tables and a materialized view
-- matching store_products to subcategories.
--
-- Categories and subcategories for products WITHOUT fixed
-- barcodes (produce, butcher, fish, bakery), i.e. store_products.
--
-- Seeded from data/reference/store_products.json.
--
-- category    -> used for DISPLAY (grouping in the UI)
-- subcategory -> used for QUERYING: its `name` is split into words
--                and every word must occur in store_products.name.
-- ============================================================


-- ------------------------------------------------------------
-- STORE_PRODUCT_CATEGORIES
--
-- Display groups, e.g. 'ירקות ופירות', 'קצבייה'.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS store_product_categories (
    id          SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sort_order  SMALLINT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- STORE_PRODUCT_SUBCATEGORIES
--
-- One row per entry in the JSON lists, e.g. 'אבוקדו', 'חזה עוף'.
--
-- The name is the search phrase:
-- every word in it must appear in store_products.name.
--
-- No FK to store_products: the match is done by keyword search,
-- not by a stored link.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS store_product_subcategories (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id  SMALLINT NOT NULL
        REFERENCES store_product_categories(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (category_id, name)
);


CREATE INDEX IF NOT EXISTS idx_sp_subcategories_category
ON store_product_subcategories (category_id, sort_order);


-- ------------------------------------------------------------
-- STORE_PRODUCT_CATEGORY_MATCHES
--
-- Materialized view containing the precomputed matches between
-- store_products and subcategories.
--
-- A store_product belongs to a subcategory when EVERY WORD in
-- the subcategory name occurs in store_products.name.
--
-- Example:
--
--   subcategory: "חזה עוף"
--   product:     "חזה עוף טרי"
--
--   -> MATCH
--
-- The words do not need to be adjacent or in the same order.
-- ------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS store_product_category_matches AS
SELECT
    sp.chain_id,
    sp.store_id,
    sp.item_code,
    sp.name AS product_name,

    c.id AS category_id,
    c.name AS category,

    sc.id AS subcategory_id,
    sc.name AS subcategory

FROM store_products sp
JOIN store_product_subcategories sc
    ON NOT EXISTS (
        SELECT 1
        FROM regexp_split_to_table(
            regexp_replace(
                replace(sc.name, '/', ' '),
                '[(),.''"־–—-]',
                ' ',
                'g'
            ),
            '\s+'
        ) AS word
        WHERE word <> ''
          AND sp.name NOT ILIKE '%' || word || '%'
    )
JOIN store_product_categories c
    ON c.id = sc.category_id
WHERE sp.name IS NOT NULL;


-- ------------------------------------------------------------
-- MATCH VIEW INDEXES
-- ------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_sp_category_matches_product
ON store_product_category_matches (
    chain_id,
    store_id,
    item_code
);

CREATE INDEX IF NOT EXISTS idx_sp_category_matches_category
ON store_product_category_matches (
    category_id,
    subcategory_id
);