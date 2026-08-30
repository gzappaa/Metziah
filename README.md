# Metziah

Metziah is a Python pipeline for ingesting, normalizing, and storing Israeli supermarket price and promotion data. It downloads the XML price and promotion feeds that supermarket chains are legally required to publish under the 2014 Price Transparency regulations (Reshumot 7442), parses them, and loads them into a PostgreSQL database. The pipeline also tracks promotion changes and can send email notifications when relevant promotions are detected.

This is a from-scratch build, written for learning and full control over the design.

## Status

Currently supports a single chain, **Machsanei Hashuk** (`7290661400001`), with a schema and architecture designed to scale to ~50 chains and thousands of stores. See [Roadmap](#roadmap) for what's next.

## How it works

```
laibcatalog.co.il API
        │
        ▼
  Downloaders (prices.py, pricesfull.py, promosfull.py)
        │  gzip'd XML feeds → data/
        ▼
  Parsers (parsers/xml.py)
        │  XML → Product / Promotion domain models
        ▼
  PostgreSQL + PostGIS
        │  products, store_products, prices,
        │  promotions → promotion_groups → promotion_items
        ▼
  Notifications (utils/promo_notifications.py)
     nearby new promos → daily email digest
```

- **Downloaders** pull `.gz` XML feeds (full snapshots and incremental deltas) from the laibcatalog API and manage which files are new, which are stale, and when it's safe to clean up old ones.
- **Parsers** turn raw Price and Promo XML into typed dataclasses (`models/product.py`, `models/promo.py`).
- **Database layer** splits a parsed product into the right tables depending on whether its `item_code` is a real barcode (global, shared across chains) or an internal, store-scoped code (e.g. loose produce, deli items). Promotions are stored as a three-level hierarchy (`promotions` → `promotion_groups` → `promotion_items`) with cascading deletes and a top-down reconciliation pass on each load.
- **`file_tracking`** records the load state of every feed file per store/day, and enforces ordering rules (e.g. a `PromoFull` snapshot must be loaded before incremental `Promo` files for the same store/day are applied).
- **Notifications** run daily, detect newly-added promo items from the day's activity log, filter to stores near a configured location using PostGIS `ST_DWithin`, and send a deduplicated digest email.

## Requirements

- Python 3.11+
- PostgreSQL with the PostGIS extension
- A Gmail (or other SMTP) account for the notification digest (optional — only needed if you enable notifications)

## Setup

1. **Clone and install dependencies**

   ```bash
   git clone <repo-url>
   cd metziah
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Create the database** and enable PostGIS:

   ```sql
   CREATE DATABASE metziah;
   \c metziah
   CREATE EXTENSION postgis;
   ```

3. **Apply the schema**:

   ```bash
   psql -d metziah -f database/migrations/001_schema.sql
   ```

4. **Configure environment variables.** Metziah uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) with separate env files per environment. Create `.env.dev` (and `.env.test` for the test environment) in the project root:

   ```dotenv
   PGHOST=localhost
   PGPORT=5432
   PGUSER=your_user
   PGPASSWORD=your_password
   PGDATABASE=metziah

   ENV=dev
   DEBUG=false

   GEOCODE_API=

   # Promo notifications (optional)
   USER_LAT=
   USER_LON=
   MAX_STORE_DISTANCE_KM=5

   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=
   SMTP_PASSWORD=
   EMAIL_FROM=
   EMAIL_TO=
   ```

   `ENV` gates several safety checks throughout the pipeline (e.g. loaders refuse to write to the wrong database, the scheduler picks real feeds vs. `data/test_feeds/`), so it should always match which `.env.*` file is active.


5. **Download_data**:
   
   ```bash
   python downloaders/pricesfull.py --test
   python downloaders/promossfull.py --test
   ```



6. **Seed store data**:

   ```bash
   python utils/seed_stores.py
   ```

## Running the pipeline

**First run**, bootstrap in this order so `file_tracking` and the database start in a consistent state:

```bash
python utils/load_file_tracking.py
python utils/load_prices.py
python utils/load_promos.py
```

**After that**, the scheduler orchestrates ongoing cycles — downloading full/incremental Price and Promo files and loading whatever is eligible according to `file_tracking`:

```bash
python downloaders/scheduler.py
```

In production this runs on a cron schedule (currently every 15 minutes for price/promo updates, daily at 8am for notifications). To send the promo notification digest manually:

```bash
python utils/promo_notifications.py
```

## Testing

Tests run against a real, separately-seeded PostgreSQL test database rather than mocked connections — integration tests use real `psycopg` connections with rollback-on-teardown. Real `.gz` feed samples live in `data/test_feeds/`.

```bash
cp .env.test.example .env.test   # if starting fresh — fill in your test DB credentials
ENV=test pytest
```

## Project layout

```
├── chains/registry.py          # Known chain IDs/metadata
├── clients/laibcatalog.py      # HTTP client for the laibcatalog feed API
├── config.py                   # pydantic-settings configuration
├── database/
│   ├── migrations/001_schema.sql
│   ├── records.py              # Domain model -> DB-shaped record mapping
│   └── repository.py           # SQL access layer
├── db.py                       # Connection management
├── docs/decisions/             # Architecture decision records
├── downloaders/                # Feed download + scheduling
├── logging_config.py           # Root + isolated (audit) logger setup
├── main.py
├── models/                     # Product, promo, and store dataclasses
├── parsers/xml.py              # XML -> domain model parsing
├── tests/
└── utils/                      # Loaders, store seeding, notifications, mailer
```

## Roadmap

- **Phase 1 (done):** Core pipeline — downloading, parsing, and loading price/promo data end-to-end for a single chain.
- **Phase 2 (current):** Expand ingestion to all supermarket chains using the same laibcatalog API pattern.
- **Phase 3:** Smart cleaning of non-real products (e.g. junk/placeholder item codes) from the data.
- **Later phases:**
- **Final phase:** Dockerize.

## Legal basis

Feed access is based on Israel's 2014 Price Transparency regulations (Reshumot 7442), which require supermarket chains to publish machine-readable price and promotion data.