.PHONY: help test setup setup-test \
	docker-up docker-down docker-logs docker-reset \
	migrate migrate-test


help:
	@echo "Metziah commands:"
	@echo ""
	@echo "Testing:"
	@echo "  make test          Run pytest"
	@echo ""
	@echo "Setup:"
	@echo "  make setup         First-time standard setup"
	@echo "  make setup-test    First-time test setup"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up     Start PostgreSQL"
	@echo "  make docker-down   Stop Docker services"
	@echo "  make docker-logs   Follow PostgreSQL logs"
	@echo "  make docker-reset  Recreate PostgreSQL database"
	@echo ""
	@echo "Database:"
	@echo "  make migrate       Apply migrations to development database"
	@echo "  make migrate-test  Apply migrations to test database"


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

migrate:
	@echo "=== Migrating development database ==="
	docker compose --env-file .env.dev exec -T db \
		psql -U "$$PGUSER" -d "$$PGDATABASE" \
		< database/migrations/001_schema.sql
	docker compose --env-file .env.dev exec -T db \
		psql -U "$$PGUSER" -d "$$PGDATABASE" \
		< database/migrations/002_chain_partitions.sql
	@echo "=== Development database migrated ==="

migrate-test:
	@echo "=== Migrating test database ==="
	docker compose --env-file .env.dev exec -T db \
		psql -U "$$PGUSER" -d metziah_test \
		< database/migrations/001_schema.sql
	docker compose --env-file .env.dev exec -T db \
		psql -U "$$PGUSER" -d metziah_test \
		< database/migrations/002_chain_partitions.sql
	@echo "=== Test database migrated ==="


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