#!/bin/bash
set -e

# Create test database
psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE metziah_test;
    GRANT ALL PRIVILEGES ON DATABASE metziah_test TO $POSTGRES_USER;
EOSQL

# Enable PostGIS in production and test databases
psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -c "CREATE EXTENSION IF NOT EXISTS postgis;"

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "metziah_test" \
    -c "CREATE EXTENSION IF NOT EXISTS postgis;"