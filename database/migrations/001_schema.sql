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
    chain_id TEXT PRIMARY KEY
);


-- ============================================================
-- SUB_CHAINS
--
-- Kept for feed metadata only.
-- NOT used to define store identity.
-- ============================================================

CREATE TABLE sub_chains (
    id            SERIAL PRIMARY KEY,
    chain_id      TEXT NOT NULL REFERENCES chains(chain_id),
    sub_chain_id  TEXT NOT NULL,

    UNIQUE (chain_id, sub_chain_id)
);


-- ============================================================
-- STORES
--
-- Store identity is:
--
--     (chain_id, store_id)
--
-- store_id is the actual identifier supplied by the retailer feed.
-- There is NO artificial stores.id.
-- ============================================================

CREATE TABLE stores (
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
            ST_SetSRID(
                ST_MakePoint(longitude, latitude),
                4326
            )::geography
        ) STORED,

    CHECK (
        (latitude IS NULL AND longitude IS NULL)
        OR
        (latitude IS NOT NULL AND longitude IS NOT NULL)
    ),

    PRIMARY KEY (chain_id, store_id)
);


CREATE INDEX idx_stores_location
ON stores
USING GIST (location);


-- ============================================================
-- FILE_TRACKING
--
-- Tracks discovered feed files.
--
-- IMPORTANT:
-- There is intentionally NO foreign key from store_id to stores.
--
-- A file can be discovered/downloaded before:
--   - the store has been seeded
--   - the store exists in the current test DB
--   - the store data has been loaded
--
-- file_tracking is about the feed files themselves, not whether
-- the corresponding store currently exists in the stores table.
--
-- Store files:
--   file_type = 'Stores'
--   store_id = NULL
--
-- All other file types:
--   store_id = actual feed store identifier
--
-- For now we simply insert newly discovered filenames.
-- ============================================================

CREATE TABLE file_tracking (
    id            SERIAL PRIMARY KEY,
    chain_id      TEXT NOT NULL REFERENCES chains(chain_id),
    sub_chain_id  TEXT,
    store_id      TEXT,
    file_type     TEXT NOT NULL CHECK (
        file_type IN (
            'PriceFull',
            'Price',
            'PromoFull',
            'Promo',
            'Stores'
        )
    ),
    filename      TEXT NOT NULL,
    file_date     DATE NOT NULL,
    downloaded    BOOLEAN NOT NULL DEFAULT false,
    loaded        BOOLEAN NOT NULL DEFAULT false,
    updated_at    TIMESTAMPTZ DEFAULT now(),

    CHECK (
        (file_type = 'Stores' AND store_id IS NULL)
        OR
        (file_type != 'Stores' AND store_id IS NOT NULL)
    ),

    UNIQUE (chain_id, filename)
);


-- Promo delta files:
-- multiple files per store/day are allowed.
CREATE INDEX idx_file_tracking_promo_date
ON file_tracking (chain_id, store_id, file_date)
WHERE file_type = 'Promo';


-- Useful for scheduler lookups.
CREATE INDEX idx_file_tracking_downloaded
ON file_tracking (chain_id, downloaded)
WHERE downloaded = false;


CREATE INDEX idx_file_tracking_loaded
ON file_tracking (chain_id, loaded)
WHERE loaded = false;


-- ============================================================
-- PRODUCTS
--
-- Real barcodes ONLY.
-- Globally unique barcode -> one row.
-- ============================================================

