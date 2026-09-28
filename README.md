# Metziah

Metziah is a Python data pipeline for collecting, processing, and storing comprehensive Israeli supermarket price, promotion, and store data. Its primary goal is to build a reliable, continuously updated source of supermarket data across chains and stores, providing a foundation for price comparison, promotion discovery, data analysis, and other applications.

The current version processes 15,000+ feed files per day, covering approximately 2,369 stores, 822,000 unique products, 30.9 million promotion items*, and 33 chains across multiple publishing platforms and data sources. The pipeline is extensively tested to ensure reliable and consistent data processing.

It downloads the XML feeds published by supermarket chains under Israel's 2014 Price Transparency regulations (Reshumot 7442), parses and normalizes the data, and loads it into PostgreSQL + PostGIS. The pipeline tracks files and data changes over time, handles full and incremental feeds, and provides monitoring, inspection, and daily promotion notifications.

This is a from-scratch build, designed for flexibility, experimentation, and full control over the architecture.

*The promotion count reflects the records published by the retailers and may be misleading due to how some publishers represent and repeat promotion data. For this version, the focus is on reliably ingesting and processing the published data rather than analyzing or correcting such anomalies.*



## Status

Ingests from 33 chains across several distinct feed protocols (see `data/reference/chains.json` / `chains_extra.json`), with schema and architecture designed to scale to the full set of ~2,500 stores nationwide. See [Roadmap](#roadmap) for what's next.

## How it works

```
Chain feed sources (laibcatalog, binaprojects, publishedprices,
carrefour, mishnatyosef, wolt, generic HTML endpoints)
        │
        ▼
  clients/          per-source client, one per feed protocol
        │
        ▼
  downloaders/      common.py + full_family.py / delta_family.py + runner.py
        │             gzip'd XML feeds → data/
        ▼
  parsers/xml.py    XML → Product / Promo domain models (models/)
        │
        ▼
  utils/update_*    normalization, product/price/promo reconciliation
        │
        ▼
  database/         repository.py (SQL access) + migrations
        │             PostgreSQL + PostGIS: products, prices, promotions
        ▼
  analytics/        log parsing → price/promo change detection → mailer
  monitoring/          source health, missing chains/stores, full-vs-delta checks
```

- **`clients/`** — one client class per genuinely distinct feed protocol (BinaProjects, Carrefour, LaibCatalog, MishnatYosef, PublishedPrices, Wolt, generic HTML).
- **`downloaders/`** — shared full/delta download orchestration (`common.py`, `full_family.py`, `delta_family.py`) plus a `runner.py` and `scheduler.py` for ongoing cycles.
- **`parsers/xml.py`** — turns raw Price/Promo/Store XML into typed models.
- **`database/`** — `repository.py` is the SQL access layer; product identity is split between real (shared, cross-chain) barcodes and internal store-scoped codes; promotions are stored as a `promotions → promotion_groups → promotion_items` hierarchy with reconciliation on each load.
- **`utils/file_tracking/`** — records per-store/day load state for every feed file and enforces ordering (e.g. a `PriceFull`/`PromoFull` snapshot must load before incremental files for that store/day are applied).
- **`analytics/`** — parses pipeline logs (`log_parsers/`), detects price/promo changes, and sends a deduplicated notification digest (`notifications/mailer.py`, `promo_notifications.py`).
- **`monitoring/`** — health checks: missing chains/stores, duplicate stores, filename pattern drift, full-vs-delta feed consistency, source staleness vs. the government registry.
- **`inspection/`** — ad-hoc reports for data quality (invalid item codes, naming inconsistencies, store/file audits).

## Requirements

- Python 3.12
- PostgreSQL with the PostGIS extension (`postgis/postgis:16-3.4` via Docker, or a local install)
- A Gmail (or other SMTP) account for the notification digest (optional — only needed if you enable notifications)
- A Google Geocoding API key (optional — only needed for store geocoding)

## Setup

1. **Clone and install dependencies**

   ```bash
   git clone <repo-url>
   cd metziah
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Start PostgreSQL/PostGIS.** Either via Docker:

   ```bash
   docker-compose up -d db
   ```

   or a local Postgres instance with PostGIS enabled — `docker/init-db.sh` shows what the container runs on first boot.

3. **Apply the schema:**

   ```bash
   psql -d metziah -f database/migrations/001_schema.sql
   psql -d metziah -f database/migrations/002_chain_partitions.sql
   ```

4. **Configure environment variables.** Metziah uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/), with `config.py` loading `.env.{ENV}` (`ENV` defaults to `test`). Create `.env.dev` (and `.env.test` for the test environment) in the project root:

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

   `ENV` gates several safety checks throughout the pipeline (e.g. which database is written to, which feed directory is used), so it should always match whichever `.env.*` file is active.

5. **Run first-time setup.** The `Makefile` bootstraps stores, chains, and initial full snapshots in the right order:

   ```bash
   make setup        # standard (ENV=dev) first-time setup
   # or
   make setup-test    # test (ENV=test) first-time setup
   ```

   Run `make help` to see what each target does; `setup`/`setup-test` walk through downloading stores, building the store registry, resolving/normalizing chains, geocoding, seeding stores, loading full price/promo snapshots, and loading products/prices/promotions, ending with a scheduler run.

## Running the pipeline

After first-time setup, the scheduler orchestrates ongoing cycles — downloading full/incremental price and promo files and loading whatever is eligible according to `file_tracking`:

```bash
ENV=dev python -m downloaders.scheduler
```

In production this runs on a cron schedule. To send the promo notification digest manually:

```bash
ENV=dev python -m analytics.notifications.promo_notifications
```

Analytics/log-parsing runs via:

```bash
ENV=dev python -m analytics.runner
```

Modules are invoked with `python -m package.module` syntax throughout, not by file path.

## Docker

Docker runs the PostgreSQL/PostGIS database and the Metziah app in separate containers.

```bash
docker compose --env-file .env.dev up -d db
docker compose --env-file .env.dev up -d app
```


Development database:

```bash
make migrate
make migrate-test
```

To run any command inside the app container:

```bash
docker compose --env-file .env.dev exec app <command>
```

Example: 

```bash
docker compose --env-file .env.dev exec app make setup
```

To run a command using the test database:

```bash
docker compose --env-file .env.dev exec \
  -e PGDATABASE=metziah_test \
  app <command>
```

Example: 

```bash
docker compose --env-file .env.dev exec \
  -e PGDATABASE=metziah_test \
  app make setup-test
```

Database queries:
```bash
docker compose --env-file .env.dev exec db psql -U postgres -d metziah
```

```bash
docker compose --env-file .env.dev exec db psql -U postgres -d metziah_test
```


## Testing

```bash
make test
```

which runs `ENV=test pytest -v`. Tests run against a real, separately-seeded PostgreSQL test database rather than mocked connections — integration tests use real `psycopg` connections. CI (`.github/workflows/tests.yml`) spins up a `postgis/postgis` service, applies both migrations, and runs the same suite on every push/PR to `main`.

## Project layout

```
clients/          # One client per feed protocol (BinaProjects, Carrefour, LaibCatalog, MishnatYosef, PublishedPrices, Wolt, generic HTML)
downloaders/      # Download orchestration: common/full_family/delta_family + runner + scheduler
parsers/xml.py    # XML -> domain model parsing
models/           # Chain, product, promo, and store dataclasses
utils/            # load_*.py (thin CLI) / update_*.py (logic) pairs: prices, products, promos, stores, file_tracking
database/
├── migrations/   # 001_schema.sql, 002_chain_partitions.sql
├── records.py    # Domain model -> DB-shaped record mapping
└── repository.py # SQL access layer
analytics/        # Log parsing, price/promo change detection, notification mailer
monitoring/       # Source health, missing chains/stores, full-vs-delta checks
inspection/       # Ad-hoc data-quality reports
data/reference/   # chains.json, chains_extra.json, canonical name vocabulary, CBS localities
docs/decisions/   # Architecture decision records (ADRs)
docs/regulations/ # Hebrew regulatory reference material
docker/           # entrypoint.sh, init-db.sh
config.py         # pydantic-settings configuration
db.py             # Connection management
logging_config.py # Root + isolated (audit) logger setup
tests/            # Unit + integration tests, real fixture XML feeds
Makefile          # setup / setup-test / test targets
```

## Roadmap

- **Phase 1 (done):** Core pipeline — downloading, parsing, and loading price/promo data end-to-end for a single chain.
- **Phase 2 (done):** Multi-chain expansion, promotion notifications, and monitoring across the full chain/protocol set. Dockerization.
- **Phase 3 (current):** Smart cleaning and canonicalization of product names (e.g. junk/placeholder item codes, cross-chain naming variance).

## Legal basis

Feed access is based on Israel's 2014 Price Transparency regulations (Reshumot 7442), which require supermarket chains to publish machine-readable price and promotion data.

## License

Metziah is released under a custom **source-available** license (see [LICENSE](./LICENSE)), not an OSI-approved open-source license. In short: free to view, run, modify, and share for non-commercial use with attribution; commercial use requires the author's prior written consent. Read the full text before reusing any part of this project.