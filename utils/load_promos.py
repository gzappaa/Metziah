"""
Standalone loader for the initial PromoFull database seed.

Walks:
    data/feeds/{chain_id}/{sub_chain_id}/{store_id}/promosfull/

Gzip-decompresses each *.gz PromoFull file, parses it, and upserts it
into Postgres.

Decoupled from the live download step on purpose -- run this manually
against PromoFull files already present on disk.

Thin CLI wrapper only -- actual loading logic lives in
utils/update_promos.py (load_files/load_one_file), shared with cron's
run_promos_and_load().

Runs with log_changes=False so the initial seed/manual backfill never
writes to promo_changes.log. That log stays exclusively a record of
live cron activity.

This loader is intentionally PromoFull-only. Promo delta files are
handled later by the scheduler after a PromoFull baseline has been
successfully loaded.

Usage:
    python utils/load_promos.py
    python utils/load_promos.py --dev
    python utils/load_promos.py --test
    python utils/load_promos.py --feeds-dir data/feeds
"""

import argparse
import logging
from pathlib import Path

from config import settings
from db import get_connection
from utils.update_promos import load_files

from logging_config import setup_general_logging


setup_general_logging()
logger = logging.getLogger(__name__)

DEFAULT_FEEDS_DIR = Path("data/feeds")


def find_promo_files(feeds_dir: Path):
    """
    Yields every PromoFull file as:

        (filepath, "PromoFull")

    under:

        {chain_id}/{sub_chain_id}/{store_id}/promosfull/

    The path structure is preserved because update_promos.py uses it
    to determine the store/sub-chain context.
    """
    for filepath in feeds_dir.glob(
        "*/*/*/promosfull/*.gz"
    ):
        yield filepath, "PromoFull"


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

    files = list(
        find_promo_files(args.feeds_dir)
    )

    logger.info(
        "Found %d PromoFull file(s) under %s",
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