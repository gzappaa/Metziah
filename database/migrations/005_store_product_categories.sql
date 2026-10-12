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
--   subcategory: "עוף שלם"
--   product:     "עוף שלם טרי אולטרה מגה"
--
--   -> MATCH
--
-- The words do not need to be adjacent or in the same order.
-- A product can match several subcategories (by design).
--
-- Performance: names are tokenized ONCE into text[] and compared
-- with array containment (@>). Matching is done on DISTINCT
-- product names first, then fanned out to store_products rows.
-- ------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS store_product_category_matches;

CREATE MATERIALIZED VIEW store_product_category_matches AS
WITH names AS (
    SELECT DISTINCT
        name,
        string_to_array(
            btrim(regexp_replace(name, '[[:space:](),.''"־–—-]+', ' ', 'g')),
            ' '
        ) AS words
    FROM store_products
    WHERE name IS NOT NULL
),
subs AS (
    SELECT
        id,
        category_id,
        name,
        string_to_array(
            btrim(regexp_replace(replace(name, '/', ' '),
                                 '[[:space:](),.''"־–—-]+', ' ', 'g')),
            ' '
        ) AS words
    FROM store_product_subcategories
),
name_matches AS (
    SELECT
        n.name  AS product_name,
        s.id    AS subcategory_id,
        s.name  AS subcategory,
        s.category_id
    FROM names n
    JOIN subs s ON n.words @> s.words
)
SELECT
    sp.chain_id,
    sp.store_id,
    sp.item_code,
    sp.name AS product_name,

    c.id   AS category_id,
    c.name AS category,

    nm.subcategory_id,
    nm.subcategory
FROM store_products sp
JOIN name_matches nm
    ON nm.product_name = sp.name
JOIN store_product_categories c
    ON c.id = nm.category_id;


-- ------------------------------------------------------------
-- MATCH VIEW INDEXES
--
-- (Dropping the view drops its indexes, so they are re-created.)
-- The unique index is required for
--   REFRESH MATERIALIZED VIEW CONCURRENTLY store_product_category_matches;
-- ------------------------------------------------------------

CREATE UNIQUE INDEX IF NOT EXISTS uq_sp_category_matches_row
ON store_product_category_matches (
    chain_id,
    store_id,
    item_code,
    subcategory_id
);

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