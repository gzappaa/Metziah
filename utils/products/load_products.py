"""
Standalone product loader.

Walks the selected feeds directory, finds the latest PriceFull file for
each chain/sub-chain/store, parses product information, resolves canonical
product names, and upserts:

    products
    store_products

Price data is intentionally ignored here.

Usage:
    python scripts/load_products.py
    python scripts/load_products.py --dev
    python scripts/load_products.py --test
    python scripts/load_products.py --feeds-dir data/feeds
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
from utils.products.update_products import load_files


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
        filepath
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
        )

    logger.info("Done.")


if __name__ == "__main__":
    main()