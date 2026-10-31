# Metziah

[![Tests](https://github.com/gzappaa/metziah/actions/workflows/tests.yml/badge.svg)](.github/workflows/tests.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![PostgreSQL + PostGIS](https://img.shields.io/badge/PostgreSQL-PostGIS%2016-336791)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688)
![License: source-available](https://img.shields.io/badge/license-source--available-lightgrey)

**Metziah** (מציאה, "a bargain") is a Python data platform for Israeli supermarket prices. It downloads the price, promotion and store feeds that chains are legally required to publish, normalizes them, **enriches products with scraped metadata, images and nutrition facts**, and stores everything in PostgreSQL + PostGIS. A FastAPI service exposes the result as a versioned JSON REST API and a small HTMX web interface.

The main goal is an **accurate, reliable, continuously updated dataset**. The API and website exist to expose and demonstrate that data. They are intentionally simple (see [ADR 016](docs/decisions/016-REST_API_and_WEB_API.md)).

<img width="800" height="392" alt="project" src="https://github.com/user-attachments/assets/c20da7bc-f9bd-495f-b148-fa62448b220e" />



## At a glance

| | |
|---|---|
| Feed files processed | 15,000+ per day |
| Chains | 33 supermarket chains (plus pharmacy chains, stored separately) |
| Stores | ~2,369, about 90% geocoded |
| Products | ~550,000 unique products, ~200,000 in the global barcode catalog |
| Price records | ~14 million records tracking individual products sold by stores at specific prices |
| Promotion items | ~30.9 million as published by retailers* |
| **Scraped products** | **~48,000** products scraped from retailer websites |
| **Product images** | **~48,000** product images downloaded and served by the API |
| **Nutrition data** | **16,000+** products with parsed, normalized nutrition facts |

*Approximately 30 million promotion items before data cleaning, including anomalies, and 20 million after cleaning in production.*

> Figures are snapshots and may lag behind the live database. Enrichment numbers count scraped and parsed output. Run the reports in `inspection/data_quality/` for current coverage against the production price listings.

## Features

- **Multi-protocol ingestion.** One client per distinct feed protocol: Laib Catalog, BinaProjects, PublishedPrices, Carrefour, Mishnat Yosef, Wolt and generic HTML endpoints.
- **Full and delta feeds.** `PriceFull` and `PromoFull` snapshots are loaded before the incremental `Price` and `Promo` files, and the order is enforced by file tracking.
- **File tracking.** Per-store, per-day load state for every feed file, with file-size metadata.
- **Two product identities.** Real cross-chain barcodes are kept separate from store-scoped internal codes. Product identity and price identity are also separate.
- **Chain-partitioned tables.** `prices` and `promotion_items` are partitioned by `chain_id`.
- **Product enrichment at scale.** Retailer websites are scraped (JSON dumps, server-rendered pages and replayed JSON APIs), parsed to JSONL and merged into `product_enrichment`. Names, brands, descriptions, ingredients and category paths are canonicalized.
- **Nutrition facts.** About 120 Hebrew and English label spellings are mapped to canonical nutrients, units are converted, and each value is tagged with its basis (per 100 g, per 100 ml, per serving, %DV). Nothing is dropped silently, and the raw scrape is kept so rows can be rebuilt.
- **Product images.** One image per barcode, stored by `item_code` and served by the web interface with a placeholder fallback.
- **Store-product categories.** Products sold by weight or prepared in store, such as chicken breast, are categorized with a manually maintained keyword vocabulary.
- **Pharmacy separation.** Pharmacy chains and stores are kept apart from supermarkets.
- **Data cleaning.** Conservative rules remove suspicious products and orphan promotion items from production data.
- **Monitoring and inspection.** Health checks for sources, missing chains and stores, filename drift and full-vs-delta consistency, plus ad-hoc data-quality and scraper-coverage reports.
- **Analytics and notifications.** Log parsing, price and promo change detection, and an optional email digest of promotions near a configured location.
- **REST API and web UI.** Versioned JSON endpoints under `/api/v1/`, interactive Swagger docs and a server-rendered HTMX site.

## How it works

```
Chain feed sources
(laibcatalog, binaprojects, publishedprices, carrefour,
 mishnatyosef, wolt, generic HTML)
        │
        ▼
  clients/            one client per feed protocol
        │
        ▼
  downloaders/        shared full/delta download logic, runner, scheduler
        │             → raw feed files in data/
        ▼
  parsers/xml.py      XML → typed models (models/)
        │
        ▼
  utils/              load_*.py (thin CLI) + update_*.py (logic):
        │             products, prices, promos, stores, file tracking
        ▼
  database/           repository.py (SQL) + records.py + migrations
        │             PostgreSQL + PostGIS
        ├──────────────► api/          FastAPI: REST API + HTMX website
        ├──────────────► analytics/    log parsing → change detection → email
        └──────────────► monitoring/   source health and consistency checks

  Enrichment (see "Product enrichment pipeline")
  scrapers/ ─► data/raw*/ ─► parsers/ ─► data/parsed/*.jsonl ─► utils/products/load_*
  (retailer      raw JSON      product_json,   one JSONL per       product_enrichment,
   sites)        per product   page_type1/2    retailer            product_nutrition
                                                                    + data/images/products/
```

### Key design decisions

The reasoning behind the architecture is documented as ADRs in [`docs/decisions/`](docs/decisions/):

| ADR | Topic |
|---|---|
| [001](docs/decisions/001-geocoding-provide.md) | Google Geocoding API instead of GovMap |
| [002](docs/decisions/002-separate-product-and-price-identity.md.md) | Separate product and price identity |
| [003](docs/decisions/003-logging-architecture.md) | Logging architecture |
| [004](docs/decisions/004-file_tracking.md), [006](docs/decisions/006-file-size-metadata.md) | File tracking and file-size metadata |
| [005](docs/decisions/005-yellow_stores.md) | "Yellow" stores |
| [007](docs/decisions/007-chains_extra.md) | Extra (non-standard) chains |
| [008](docs/decisions/008-store-identity.md) | Store identity |
| [009](docs/decisions/009-downloaders.md) | Shared downloader architecture |
| [010](docs/decisions/010-snapshot_prices.md) | Snapshot prices |
| [011](docs/decisions/011-partitions.md) | Chain-specific table partitions |
| [012](docs/decisions/012-pharmacies_separation.md) | Pharmacies separation |
| [013](docs/decisions/013-product_enrichment.md) | Product enrichment and metadata normalization |
| [014](docs/decisions/014-simple_data_cleaning.md) | Conservative data cleaning |
| [015](docs/decisions/015-store_product_normalization.md) | Store-product category normalization |
| [016](docs/decisions/016-REST_API_and_WEB_API.md) | Separate REST API and web interface |
| [017](docs/decisions/017-barcode_fallback_scraping.md) | Barcode fallback scraping |

## Requirements

- Python 3.12
- PostgreSQL 16 with PostGIS (`postgis/postgis:16-3.4` via Docker, or a local install). The schema also uses `pg_trgm`.
- Docker and Docker Compose (recommended)
- Optional: a Google Geocoding API key for store geocoding
- Optional: an SMTP account for the promotion notification digest
- Optional: Playwright browsers, only if you run the scrapers

## Getting started

### 1. Install

```bash
git clone <repo-url>
cd metziah
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment files

Settings are loaded by [`config.py`](config.py) (pydantic-settings) from `.env.{ENV}`. `ENV` is `dev`, `test` or `prod` and defaults to `test`. Create the files you need in the project root:

```dotenv
PGHOST=localhost
PGPORT=5432
PGUSER=your_user
PGPASSWORD=your_password
PGDATABASE=metziah

ENV=dev
DEBUG=false

GEOCODE_API=

# Promotion notifications (optional)
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

`ENV` gates several safety checks, such as which database is written to and which feed directory is used. Keep it consistent with the active `.env.*` file. `.env*` files are git-ignored.

### 3. Start the database

```bash
make docker-up
```

On first boot [`docker/init-db.sh`](docker/init-db.sh) creates the `metziah_test` database and enables PostGIS on both `metziah` and `metziah_test`.

### 4. Apply migrations

```bash
make migrate        # development database
make migrate-test   # test database
```

Migrations live in [`database/migrations/`](database/migrations/):

| File | Purpose |
|---|---|
| `001_schema.sql` | Core schema: chains, stores, file tracking, products, prices, promotions |
| `002_chain_partitions.sql` | Per-chain partitions for `prices` and `promotion_items` |
| `003_pharmacies.sql` | Pharmacy separation |
| `004_product_enrichment.sql` | Product enrichment and nutrition tables |
| `005_store_product_categories.sql` | Store-product category matching |

`make migrate` applies `001` and `002`, and `make migrate-test` applies `001` to `003`. Apply `004` and `005` with `psql` where you need them. `make enrich-prod` does this for the production database.

### 5. Run first-time setup

```bash
make setup         # development (ENV=dev)
make setup-test    # test (ENV=test)
make setup-prod    # production (ENV=prod)
```

Each target runs the full bootstrap in order:

1. Download store files and build the store registry
2. Load file-tracking history
3. Resolve hidden or ambiguous chains and normalize chain IDs
4. Normalize city metadata and clean City Market addresses
5. Geocode stores (skipped in production)
6. Seed stores and add stores missing from `Stores.xml`
7. Load `PriceFull` and `PromoFull` snapshots
8. Load and resolve products, prices and promotions
9. Run the scheduler once

Run `make help` for a summary of all targets.

## Usage

### Run the ingestion pipeline

After setup, the scheduler downloads and loads whatever is eligible according to file tracking:

```bash
ENV=dev python -m downloaders.scheduler
```

In production this runs on a cron schedule. Everything is invoked as a module (`python -m package.module`), not by file path.

## Product enrichment pipeline

Feeds give prices and a barcode, but names are noisy and there are no images, ingredients or nutrition facts. Enrichment fills that gap from the retailers' own websites. The current dataset holds **~48,000 scraped products, ~48,000 product images and 16,000+ products with parsed nutrition**.

### Stages

| Stage | What happens | Code |
|---|---|---|
| 1. Scrape | Retailer sites are scraped per barcode. Chain JSON dumps go to `data/raw/<retailer>/`, and product pages go to `data/raw_product_pages/<retailer>/<item_code>.json`. | `scrapers/generic.py`, `scrapers/product_pages/` |
| 2. Parse | Raw dumps become flat records. A missing barcode can be recovered from a GS1 image URL when the GTIN is valid. | `parsers/product_json.py`, `parsers/product_page_type1.py`, `parsers/product_page_type2.py` |
| 3. Generate JSONL | One `products_parsed*.jsonl` file per retailer under `data/parsed/`. | `utils/processing/generate_product_jsonl.py` |
| 4. Load | The retailer with the most parsed barcodes is the source of truth. Others only add missing products and fill empty fields. Raw category paths are mapped to canonical category and subcategory through `data/reference/categories.json`. | `utils/products/load_products_enriched.py` |
| 5. Nutrition | Scraped nutrition rows are normalized into `product_nutrition`. | `utils/processing/normalize_nutritional.py`, `utils/products/load_products_nutrition.py` |
| 6. Images | One image per barcode is saved to `data/images/products/{item_code}.jpg`. Existing files are skipped. | `utils/processing/download_img.py`, `utils/processing/download_all_product_images.py` |

### Product-page scraper

`scrapers/product_pages/scraper.py` needs one example product URL per supermarket in `scrapers/product_pages/product_urls.txt`. The barcode in that URL is swapped for every item code in the database. The site's page type is detected once:

- **Type 1, server-rendered.** The product content is parsed from the HTML (`.productContainer` sections).
- **Type 2, JSON API.** The product request is captured from the example page's network traffic, then replayed per item code with plain HTTP and no browser. Requests are throttled adaptively and retried with backoff on `429` and `5xx`.

New page structures are added as `scrapers/product_pages/type_*.py` modules. Runs are resumable: items that already have a file are skipped, items the site does not have are written to `_missing.txt`, and failures save nothing so the next run retries them.

```bash
python -m scrapers.product_pages.scraper --item 7290110115227            # one item from every site, print only
python -m scrapers.product_pages.scraper --item 7290110115227 --save     # same, and save found items
python -m scrapers.product_pages.scraper --limit 20                      # first 20 unsaved codes per site
python -m scrapers.product_pages.scraper                                 # everything unsaved, in chunks
```

### Nutrition normalization

Every nutrition row is normalized into a comparable shape:

- **Label.** About 120 Hebrew and English spellings map to one canonical nutrient key, such as `calories`, `total_fat`, `sodium` or `vitamin_b12`.
- **Unit.** Values are converted to the nutrient's canonical unit (`kcal`, `g`, `mg`, `mcg`).
- **Basis.** The scraped size field becomes what the number is per: 100 g, 100 ml, serving or %DV.
- **Duplicates.** If the same nutrient and basis appear twice in a product, only the first row is marked canonical (`is_canonical`).
- **Flags.** `unmapped`, `unit_missing` and `unit_mismatch` mark rows that need attention. Unknown labels are kept, so the mapping can be extended later and the rows rebuilt from `nutrition_raw`.

To support a new spelling from a new retailer, add it to the label list of the right key in `SPEC`.

### Run it

```bash
make enrich-prod          # detect pharmacies → scrape → generate JSONL → migrate → load
make enrich-prod-images   # download product images (slow, run only when needed)
```

The pipeline scrapes every retailer marked `available` in `data/reference/chains_extra.json`. To run a stage on its own, use the module directly, for example:

```bash
ENV=prod python -u -m utils.products.load_products --prod
python -m utils.processing.download_img --item-code 7290019431169
python -m utils.processing.download_img --all
```

### Coverage checks

`inspection/scrapers/` has reports for parsed barcodes, fields, image URLs, nutrition and category mapping. `inspection/data_quality/analyze_images_coverage.py` measures image coverage, and `monitoring.scraper_coverage` tracks which retailers are covered.

## REST API

The API is a FastAPI app (`api/main.py`) with a thin routing layer (`api/routes_api.py`), a service layer (`api/service.py`), SQL in `api/queries.py` and Pydantic response models in `api/schemas.py`. It serves the **whole catalog**: enrichment is optional metadata, not a requirement for a product to appear.

Everything is read-only JSON under `/api/v1`. The same data backs the HTMX website, and a parity test keeps the two in sync.

| URL | Description |
|---|---|
| `http://localhost:8000/` | Website |
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/openapi.json` | OpenAPI schema |

### Run locally

```bash
ENV=prod uvicorn api.main:app --reload
```

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check, returns `{"status": "ok"}` |
| `GET /stats` | Catalog totals: stores, brands and fresh products |
| `GET /categories/packaged` | Packaged-product categories with counts and subcategories |
| `GET /products?category=` | Enriched packaged products in a category |
| `GET /products/search?q=` | Search enriched products. Each hit has its cheapest price and store count |
| `GET /products/unenriched?q=` | Browse or search products that have no enrichment |
| `GET /products/{barcode}` | Full detail for any barcode, enriched or not |
| `GET /fresh/categories` | Fresh-product categories in display order, with counts |
| `GET /fresh/categories/{category_id}/subcategories` | Subcategories of a fresh category |
| `GET /fresh/products?subcategory_id=` | Distinct fresh products in a subcategory, cheapest first |
| `GET /fresh/products/detail?name=&subcategory_id=` | Price and active promotions for a fresh product in every store |
| `GET /fresh/search?q=` | Search fresh (unbarcoded) products by name or item code |

List endpoints take `limit` (1 to 100) and `offset`, and return `{items, total, limit, offset}`. `/products/{barcode}` is declared after `/products/search` and `/products/unenriched` so those paths are not captured as barcodes.

### Example requests

```bash
curl "http://localhost:8000/api/v1/stats"
curl "http://localhost:8000/api/v1/products/search?q=שוקולד&limit=10"
curl "http://localhost:8000/api/v1/products/7290019431169"
curl "http://localhost:8000/api/v1/fresh/search?q=חזה עוף"
```

### Product detail response

`GET /products/{barcode}` returns one object with four parts:

```
{
  "product":     { item_code, name, manufacturer, name_he, name_en, brand_he, brand_en,
                   category_he, subcategory_he, ingredients_he, ... },
  "prices":      [ { chain, store, address, city, latitude, longitude,
                     price, unit_price, quantity, unit_measure, weighted,
                     price_update_time, ... } ],
  "promotions":  [ { promotion_id, store, description, start_datetime, end_datetime,
                     discount_type, min_qty, discounted_price, discount_rate, club_id, ... } ],
  "enrichment":  { source, category_path_he, category_path_en, ...,
                   nutrition: [ { nutrient, amount, unit, basis, bound, flags, is_canonical } ] }
}
```

`enrichment` is `null` when a product has no scraped metadata. Prices and promotions carry the chain's Hebrew and English names, brand list and store coordinates, so a client can sort by price or distance without extra calls.

### Images

Product images are served by the website routes, not under `/api/v1`:

- `GET /img/{item_code}` returns the product image, or a neutral SVG placeholder when none exists.
- `GET /brand-logo/{brand_name}` returns a brand logo, or the same placeholder.

Images are read from `data/images/`, so mount that directory into the API container in production.

### Analytics and notifications

```bash
ENV=dev python -m analytics.runner                          # parse logs, detect price/promo changes
ENV=dev python -m analytics.notifications.promo_notifications   # send the promotion digest
```

Notifications use `USER_LAT`, `USER_LON` and `MAX_STORE_DISTANCE_KM` from your env file, and the SMTP settings.

### Monitoring and inspection

```bash
ENV=dev python -m monitoring.chains_missing
ENV=dev python -m monitoring.stores_missing
ENV=dev python -m monitoring.check_full_x_delta
ENV=dev python -m monitoring.scraper_coverage
```

`inspection/` holds ad-hoc reports for data quality, items, scrapers, stores and file tracking. Run them the same way, for example `python -m inspection.stores.stores_data_report`.

## Docker

The compose file defines the `db` (PostGIS 16) and `app` (the Python image, which idles so you can run commands inside it) services. Production adds an `api` service that runs the FastAPI server on port 8000.

### Development

```bash
docker compose --env-file .env.dev up -d db
docker compose --env-file .env.dev up -d app

# run any command in the app container
docker compose --env-file .env.dev exec app make setup

# run against the test database
docker compose --env-file .env.dev exec -e PGDATABASE=metziah_test app make setup-test

# open psql
docker compose --env-file .env.dev exec db psql -U <user> -d metziah
```

Other helpers: `make docker-down`, `make docker-logs`, `make docker-reset` (destroys the volume and recreates the database).

### Production

All commands use `--env-file .env.prod`. Run them from the project directory (`cd ~/metziah`).

**First deployment**

```bash
# 1. Build the image
docker compose --env-file .env.prod build

# 2. Start the database and wait until PostgreSQL reports healthy
docker compose --env-file .env.prod up -d db
docker compose --env-file .env.prod ps

# 3. Start the application container
docker compose --env-file .env.prod up -d app

# 4. Run the production setup (needs the app container running)
docker compose --env-file .env.prod exec -T app make setup-prod

# 5. Run database migrations from a shell inside the app container
docker compose --env-file .env.prod exec app bash
PGUSER=postgres PGDATABASE=metziah_prod make migrate
PGUSER=postgres PGDATABASE=metziah_test make migrate    # test database

# 6. Start the API and check all services
docker compose --env-file .env.prod up -d api
docker compose --env-file .env.prod ps
```

Then open:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- OpenAPI: `http://localhost:8000/openapi.json`

**Day-to-day commands**

```bash
# Run a Python module
docker compose --env-file .env.prod exec -T app env ENV=prod python -u -m MODULE_NAME
# e.g. load products
docker compose --env-file .env.prod exec -T app env ENV=prod python -u -m utils.products.load_products --prod

# Run a Makefile target
docker compose --env-file .env.prod exec -T app make TARGET_NAME

# Logs
docker compose --env-file .env.prod logs -f api
docker compose --env-file .env.prod logs -f db
docker compose --env-file .env.prod logs -f app

# Restart the API
docker compose --env-file .env.prod restart api
```

**Updating after code or dependency changes**

```bash
docker compose --env-file .env.prod build
docker compose --env-file .env.prod up -d --force-recreate app api
```

**Stopping**

```bash
docker compose --env-file .env.prod down
```

> **Do not use `down -v`** unless you intentionally want to delete the PostgreSQL volume and all its data.

## Testing

```bash
make test        # ENV=test pytest -v
```

The suite uses a real, separately seeded PostgreSQL test database instead of mocked connections. It covers clients, downloaders, parsers, scrapers, repository and records, the pipeline utilities (including nutrition normalization and image download), monitoring, analytics, the API (queries, service layer, route parity and web pages), and full-lifecycle integration tests. Fixtures include synthetic XML feeds and parsed product files under `tests/fixtures/`. Tests marked `integration` use the real test database.

CI ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)) starts a `postgis/postgis:16-3.4` service, applies migrations `001` to `005`, and runs `pytest --import-mode=importlib` on every push and pull request to `main`.

## Project structure

```
metziah/
├── api/                 FastAPI app: routes_api, routes_web, service, queries, schemas,
│                        Jinja templates, static files
├── analytics/           Log parsers, price/promo change detection, email notifications
├── clients/             One client per feed protocol (BinaProjects, Carrefour, Laib Catalog,
│                        Mishnat Yosef, PublishedPrices, Wolt, generic HTML)
├── database/            migrations/, records.py (model → DB record), repository.py (SQL layer)
├── data/
│   ├── reference/       Chains, categories, vocabularies, CBS localities, ignored stores
│   ├── raw/             Raw chain product JSON dumps (git-ignored)
│   ├── raw_product_pages/  Raw scraped product pages per retailer (git-ignored)
│   ├── parsed/          Parsed product JSONL per retailer (git-ignored)
│   ├── images/          Product images, named by item_code (git-ignored)
│   └── archive/         Archived reference data
├── docker/              Container entrypoint and DB init script
├── docs/
│   ├── decisions/       Architecture decision records
│   ├── extras/          Schema diagrams
│   └── regulations/     Price Transparency regulations (Hebrew)
├── downloaders/         common, full_family, delta_family, prices/promos(+full), stores, runner, scheduler
├── inspection/          Ad-hoc data-quality, scraper and audit reports
├── models/              Chain, product, promo and store models
├── monitoring/          Source health, missing chains/stores, filename drift, full-vs-delta checks
├── parsers/             xml.py (feeds), product_json.py, product_page_type1.py, product_page_type2.py
├── scrapers/            generic.py, browser.py, product_pages/ (type_1, type_2, scraper)
├── tests/               Unit and integration tests mirroring the package layout
├── utils/               load_*/update_* pipelines, file tracking, store enrichment, processing
├── config.py            Settings (pydantic-settings, per-ENV)
├── db.py                Connection management
├── logging_config.py    Root and isolated (audit) loggers
├── Dockerfile · docker-compose.yml · Makefile · pytest.ini · requirements.txt
└── LICENSE
```

`utils/` follows a consistent pattern: `load_*.py` is a thin CLI wrapper and `update_*.py` holds the logic.

## Data model

The main tables are `chains`, `sub_chains`, `stores`, `file_tracking`, `products`, `store_products`, `prices`, `promotions`, `promotion_groups` and `promotion_items`. Enrichment adds `product_enrichment` (names, brand, category path and canonical category, description, ingredients, source and raw nutrition), `product_nutrition` (one normalized row per nutrient and basis) and a `store_product_category_matches` materialized view. Promotions form a `promotions → promotion_groups → promotion_items` hierarchy that is reconciled on each load. See [`docs/extras/`](docs/extras/) for the schema diagrams.

## Roadmap

- [x] **Phase 1:** Core pipeline: download, parse and load price and promo data end to end.
- [x] **Phase 2:** Multi-chain expansion, promotion notifications, monitoring, Dockerization.
- [x] **Phase 3:** Product enrichment, name canonicalization, store-product categories, conservative data cleaning.
- [x] **Phase 4:** REST API and web interface.
- [x] **Phase 5:** Enrichment at scale (~48k scraped products and images, 16k+ parsed nutrition records), barcode fallback scraping, production Docker deployment with a dedicated API service.

## Legal basis

Feed access rests on Israel's **Regulations for the Promotion of Competition in the Food Industry (Price Transparency), 2014** (Reshumot 7442), which require large supermarket chains to publish machine-readable price and promotion data. The feed structure is government-mandated, so it is known in advance and was not reverse-engineered. The regulation text is in [`docs/regulations/`](docs/regulations/).

## License

Metziah is released under a custom **source-available** license (see [LICENSE](./LICENSE)), not an OSI-approved open-source license. In short, you may view, run, modify and share it for non-commercial use with attribution. Commercial use requires the author's prior written consent. Contributions are licensed back to the author as described in the license. Read the full text before reusing any part of the project.

Created by [gzappaa](https://github.com/gzappaa).
