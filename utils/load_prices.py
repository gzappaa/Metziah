"""
Standalone loader: walks data/feeds/{chain_id}/{sub_chain_id}/{store_id}/
prices/ and pricesfull/, gzip-decompresses each *.gz price file, parses it,
and upserts into Postgres.

Decoupled from the live download step on purpose -- run this manually or
via its own cron entry, pointed at whatever's already on disk.

Thin CLI wrapper only -- actual loading logic lives in
utils/update_prices.py (load_files/load_one_file), shared with cron's
run_prices_and_load(). Runs with log_changes=False so backfill/manual
runs never write to price_changes.log -- that log stays exclusively a
record of live cron activity.

File tracking is handled by load_files(). Successfully loaded files are
marked loaded=true there; failed files remain loaded=false.

Usage:
    python scripts/load_prices.py
    python scripts/load_prices.py --dev
    python scripts/load_prices.py --test
    python scripts/load_prices.py --feeds-dir data/feeds
"""

import argparse
import logging
from pathlib import Path

from config import settings
from db import get_connection
from utils.update_prices import load_files

import re

from logging_config import setup_general_logging

setup_general_logging()
logger = logging.getLogger(__name__)

DEFAULT_FEEDS_DIR = Path("data/feeds")


def find_price_files(feeds_dir: Path):
    latest = {}

    for filepath in feeds_dir.glob("*/*/*/pricesfull/*.gz"):
        match = re.match(
            r"PriceFull(\d+)-(\d+)-(\d+)-(\d{8}-\d{6})\.gz$",
            filepath.name,
        )

        if not match:
            logger.warning(
                "Skipping unrecognized PriceFull filename: %s",
                filepath.name,
            )
            continue

        chain_id, sub_chain_id, store_id, timestamp = match.groups()

        key = (chain_id, sub_chain_id, store_id)

        if key not in latest or timestamp > latest[key][0]:
            latest[key] = (timestamp, filepath)

    yield from (filepath for _, filepath in latest.values())


def main():
    parser_args = argparse.ArgumentParser()

    parser_args.add_argument(
        "--dev",
        action="store_true",
        help="Allow loading into the development database",
    )

    parser_args.add_argument(
        "--test",
        action="store_true",
        help="Load the test database using data/test_feeds",
    )

    parser_args.add_argument(
        "--feeds-dir",
        type=Path,
        default=DEFAULT_FEEDS_DIR,
        help="Root of the feeds tree (default: data/feeds)",
    )

    args = parser_args.parse_args()

    if settings.ENV == "dev" and not args.dev:
        raise RuntimeError(
            "Development database selected. Run with --dev to confirm."
        )

    if settings.ENV != "dev" and args.dev:
        raise RuntimeError(
            "--dev was provided, but the configured environment is not dev."
        )

    if args.test and settings.ENV != "test":
        raise RuntimeError(
            "--test was provided, but the configured environment is not test."
        )

    if args.test:
        args.feeds_dir = Path("data/test_feeds")

    files = list(find_price_files(args.feeds_dir))

    logger.info(
        "Found %d price/pricefull file(s) under %s",
        len(files),
        args.feeds_dir,
    )

    if not files:
        return

    with get_connection() as conn:
        load_files(
            conn,
            files,
            args.feeds_dir,
            log_changes=False,
        )

    logger.info("Done.")


if __name__ == "__main__":
    main()