CREATE TABLE products (
    item_code             TEXT PRIMARY KEY,
    name                  TEXT,
    name_count            INTEGER NOT NULL DEFAULT 1,
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
--
-- Non-barcode / internal item codes.
--
-- Identity:
--
--     (chain_id, store_id, item_code)
--
-- store_id is the actual retailer store identifier.
-- ============================================================

CREATE TABLE store_products (
    chain_id              TEXT NOT NULL REFERENCES chains(chain_id),
    store_id              TEXT NOT NULL,
    item_code             TEXT NOT NULL,
    name                  TEXT,
    name_count            INTEGER NOT NULL DEFAULT 1,
    manufacturer          TEXT,
    manufacturer_country  TEXT,
    item_type             INTEGER,
    updated_at            TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (chain_id, store_id, item_code),

    FOREIGN KEY (chain_id, store_id)
        REFERENCES stores(chain_id, store_id)
);


CREATE INDEX idx_store_products_name_trgm
ON store_products
USING GIN (name gin_trgm_ops);


-- ============================================================
-- PRICES
--
-- Current state only.
--
-- Identity:
--
--     (chain_id, store_id, item_code)
--
-- No artificial ID.
-- ============================================================

CREATE TABLE prices (
    chain_id            TEXT NOT NULL REFERENCES chains(chain_id),
    store_id            TEXT NOT NULL,
    item_code            TEXT NOT NULL,

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

    PRIMARY KEY (chain_id, store_id, item_code),

    FOREIGN KEY (chain_id, store_id)
        REFERENCES stores(chain_id, store_id)
)
PARTITION BY LIST (chain_id);


CREATE INDEX idx_prices_store_item
ON prices (store_id, item_code);


CREATE INDEX idx_prices_item_store
ON prices (item_code, store_id);


-- ============================================================
-- PRICES PARTITIONS
-- ============================================================

CREATE TABLE prices_7290661400001
PARTITION OF prices
FOR VALUES IN ('7290661400001');


-- ============================================================
-- PROMOTIONS
--
-- Identity:
--
--     (chain_id, promotion_id, store_id)
--
-- Each store's PromoFull is an independent snapshot.
-- ============================================================

CREATE TABLE promotions (
    chain_id                   TEXT NOT NULL REFERENCES chains(chain_id),
    promotion_id               TEXT NOT NULL,
    store_id                   TEXT NOT NULL,

    description                TEXT,
    start_datetime             TIMESTAMPTZ,
    end_datetime               TIMESTAMPTZ,
    start_hour                 TEXT,
    end_hour                   TEXT,
    promotion_days             TEXT,
    update_time                TIMESTAMPTZ,
    club_id                    TEXT,
    is_gift_item               TEXT,
    additional_is_coupon      BOOLEAN,
    allow_multiple_discounts  BOOLEAN,
    redemption_limit          INTEGER,
    min_no_of_items_offered   INTEGER,
    additional_restrictions   TEXT,
    remarks                    TEXT,
    updated_at                 TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (chain_id, promotion_id, store_id),

    FOREIGN KEY (chain_id, store_id)
        REFERENCES stores(chain_id, store_id)
);


-- ============================================================
-- PROMOTION_GROUPS
-- ============================================================

CREATE TABLE promotion_groups (
    chain_id              TEXT NOT NULL,
    promotion_id          TEXT NOT NULL,
    store_id              TEXT NOT NULL,
    group_id              TEXT NOT NULL,

    min_purchase_amount   NUMERIC(10,2),
    discount_type         TEXT,
    updated_at            TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (
        chain_id,
        promotion_id,
        store_id,
        group_id
    ),

    FOREIGN KEY (
        chain_id,
        promotion_id,
        store_id
    )
    REFERENCES promotions(
        chain_id,
        promotion_id,
        store_id
    )
    ON DELETE CASCADE
);


-- ============================================================
-- PROMOTION_ITEMS
-- ============================================================

CREATE TABLE promotion_items (
    chain_id                     TEXT NOT NULL,
    promotion_id                 TEXT NOT NULL,
    store_id                    TEXT NOT NULL,
    group_id                     TEXT NOT NULL,
    item_code                    TEXT NOT NULL,

    item_type                    INTEGER,
    reward_type                  INTEGER,
    min_qty                      NUMERIC(10,3),
    max_qty                      NUMERIC(10,3),
    discount_rate                NUMERIC(10,2),
    discounted_price             NUMERIC(10,2),
    discounted_price_per_mida    NUMERIC(10,2),
    is_weighted                  BOOLEAN,
    updated_at                   TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (
        chain_id,
        promotion_id,
        store_id,
        group_id,
        item_code
    ),

    FOREIGN KEY (
        chain_id,
        promotion_id,
        store_id,
        group_id
    )
    REFERENCES promotion_groups(
        chain_id,
        promotion_id,
        store_id,
        group_id
    )
    ON DELETE CASCADE
)
PARTITION BY LIST (chain_id);


CREATE INDEX idx_promotion_items_store_item
ON promotion_items (store_id, item_code);


CREATE INDEX idx_promotion_items_item_store
ON promotion_items (item_code, store_id);


-- ============================================================
-- PROMOTION_ITEMS PARTITIONS
-- ============================================================

CREATE TABLE promotion_items_7290661400001
PARTITION OF promotion_items
FOR VALUES IN ('7290661400001');