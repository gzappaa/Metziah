-- ============================================================
-- 003_pharmacy_separation.sql
--
-- Apply after 001_schema.sql and 002_chain_partitions.sql.
-- Only adds a column and two tables; existing data is untouched.
--
-- store_type is filled by utils/stores/mark_pharmacy_stores.py,
-- driven by data/reference/chains_pharms.json.
-- ============================================================

-- Which stores are pharmacies.
ALTER TABLE stores
    ADD COLUMN IF NOT EXISTS store_type TEXT NOT NULL DEFAULT 'supermarket'
    CHECK (store_type IN ('supermarket', 'pharmacy'));

CREATE INDEX IF NOT EXISTS idx_stores_type
ON stores (chain_id, store_type)
WHERE store_type = 'pharmacy';


-- ------------------------------------------------------------
-- PHARMACY_PRODUCTS
--
-- Barcodes (valid GTINs) seen ONLY in pharmacy stores and not
-- present in `products`. No price rows are created for them.
-- A daily job deletes a row once the barcode appears in `products`
-- (a supermarket started carrying it).
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pharmacy_products (
    chain_id              TEXT NOT NULL REFERENCES chains(chain_id),
    item_code             TEXT NOT NULL,
    name                  TEXT,
    manufacturer          TEXT,
    manufacturer_country  TEXT,
    item_type             INTEGER,
    first_seen            TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen             TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (chain_id, item_code)
);

CREATE INDEX IF NOT EXISTS idx_pharmacy_products_item
ON pharmacy_products (item_code);


-- ------------------------------------------------------------
-- PHARMACY_STORE_PRODUCTS
--
-- ALL non-barcode / internal item codes from pharmacy stores.
-- No FK to stores on purpose, so re-seeding stores never blocks it.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pharmacy_store_products (
    chain_id              TEXT NOT NULL REFERENCES chains(chain_id),
    store_id              TEXT NOT NULL,
    item_code             TEXT NOT NULL,
    name                  TEXT,
    manufacturer          TEXT,
    manufacturer_country  TEXT,
    item_type             INTEGER,
    first_seen            TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen             TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (chain_id, store_id, item_code)
);

CREATE INDEX IF NOT EXISTS idx_pharmacy_store_products_name_trgm
ON pharmacy_store_products
USING GIN (name gin_trgm_ops);