.PHONY: help test setup setup-test setup-prod enrich-prod enrich-prod-images \
	enrich-prod-bonus \
	docker-up docker-down docker-logs docker-reset \
	migrate migrate-test

help:
	@echo "Metziah commands:"
	@echo ""
	@echo "Testing:"
	@echo "  make test                Run pytest"
	@echo ""
	@echo "Setup:"
	@echo "  make setup               First-time standard setup"
	@echo "  make setup-test          First-time test setup"
	@echo "  make setup-prod          First-time production setup"
	@echo ""
	@echo "Product enrichment:"
	@echo "  make enrich-prod         Run production product enrichment pipeline"
	@echo "  make enrich-prod-bonus   Run optional browser/product-page scrapers and reload enrichment"
	@echo "  make enrich-prod-images  Download product images (slow)"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up           Start PostgreSQL"
	@echo "  make docker-down         Stop Docker services"
	@echo "  make docker-logs         Follow PostgreSQL logs"
	@echo "  make docker-reset        Recreate PostgreSQL database"
	@echo ""
	@echo "Database:"
	@echo "  make migrate             Apply all migrations to development database"
	@echo "  make migrate-test        Apply all migrations to test database"


# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test:
	ENV=test pytest -v


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

docker-up:
	docker compose --env-file .env.dev up -d db
	@echo "=== Postgres is up ==="


docker-down:
	docker compose --env-file .env.dev down


docker-logs:
	docker compose --env-file .env.dev logs -f db


docker-reset:
	docker compose --env-file .env.dev down -v
	$(MAKE) docker-up


# ---------------------------------------------------------------------------
# Database migrations
# ---------------------------------------------------------------------------

