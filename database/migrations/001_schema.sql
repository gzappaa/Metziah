-- ============================================================
-- RESET DATABASE (DEV ONLY)
-- ============================================================

DROP TABLE IF EXISTS promotion_items CASCADE;
DROP TABLE IF EXISTS promotion_groups CASCADE;
DROP TABLE IF EXISTS promotions CASCADE;
DROP TABLE IF EXISTS prices CASCADE;
DROP TABLE IF EXISTS store_products CASCADE;
DROP TABLE IF EXISTS file_tracking CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS stores CASCADE;
DROP TABLE IF EXISTS sub_chains CASCADE;
DROP TABLE IF EXISTS chains CASCADE;

DROP EXTENSION IF EXISTS pg_trgm CASCADE;
DROP EXTENSION IF EXISTS postgis CASCADE;


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
-- FILE_TRACKING
-- Tracks every feed file per (chain, store, file_type) -- both
-- download and load state, so failures at either stage are visible
-- and queryable instead of silently drifting.
--
-- Snapshot types (PriceFull, Price, PromoFull, Stores) always
-- REPLACE -- one row per (chain_id, store_id, file_type), enforced
-- by the partial unique index below. A new file just updates the
-- existing row.
--
-- Promo (delta) is the odd one out -- multiple files/day are normal
-- (sometimes zero, sometimes several), so no replace semantics --
-- one row per file, pruned nightly since a new day always requires
-- a fresh PromoFull anyway, making yesterday's deltas irrelevant.
--
-- Stores is chain-wide, not per-store -- store_id is NULL for this
-- type. Nullable rather than a separate table since it shares every
-- other column (downloaded/loaded/filename tracking) with the rest.
-- ============================================================
CREATE TABLE file_tracking (
    id            SERIAL PRIMARY KEY,
    chain_id      TEXT NOT NULL REFERENCES chains(chain_id),
    sub_chain_id  TEXT,
    store_id      TEXT,   -- NULL for file_type='Stores'
    file_type     TEXT NOT NULL CHECK (file_type IN ('PriceFull', 'Price', 'PromoFull', 'Promo', 'Stores')),
    filename      TEXT NOT NULL,
    file_date     DATE NOT NULL,   -- parsed from filename timestamp
    downloaded    BOOLEAN NOT NULL DEFAULT false,
    loaded        BOOLEAN NOT NULL DEFAULT false,
    updated_at    TIMESTAMPTZ DEFAULT now(),

    CHECK (
        (file_type = 'Stores' AND store_id IS NULL)
        OR
        (file_type != 'Stores' AND store_id IS NOT NULL)
    ),

    FOREIGN KEY (chain_id, store_id) REFERENCES stores(chain_id, store_id)
);

-- Snapshot + Stores types: at most ONE row per (chain, store, file_type).
-- store_id being NULL for Stores rows means a plain UNIQUE index would
-- allow multiple NULL store_id rows per chain (Postgres treats NULLs as
-- distinct) -- so Stores needs chain_id alone as its uniqueness key,
-- handled as a separate partial index below.
CREATE UNIQUE INDEX idx_file_tracking_snapshot
ON file_tracking (chain_id, store_id, file_type)
WHERE file_type NOT IN ('Promo', 'Stores');

CREATE UNIQUE INDEX idx_file_tracking_stores
ON file_tracking (chain_id, file_type)
WHERE file_type = 'Stores';

-- Promo (delta): no uniqueness constraint -- multiple rows/day allowed,
-- one per file. Pruned by a daily job, not by a constraint.
CREATE INDEX idx_file_tracking_promo_date
ON file_tracking (chain_id, store_id, file_date)
WHERE file_type = 'Promo';







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
--
-- No has_promo flag here either, same reasoning -- promotions are
-- chain-scoped, this table is global across chains. Promo status
-- lives on `prices`, which is already scoped per (chain, store, item).
-- ============================================================
CREATE TABLE products (
    item_code             TEXT PRIMARY KEY,
    name                  TEXT,
    name_count             INTEGER NOT NULL DEFAULT 1,
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
    store_id              INTEGER NOT NULL REFERENCES stores(id),
    item_code             TEXT NOT NULL,
    name                  TEXT,
    name_count             INTEGER NOT NULL DEFAULT 1,
    manufacturer          TEXT,
    manufacturer_country  TEXT,
    item_type             INTEGER,
    updated_at            TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chain_id, store_id, item_code)
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
-- has_promo is a fast filter flag only, set by the promo loader on
-- the same (chain_id, store_id, item_code) upsert cycle as price.
-- It does NOT identify *which* promotion -- an item can be under
-- multiple simultaneous promotions, so the source of truth for
-- promo details is always promotion_items, joined on
-- (chain_id, store_id, item_code).
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
    has_promo           BOOLEAN NOT NULL DEFAULT false,
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
-- PARTITIONS (prices)
-- One per chain. Add a new one whenever a new chain is onboarded.
-- ============================================================
CREATE TABLE prices_7290661400001 PARTITION OF prices
    FOR VALUES IN ('7290661400001');

