-- ============================================================
-- EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS postgis;


-- ============================================================
-- CHAINS
-- ============================================================
CREATE TABLE chains (
    chain_id  TEXT PRIMARY KEY   -- e.g. '7290661400001', from <ChainID>
);

-- ============================================================
-- SUB_CHAINS
-- Kept for feed metadata only (e.g. banner name reporting).
-- NOT used to define store identity -- investigation showed
-- sub_chain grouping isn't reliable enough for that.
-- ============================================================
CREATE TABLE sub_chains (
    id            SERIAL PRIMARY KEY,
    chain_id      TEXT NOT NULL REFERENCES chains(chain_id),
    sub_chain_id  TEXT NOT NULL,    -- e.g. '001', from <SubChainID>
    UNIQUE (chain_id, sub_chain_id)
);

-- ============================================================
-- STORES
-- Identity is chain_id + store_id only. sub_chain_id is stored
-- as plain metadata (nullable, no FK) -- not used for uniqueness
-- or hierarchy.
-- ============================================================
CREATE TABLE stores (
    id            SERIAL PRIMARY KEY,
    chain_id      TEXT NOT NULL REFERENCES chains(chain_id),
    sub_chain_id  TEXT,
    store_id      TEXT NOT NULL,
    store_name    TEXT,
    address       TEXT,
    city          TEXT,
    zip_code      TEXT,
    latitude      NUMERIC(9,6),
    longitude     NUMERIC(9,6),
    location      GEOGRAPHY(Point, 4326)
        GENERATED ALWAYS AS (
            ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
        ) STORED,
    CHECK (
        (latitude IS NULL AND longitude IS NULL)
        OR
        (latitude IS NOT NULL AND longitude IS NOT NULL)
    ),
    UNIQUE (chain_id, store_id)
);

CREATE INDEX idx_stores_location
ON stores
USING GIST (location);


-- ============================================================
-- PRODUCTS
-- Real barcodes ONLY (EAN-8/UPC-A/EAN-13 -- 8, 12, or 13 digit
-- numeric item_code). Barcodes are globally unique and consistent
-- across chains, so this table has ONE row per barcode, shared
-- by every chain that sells it.
--
-- Non-barcode / internal item_codes (loose produce, deli, bakery,
-- etc.) do NOT go here -- they collide across chains and live in
-- store_products instead.
--
-- No unit_qty/unit_measure/weighted/package_quantity here -- those
-- can legitimately differ per store for the same barcode (e.g. sold
-- prepackaged at one branch, loose by weight at another), so they
-- live on `prices` ("how it's sold here"), not here ("what it is").
-- ============================================================
CREATE TABLE products (
    item_code             TEXT PRIMARY KEY,
    name                  TEXT,
    manufacturer          TEXT,
    manufacturer_country  TEXT,
    item_type             INTEGER,
    updated_at            TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_products_name_trgm
ON products
USING GIN (name gin_trgm_ops);

CREATE INDEX idx_products_manufacturer_trgm
ON products
USING GIN (manufacturer gin_trgm_ops);


-- ============================================================
-- STORE_PRODUCTS
-- Non-barcode / internal item_codes. These are assigned by each
-- retailer's own catalog system and are NOT globally unique --
-- two unrelated chains can both use item_code '12345' for two
-- different products. Scoped to (chain_id, item_code): one row
-- per chain, shared across that chain's stores.
--
-- NOTE: this assumes a chain assigns a given internal item_code
-- to the same product at every branch. If that assumption turns
-- out to be false (verified via
-- scripts/check_item_code_consistency.py), this table isn't safe
-- to keep -- name/manufacturer/item_type would need to move onto
-- `prices` directly for non-barcode items instead.
-- ============================================================
CREATE TABLE store_products (
    chain_id              TEXT NOT NULL REFERENCES chains(chain_id),
    item_code             TEXT NOT NULL,
    name                  TEXT,
    manufacturer          TEXT,
    manufacturer_country  TEXT,
    item_type             INTEGER,
    updated_at            TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chain_id, item_code)
);

CREATE INDEX idx_store_products_name_trgm
ON store_products
USING GIN (name gin_trgm_ops);


-- ============================================================
-- PRICES
-- One row per (chain_id, store_id, item_code) = current state, no
-- history. UNIQUE (chain_id, store_id, item_code) is required for
-- the upsert (ADD/CHANGE) pattern. REMOVE is a hard DELETE --
-- item_codes no longer present in a store's latest file get
-- deleted outright.
--
-- item_code has NO foreign key -- it may point at either products
-- (barcodes) or store_products (internal codes) depending on which
-- kind it is, and a single FK column can't reference two tables.
-- Consistency between item_code and its metadata row is enforced
-- by the loader (storage/repository.py), not by Postgres.
--
-- unit_qty/unit_measure/weighted/package_quantity live here, not
-- on products/store_products, since how an item is sold (loose vs.
-- prepackaged, package size) can differ per store even for the
-- same item_code.
--
-- Partitioned by chain_id (LIST) -- ~50 chains expected, not
-- thousands, so one partition per chain is manageable. store_id
-- is NOT the partition key (3,500+ stores would mean too many
-- partitions) -- it's handled via a normal index inside each
-- chain's partition instead.
-- ============================================================
CREATE TABLE prices (
    id                  BIGSERIAL,
    chain_id            TEXT NOT NULL REFERENCES chains(chain_id),
    store_id            INTEGER NOT NULL REFERENCES stores(id),
    item_code           TEXT NOT NULL,
    price               NUMERIC(10,2),
    unit_price          NUMERIC(10,2),
    quantity            NUMERIC(10,3),
    unit_qty            TEXT,
    unit_measure        TEXT,
    weighted            BOOLEAN,
    package_quantity    INTEGER,
    allow_discount      BOOLEAN,
    status              TEXT,
    price_update_time   TIMESTAMPTZ,
    last_sale_datetime  TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, chain_id),
    UNIQUE (chain_id, store_id, item_code)
) PARTITION BY LIST (chain_id);


CREATE INDEX idx_prices_store_item
ON prices (store_id, item_code);

CREATE INDEX idx_prices_item_store
ON prices (item_code, store_id);


-- ============================================================
-- PARTITIONS
-- One per chain. Add a new one whenever a new chain is onboarded.
-- ============================================================
CREATE TABLE prices_7290661400001 PARTITION OF prices
    FOR VALUES IN ('7290661400001');


-- Repeat for each additional chain, e.g.:
-- CREATE TABLE prices_<chain_id> PARTITION OF prices
--     FOR VALUES IN ('<chain_id>');