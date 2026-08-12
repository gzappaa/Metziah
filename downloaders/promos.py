# promos.py

import argparse
import asyncio
import re
from pathlib import Path

from chains.registry import CHAINS
from clients.laibcatalog import LaibcatalogClient
from logging_config import setup_logging


# Use --test to download the first 5 stores into data/test_feeds.
#
# Unlike Price files, Promo files are intentionally NOT overwritten
# or deleted. Every Promo file released by the API is kept so we can
# observe the feed's behavior over an entire day.

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "feeds"
TEST_DATA_DIR = BASE_DIR / "data" / "test_feeds"

CHAIN = CHAINS["machsenei_hashuk"]
CHAIN_ID = CHAIN.chain_id

logger = setup_logging("promos")


FILENAME_PATTERN = re.compile(
    r"Promo"
    r"(?P<chain>\d+)-"
    r"(?P<subchain>\d+)-"
    r"(?P<store>\d+)-"
    r"(?P<date>\d{8})-"
    r"(?P<time>\d{6})\.gz"
)


def parse_filename(filename):
    match = FILENAME_PATTERN.fullmatch(filename)

    if not match:
        return None

    return match.groupdict()


def get_storage_path(meta, data_dir):
    return (
        data_dir
        / meta["chain"]
        / meta["subchain"]
        / meta["store"]
        / "promos"
    )


async def download_promos(test=False):
    data_dir = TEST_DATA_DIR if test else DATA_DIR

    client = LaibcatalogClient(CHAIN_ID)

    logger.info("Getting files from API...")

    try:
        files = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list from Laibcatalog")
        return

    promo_files = [
        f["fileName"]
        for f in files
        if (
            f["fileName"].startswith("Promo")
            and not f["fileName"].startswith("PromoFull")
        )
    ]

    logger.info("Found %d Promo files", len(promo_files))

    if test:
        # Keep the first 5 stores, but download ALL Promo files
        # belonging to those stores.
        selected_stores = []

        for filename in promo_files:
            meta = parse_filename(filename)

            if not meta:
                continue

            store_key = (
                meta["chain"],
                meta["subchain"],
                meta["store"],
            )

            if store_key not in selected_stores:
                selected_stores.append(store_key)

            if len(selected_stores) >= 5:
                break

        promo_files = [
            filename
            for filename in promo_files
            if (
                (meta := parse_filename(filename))
                and (
                    meta["chain"],
                    meta["subchain"],
                    meta["store"],
                ) in selected_stores
            )
        ]

        logger.info(
            "TEST MODE: keeping all Promo files for first 5 stores"
        )

    downloaded = 0
    skipped = 0
    failed = 0

    for filename in promo_files:
        meta = parse_filename(filename)

        if not meta:
            logger.warning("Skipping invalid filename: %s", filename)
            continue

        folder = get_storage_path(meta, data_dir)
        folder.mkdir(parents=True, exist_ok=True)

        destination = folder / filename

        if destination.exists():
            logger.debug("ALREADY EXISTS: %s", filename)
            skipped += 1
            continue

        logger.info("DOWNLOAD: %s", filename)

        try:
            url = client.build_download_url(filename)
            content = await client.download_file(url)

            destination.write_bytes(content)
            downloaded += 1

        except Exception:
            logger.exception(
                "FAILED downloading %s",
                filename,
            )
            failed += 1
            continue

    logger.info(
        "Finished: downloaded=%d skipped=%d failed=%d",
        downloaded,
        skipped,
        failed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Download all Promo files for the first 5 stores into data/test_feeds",
    )

    args = parser.parse_args()

    if args.test and TEST_DATA_DIR.exists():
        logger.warning(
            "TEST MODE: deleting existing %s",
            TEST_DATA_DIR,
        )

        import shutil

        shutil.rmtree(TEST_DATA_DIR)

    try:
        asyncio.run(download_promos(test=args.test))

    except Exception:
        logger.exception("Promos downloader crashed")
        raise