-- Repeat for each additional chain, e.g.:
-- CREATE TABLE prices_<chain_id> PARTITION OF prices
--     FOR VALUES IN ('<chain_id>');


-- ============================================================
-- PROMOTIONS
-- Now store-scoped (chain_id, promotion_id, store_id) instead of
-- chain-wide -- each store's PromoFull is treated as a fully
-- independent, authoritative snapshot. Some duplication across
-- stores for shared promo_ids, traded for simpler independent
-- reconciliation per file.
-- ============================================================
CREATE TABLE promotions (
    chain_id                   TEXT NOT NULL REFERENCES chains(chain_id),
    promotion_id                TEXT NOT NULL,
    store_id                    INTEGER NOT NULL REFERENCES stores(id),
    description                 TEXT,
    start_datetime               TIMESTAMPTZ,
    end_datetime                 TIMESTAMPTZ,
    start_hour                   TEXT,
    end_hour                     TEXT,
    promotion_days                TEXT,
    update_time                 TIMESTAMPTZ,
    club_id                     TEXT,
    is_gift_item                 TEXT,
    additional_is_coupon         BOOLEAN,
    allow_multiple_discounts     BOOLEAN,
    redemption_limit              INTEGER,
    min_no_of_items_offered       INTEGER,
    additional_restrictions       TEXT,
    remarks                      TEXT,
    updated_at                   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chain_id, promotion_id, store_id)
);


-- ============================================================
-- PROMOTION_GROUPS
-- FK to promotions now includes store_id (3-column) since
-- promotions is store-scoped. ON DELETE CASCADE -- when a
-- promotion is removed for a store, all its groups (and their
-- items, via the next cascade) go with it automatically.
-- ============================================================
CREATE TABLE promotion_groups (
    chain_id              TEXT NOT NULL,
    promotion_id           TEXT NOT NULL,
    store_id               INTEGER NOT NULL REFERENCES stores(id),
    group_id                TEXT NOT NULL,
    min_purchase_amount     NUMERIC(10,2),
    discount_type           TEXT,
    updated_at              TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chain_id, promotion_id, store_id, group_id),
    FOREIGN KEY (chain_id, promotion_id, store_id)
        REFERENCES promotions(chain_id, promotion_id, store_id)
        ON DELETE CASCADE
);


-- ============================================================
-- PROMOTION_ITEMS
-- FK to promotion_groups unchanged in shape, now ON DELETE CASCADE
-- -- when a group is removed, its items go with it automatically.
-- ============================================================
CREATE TABLE promotion_items (
    chain_id                     TEXT NOT NULL,
    promotion_id                  TEXT NOT NULL,
    store_id                      INTEGER NOT NULL REFERENCES stores(id),
    group_id                       TEXT NOT NULL,
    item_code                      TEXT NOT NULL,
    item_type                      INTEGER,
    reward_type                    INTEGER,
    min_qty                        NUMERIC(10,3),
    max_qty                        NUMERIC(10,3),
    discount_rate                  NUMERIC(10,2),
    discounted_price               NUMERIC(10,2),
    discounted_price_per_mida      NUMERIC(10,2),
    is_weighted                    BOOLEAN,
    updated_at                     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chain_id, promotion_id, store_id, group_id, item_code),
    FOREIGN KEY (chain_id, promotion_id, store_id, group_id)
        REFERENCES promotion_groups(chain_id, promotion_id, store_id, group_id)
        ON DELETE CASCADE
) PARTITION BY LIST (chain_id);

CREATE INDEX idx_promotion_items_store_item
ON promotion_items (store_id, item_code);

CREATE INDEX idx_promotion_items_item_store
ON promotion_items (item_code, store_id);


CREATE TABLE promotion_items_7290661400001 PARTITION OF promotion_items
    FOR VALUES IN ('7290661400001');