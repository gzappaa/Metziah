import argparse
import asyncio
import re
import shutil
from datetime import datetime
from pathlib import Path

from logging_config import setup_logging
from clients.laibcatalog import LaibcatalogClient
from chains.registry import CHAINS


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "feeds"
TEST_DATA_DIR = BASE_DIR / "data" / "test_feeds"

CHAIN = CHAINS["machsenei_hashuk"]
CHAIN_ID = CHAIN.chain_id

logger = setup_logging("pricesfull")


FILENAME_PATTERN = re.compile(
    r"PriceFull"
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
        / "pricesfull"
    )


async def download_pricefull(test=False) -> list[Path]:

    data_dir = TEST_DATA_DIR if test else DATA_DIR

    client = LaibcatalogClient(CHAIN_ID)

    logger.info("Getting files from API...")

    try:
        files = await client.get_files()

    except Exception:
        logger.exception(
            "Failed getting file list from Laibcatalog"
        )
        return []

    pricefull_files = [
        f["fileName"]
        for f in files
        if f["fileName"].startswith("PriceFull")
    ]

    logger.info(
        "Found %d PriceFull files",
        len(pricefull_files),
    )

    latest_files = {}

    # Find newest PriceFull file per store + day.
    for filename in pricefull_files:

        meta = parse_filename(filename)

        if not meta:
            logger.warning(
                "Skipping invalid filename: %s",
                filename,
            )
            continue

        key = (
            meta["chain"],
            meta["subchain"],
            meta["store"],
            meta["date"],
        )

        file_datetime = datetime.strptime(
            meta["date"] + meta["time"],
            "%Y%m%d%H%M%S",
        )

        if (
            key not in latest_files
            or file_datetime > latest_files[key][0]
        ):
            latest_files[key] = (
                file_datetime,
                filename,
                meta,
            )

    if test:
        latest_files = dict(
            list(latest_files.items())[:5]
        )

        logger.info(
            "TEST MODE: keeping first 5 stores"
        )

        if TEST_DATA_DIR.exists():
            logger.warning(
                "TEST MODE: deleting existing %s",
                TEST_DATA_DIR,
            )
            shutil.rmtree(TEST_DATA_DIR)

    logger.info(
        "Keeping %d latest PriceFull files",
        len(latest_files),
    )

    downloaded = 0
    skipped = 0
    failed = 0
    downloaded_files = []

    for _, filename, meta in latest_files.values():

        folder = get_storage_path(
            meta,
            data_dir,
        )

        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = folder / filename

        if destination.exists():

            logger.info(
                "UP TO DATE: %s",
                filename,
            )

            skipped += 1
            continue

        logger.info(
            "DOWNLOAD: %s",
            filename,
        )

        try:

            url = client.build_download_url(filename)

            content = await client.download_file(url)

            destination.write_bytes(content)

            downloaded += 1
            downloaded_files.append(destination)

        except Exception:

            logger.exception(
                "FAILED downloading %s",
                filename,
            )

            failed += 1
            continue

        # Normal mode: preserve existing behavior.
        # Clean older same-day PriceFull files.
        if not test:

            for old_file in folder.glob("PriceFull*.gz"):

                if old_file.name == filename:
                    continue

                old_meta = parse_filename(old_file.name)

                if (
                    old_meta
                    and old_meta["date"] == meta["date"]
                ):

                    logger.info(
                        "REMOVE OLD SAME DAY: %s",
                        old_file.name,
                    )

                    old_file.unlink()

    logger.info("Finished")

    logger.info(
        "Downloaded: %d",
        downloaded,
    )

    logger.info(
        "Skipped: %d",
        skipped,
    )

    logger.info(
        "Failed: %d",
        failed,
    )

    return downloaded_files


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Delete test_feeds and download first 5 PriceFull stores",
    )

    args = parser.parse_args()

    try:

        asyncio.run(
            download_pricefull(
                test=args.test
            )
        )

    except Exception:

        logger.exception(
            "PriceFull downloader crashed"
        )

        raise