# Every .sql file in database/migrations/, applied in filename order.
MIGRATIONS := $(sort $(wildcard database/migrations/*.sql))
DOCKER_APP = docker compose --env-file .env.prod exec -T app

migrate: DB = $$PGDATABASE
migrate-test: DB = metziah_test

migrate migrate-test:
	@echo "=== Migrating $(DB) ==="
	@for f in $(MIGRATIONS); do \
		echo "--- $$f"; \
		docker compose --env-file .env.prod exec -T db \
			psql -U "$$PGUSER" -d "$(DB)" -v ON_ERROR_STOP=1 \
			< "$$f" || exit 1; \
	done
	@echo "=== $(DB) migrated ==="


# ---------------------------------------------------------------------------
# First-time setup
# ---------------------------------------------------------------------------

setup:
	@echo "=== Standard setup: ENV=dev ==="

	@echo "=== 1. Download Stores ==="
	ENV=dev python -m downloaders.stores

	@echo "=== 2. Build initial store JSON ==="
	ENV=dev python -m utils.stores.get_stores

	@echo "=== 3. Load file-tracking history ==="
	ENV=dev python -m utils.file_tracking.load_file_tracking --report

	@echo "=== 4. Resolve hidden/ambiguous chains ==="
	ENV=dev python -m monitoring.chains_missing

	@echo "=== 5. Normalize chain IDs ==="
	ENV=dev python -m utils.stores.chains_id_normalizer

	@echo "=== 6. Normalize city metadata ==="
	ENV=dev python -m utils.stores.data_enrichment.normalize_store_cities

	@echo "=== 7. Clean City Market addresses ==="
	ENV=dev python -m utils.stores.data_enrichment.citymarket_addresses

	@echo "=== 8. Geocode stores ==="
	ENV=dev python -m utils.stores.data_enrichment.geocode_google

	@echo "=== 9. Seed normal stores ==="
	ENV=dev python -m utils.stores.seed_stores

	@echo "=== 10. Find stores missing from Stores.xml ==="
	ENV=dev python -m monitoring.stores_missing

	@echo "=== 11. Add unregistered stores ==="
	ENV=dev python -m utils.stores.add_unregistered_stores

	@echo "=== 12. Load file tracking ==="
	ENV=dev python -m utils.file_tracking.load_file_tracking

	@echo "=== 13. Load PriceFull snapshots ==="
	ENV=dev python -m downloaders.pricesfull

	@echo "=== 14. Load PromoFull snapshots ==="
	ENV=dev python -m utils.file_tracking.cache
	ENV=dev python -m downloaders.promosfull

	@echo "=== 15. Load/resolve products ==="
	ENV=dev python -m utils.products.load_products --dev

	@echo "=== 16. Load prices ==="
	ENV=dev python -m utils.prices.load_prices --dev

	@echo "=== 17. Load promotions ==="
	ENV=dev python -m utils.promos.load_promos --dev

	@echo "=== 18. Run scheduler ==="
	ENV=dev python -m downloaders.scheduler

	@echo "=== Standard setup complete ==="


setup-test:
	@echo "=== Test setup: ENV=test ==="

	@echo "=== 1. Load file-tracking history ==="
	ENV=test python -m utils.file_tracking.load_file_tracking --report

	@echo "=== 2. Download PriceFull test files ==="
	ENV=test python -m downloaders.pricesfull --test

	@echo "=== 3. Download Stores files ==="
	ENV=test python -m utils.file_tracking.cache
	ENV=test python -m downloaders.stores

	@echo "=== 4. Build initial store JSON ==="
	ENV=test python -m utils.stores.get_stores

	@echo "=== 5. Resolve hidden/ambiguous chains ==="
	ENV=test python -m monitoring.chains_missing

	@echo "=== 6. Normalize chain IDs ==="
	ENV=test python -m utils.stores.chains_id_normalizer

	@echo "=== 7. Normalize city metadata ==="
	ENV=test python -m utils.stores.data_enrichment.normalize_store_cities

	@echo "=== 8. Clean City Market addresses ==="
	ENV=test python -m utils.stores.data_enrichment.citymarket_addresses

	@echo "=== 9. Seed normal stores ==="
	ENV=test python -m utils.stores.seed_stores --test

	@echo "=== 10. Find stores missing from Stores.xml ==="
	ENV=test python -m monitoring.stores_missing

	@echo "=== 11. Add unregistered stores ==="
	ENV=test python -m utils.stores.add_unregistered_stores

	@echo "=== 12. Load file tracking ==="
	ENV=test python -m utils.file_tracking.load_file_tracking

	@echo "=== 13. Download PromoFull test snapshots ==="
	ENV=test python -m utils.file_tracking.cache
	ENV=test python -m downloaders.promosfull --test

	@echo "=== 14. Load/resolve products ==="
	ENV=test python -m utils.products.load_products --test

	@echo "=== 15. Load prices ==="
	ENV=test python -m utils.prices.load_prices --test

	@echo "=== 16. Load promotions ==="
	ENV=test python -m utils.promos.load_promos --test

	@echo "=== 17. Run scheduler ==="
	ENV=test python -m downloaders.scheduler --test

	@echo "=== Test setup complete ==="


# ---------------------------------------------------------------------------
# Production setup
# ---------------------------------------------------------------------------

setup-prod:
	@echo "=== Production setup: ENV=prod ==="

	@echo "=== 1. Download Stores ==="
	ENV=prod python -m downloaders.stores

	@echo "=== 2. Build initial store JSON ==="
	ENV=prod python -m utils.stores.get_stores

	@echo "=== 3. Load file-tracking history ==="
	ENV=prod python -m utils.file_tracking.load_file_tracking --report

	@echo "=== 4. Resolve hidden/ambiguous chains ==="
	ENV=prod python -m monitoring.chains_missing

	@echo "=== 5. Normalize chain IDs ==="
	ENV=prod python -m utils.stores.chains_id_normalizer

	@echo "=== 6. Normalize city metadata ==="
	ENV=prod python -m utils.stores.data_enrichment.normalize_store_cities

	@echo "=== 7. Clean City Market addresses ==="
	ENV=prod python -m utils.stores.data_enrichment.citymarket_addresses

	# @echo "=== 8. Geocode stores ==="
	# ENV=prod python -m utils.stores.data_enrichment.geocode_google

	@echo "=== 9. Seed normal stores ==="
	ENV=prod python -m utils.stores.seed_stores

	@echo "=== 10. Find stores missing from Stores.xml ==="
	ENV=prod python -m monitoring.stores_missing

	@echo "=== 11. Add unregistered stores ==="
	ENV=prod python -m utils.stores.add_unregistered_stores

	@echo "=== 12. Load file tracking ==="
	ENV=prod python -m utils.file_tracking.load_file_tracking

	@echo "=== 13. Load PriceFull snapshots ==="
	ENV=prod python -m downloaders.pricesfull

	@echo "=== 14. Load PromoFull snapshots ==="
	ENV=prod python -m utils.file_tracking.cache
	ENV=prod python -m downloaders.promosfull

	@echo "=== 15. Load/resolve products ==="
	ENV=prod python -m utils.products.load_products --prod

	@echo "=== 16. Load prices ==="
	ENV=prod python -m utils.prices.load_prices --prod

	@echo "=== 17. Load promotions ==="
	ENV=prod python -m utils.promos.load_promos --prod

	@echo "=== 18. Run scheduler ==="
	ENV=prod python -m downloaders.scheduler

	@echo "=== Production setup complete ==="


# ---------------------------------------------------------------------------
# Production product enrichment
# ---------------------------------------------------------------------------

# Select the retailer with the largest parsed product JSONL file.
# Supports products_parsed.jsonl and products_parsed_*.jsonl.
PRODUCTS_SOURCE := $(shell find data/parsed -mindepth 2 -maxdepth 2 \
	-type f -name 'products_parsed*.jsonl' -printf '%s\t%h\n' \
	| sort -nr | head -1 | cut -f2- | sed 's|.*/||')

enrich-prod:
	@echo "=== 1. Detect pharmacy stores ==="
	ENV=prod python -m monitoring.detect_pharmacy_stores

	@echo "=== 2. Check scraper coverage ==="
	ENV=prod python -m monitoring.scraper_coverage

	@echo "=== 3. Run generic scraper ==="
	ENV=prod python -m scrapers.generic

	@echo "=== 4. Generate product JSONL ==="
	ENV=prod python -m utils.processing.generate_product_jsonl

	@echo "=== 5. Apply product enrichment migration ==="
	docker compose --env-file .env.prod exec -T db \
		psql -U "$$PGUSER" -d metziah_prod \
		< database/migrations/004_product_enrichment.sql

	@echo "=== 6. Apply store-product categories migration ==="
	docker compose --env-file .env.prod exec -T db \
		psql -U "$$PGUSER" -d metziah_prod \
		< database/migrations/005_store_product_categories.sql

	@echo "=== 7. Load enriched products (source: $(PRODUCTS_SOURCE)) ==="
	@if [ -z "$(PRODUCTS_SOURCE)" ]; then \
		echo "ERROR: No products_parsed.jsonl found under data/parsed"; \
		exit 1; \
	fi
	ENV=prod python -m utils.products.load_products_enriched \
		--source "$(PRODUCTS_SOURCE)"

	@echo "=== 8. Load store-product categories ==="
	ENV=prod python -m utils.products.load_store_products_categories

	@echo "=== Refresh store-product category matches ==="
	ENV=prod python -c "import db; conn = db.get_connection(); conn.execute('REFRESH MATERIALIZED VIEW store_product_category_matches'); conn.commit(); conn.close()"

	@echo "=== 9. Load product nutrition ==="
	ENV=prod python -m utils.products.load_products_nutrition

	@echo "=== Production product enrichment complete ==="


# Optional: run the additional browser-based scrapers and reload enrichment.
enrich-prod-bonus:
	@echo "=== 1. Run browser scraper ==="
	ENV=prod python -m scrapers.browser

	@echo "=== IMPORTANT: Create scrapers/product_pages/product_urls.txt before continuing ==="
	@read -p "Press Enter once product_urls.txt is ready..."

	@echo "=== 2. Run product-pages scraper ==="
	ENV=prod python -m scrapers.product_pages.scraper --headless

	@echo "=== 3. Regenerate product JSONL ==="
	ENV=prod python -m utils.processing.generate_product_jsonl

	@echo "=== 4. Reload enriched products ==="
	@if [ -z "$(PRODUCTS_SOURCE)" ]; then \
		echo "ERROR: No products_parsed.jsonl found under data/parsed"; \
		exit 1; \
	fi
	ENV=prod python -m utils.products.load_products_enriched \
		--source "$(PRODUCTS_SOURCE)"

	@echo "=== 5. Load product nutrition ==="
	ENV=prod python -m utils.products.load_products_nutrition

	@echo "=== Bonus product enrichment complete ==="


# Run only when intentionally downloading product images.
enrich-prod-images:
	ENV=prod python -m utils.processing.download_img