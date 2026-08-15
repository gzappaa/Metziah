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

from logging_config import setup_general_logging

setup_general_logging()
logger = logging.getLogger(__name__)

DEFAULT_FEEDS_DIR = Path("data/feeds")


def find_price_files(feeds_dir: Path):
    """
    Yields every *.gz Price and PriceFull file under:

        data/feeds/{chain}/{subchain}/{store}/prices/
        data/feeds/{chain}/{subchain}/{store}/pricesfull/

    Doesn't assume anything about filenames -- chain/subchain/store come
    from parsing the XML content itself, not the filename.
    """
    yield from feeds_dir.glob("*/*/*/prices/*.gz")
    yield from feeds_dir.glob("*/*/*/pricesfull/*.gz")


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