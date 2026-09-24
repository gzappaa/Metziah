"""
Standalone price loader.

Walks the selected feeds directory, finds the latest PriceFull file
for each chain/store, parses it, and upserts into:

    prices

Product identity, names, and metadata are handled entirely by
load_products.py / update_products.py -- this loader ignores them.

Decoupled from the live download step on purpose -- run this manually
or via its own cron entry, pointed at whatever's already on disk.

This loader is intentionally PriceFull-only, the same convention used
by load_promos.py for PromoFull: a delta "Price" file only contains
changed items, not a full store snapshot, and update_prices.py always
reconciles (deletes) items missing from what it just parsed. Loading a
delta file through this path would incorrectly delete every item the
delta didn't happen to mention. Delta Price files are handled later by
the scheduler/cron, not by this standalone backfill loader.

Thin CLI wrapper only -- actual loading logic lives in
utils/update_prices.py (load_files/load_one_file), shared with cron's
run_prices_and_load(). Runs with log_changes=False so backfill/manual
runs never write to price_changes.log -- that log stays exclusively a
record of live cron activity.

File tracking is handled by load_files(). Successfully loaded files are
marked loaded=true there; failed files remain loaded=false.

Usage:
    python utils/prices/load_prices.py
    python utils/prices/load_prices.py --dev
    python utils/prices/load_prices.py --test
    python utils/prices/load_prices.py --feeds-dir data/feeds
"""

import argparse
import logging
from pathlib import Path

from config import settings
from db import get_connection
from logging_config import setup_general_logging
from utils.file_tracking.parser_file_tracking import (
    extract_time_suffix,
    parse_filename,
)
from utils.prices.update_prices import load_files


setup_general_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]

DEFAULT_FEEDS_DIR = BASE_DIR / "data" / "feeds"
TEST_FEEDS_DIR = BASE_DIR / "data" / "test_feeds"


def find_pricefull_files(feeds_dir: Path):
    """
    Find the latest PriceFull file for each chain/sub-chain/store.

    Files are ordered by their feed date first and timestamp second, so
    only the most recent snapshot for each chain/sub-chain/store is loaded.
    """

    latest = {}

    for filepath in feeds_dir.glob("*/*/pricesfull/*"):
        try:
            info = parse_filename(filepath.name)
        except ValueError:
            logger.warning(
                "Skipping unrecognized PriceFull filename: %s",
                filepath.name,
            )
            continue

        if info["file_type"] != "PriceFull":
            continue

        chain_id = info["chain_id"]
        sub_chain_id = info["sub_chain_id"]
        store_id = info["store_id"]

        file_timestamp = (
            info["file_date"],
            extract_time_suffix(filepath.name),
        )

        key = (
            chain_id,
            sub_chain_id,
            store_id,
        )

        if (
            key not in latest
            or file_timestamp > latest[key][0]
        ):
            latest[key] = (
                file_timestamp,
                filepath,
            )

    yield from (
        (filepath, "PriceFull", True)
        for _, filepath in latest.values()
    )


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

    # ------------------------------------------------------------------
    # Environment safety
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Test feed override
    # ------------------------------------------------------------------

    if args.test:
        args.feeds_dir = TEST_FEEDS_DIR

    # Make a user-supplied relative --feeds-dir relative to the
    # repository root as well. This keeps the script independent of
    # the shell's current working directory.
    elif not args.feeds_dir.is_absolute():
        args.feeds_dir = BASE_DIR / args.feeds_dir

    args.feeds_dir = args.feeds_dir.resolve()

    logger.info(
        "Using feeds directory: %s",
        args.feeds_dir,
    )

    # ------------------------------------------------------------------
    # Discover PriceFull files
    # ------------------------------------------------------------------

    files = list(
        find_pricefull_files(
            args.feeds_dir
        )
    )

    logger.info(
        "Found %d PriceFull file(s) under %s",
        len(files),
        args.feeds_dir,
    )

    if not files:
        return

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

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