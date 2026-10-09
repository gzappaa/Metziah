-- 004_product_enrichment.sql

BEGIN;

CREATE TABLE IF NOT EXISTS product_enrichment (
    item_code        TEXT NOT NULL,        -- = barcode, joins to products.item_code
    source           TEXT NOT NULL,        -- source company, e.g. 'super yuda'
    source_file      TEXT,

    local_name       TEXT,
    name_he          TEXT,
    name_en          TEXT,

    brand_he         TEXT,
    brand_en         TEXT,
    family_he        TEXT,
    family_en        TEXT,
    department_he    TEXT,

    -- Raw source taxonomy, exactly as scraped. Input to the category mapping.
    category_path_he TEXT[],
    category_path_en TEXT[],

    -- Canonical taxonomy, derived from category_path_he by Python
    -- using the category mapping JSON. NULL = no match (gap report).
    category_he      TEXT,
    subcategory_he   TEXT,

    ingredients_he   TEXT,
    ingredients_en   TEXT,
    description_he   TEXT,
    description_en   TEXT,

    nutrition_raw    JSONB,                -- nutrition fields exactly as scraped

    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (item_code)
);

CREATE INDEX IF NOT EXISTS idx_pe_item_code
    ON product_enrichment (item_code);

CREATE INDEX IF NOT EXISTS idx_pe_brand_he
    ON product_enrichment (brand_he);

CREATE INDEX IF NOT EXISTS idx_pe_cat_he
    ON product_enrichment USING GIN (category_path_he);

CREATE INDEX IF NOT EXISTS idx_pe_category_he
    ON product_enrichment (category_he);

CREATE INDEX IF NOT EXISTS idx_pe_subcategory_he
    ON product_enrichment (category_he, subcategory_he);

CREATE INDEX IF NOT EXISTS idx_pe_nut_raw
    ON product_enrichment USING GIN (nutrition_raw);


-- Normalized nutrition: derived from nutrition_raw by Python,
-- rebuildable at any time.
CREATE TABLE IF NOT EXISTS product_nutrition (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_code    TEXT NOT NULL,
    source       TEXT NOT NULL,
    raw_label    TEXT NOT NULL,                  -- exactly as scraped (cleaned)
    nutrient     TEXT,                           -- canonical key, NULL = unmapped
    amount       NUMERIC,
    unit         TEXT,
    bound        TEXT,                           -- 'lt' | 'min' | 'max' | NULL
    basis        TEXT NOT NULL DEFAULT 'unknown',-- '100g', '100g:cooked', '100ml', 'serving', 'percent_dv'...
    basis_raw    TEXT NOT NULL DEFAULT '',       -- original "size" text
    flags        TEXT[] NOT NULL DEFAULT '{}',   -- unmapped | unit_missing | unit_mismatch
    is_canonical BOOLEAN NOT NULL DEFAULT true,  -- false = duplicate of same nutrient+basis

    FOREIGN KEY (item_code)
        REFERENCES product_enrichment (item_code)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pn_raw
    ON product_nutrition (item_code, source, raw_label, basis_raw);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pn_canonical
    ON product_nutrition (item_code, source, nutrient, basis)
    WHERE is_canonical AND nutrient IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pn_item
    ON product_nutrition (item_code);

CREATE INDEX IF NOT EXISTS idx_pn_nutrient
    ON product_nutrition (nutrient, basis);

CREATE INDEX IF NOT EXISTS idx_pn_unmapped
    ON product_nutrition (raw_label)
    WHERE nutrient IS NULL;

COMMIT;