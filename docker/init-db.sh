#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE metziah_test;
    GRANT ALL PRIVILEGES ON DATABASE metziah_test TO $POSTGRES_USER;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "metziah" -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "metziah_test" -c "CREATE EXTENSION IF NOT EXISTS postgis;"