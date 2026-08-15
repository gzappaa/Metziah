import asyncio
import re
from logging_config import setup_logging
from pathlib import Path
from datetime import datetime
from chains.registry import CHAINS
from clients.laibcatalog import LaibcatalogClient
import argparse

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "feeds"

CHAIN = CHAINS["machsenei_hashuk"]
CHAIN_ID = CHAIN.chain_id


logger = setup_logging("promosfull")


FILENAME_PATTERN = re.compile(
    r"PromoFull"
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



def get_storage_path(meta):

    return (
        DATA_DIR
        / meta["chain"]
        / meta["subchain"]
        / meta["store"]
        / "promosfull"
    )



async def download_promofull(test=False) -> list[Path]:

    data_dir = (
        BASE_DIR / "data" / "test_feeds"
        if test
        else DATA_DIR
    )

    client = LaibcatalogClient(CHAIN_ID)

    logger.info("Getting files from API...")

    try:
        files = await client.get_files()

    except Exception:
        logger.exception(
            "Failed getting file list from Laibcatalog"
        )
        return []

    promofull_files = [
        f["fileName"]
        for f in files
        if f["fileName"].startswith("PromoFull")
    ]

    logger.info(
        "Found %d PromoFull files",
        len(promofull_files)
    )

    if test:
        # Use exactly the stores already present in test_feeds.
        test_feeds_dir = BASE_DIR / "data" / "test_feeds"

        test_stores = {
            path.name
            for path in test_feeds_dir.glob("*/*/*")
            if path.is_dir()
        }

        promofull_files = [
            filename
            for filename in promofull_files
            if (
                (meta := parse_filename(filename))
                and meta["store"] in test_stores
            )
        ]

        logger.info(
            "TEST MODE: keeping PromoFull files for %d existing test store(s)",
            len(test_stores),
        )

    latest_files = {}

    # Find newest file per store + day
    for filename in promofull_files:

        meta = parse_filename(filename)

        if not meta:
            logger.warning(
                "Skipping invalid filename: %s",
                filename
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
            "%Y%m%d%H%M%S"
        )

        if (
            key not in latest_files
            or file_datetime > latest_files[key][0]
        ):
            latest_files[key] = (
                file_datetime,
                filename,
                meta
            )

    logger.info(
        "Keeping %d latest PromoFull files",
        len(latest_files)
    )

    downloaded = 0
    skipped = 0
    failed = 0
    downloaded_files = []

    for _, filename, meta in latest_files.values():

        folder = (
            data_dir
            / meta["chain"]
            / meta["subchain"]
            / meta["store"]
            / "promosfull"
        )

        folder.mkdir(
            parents=True,
            exist_ok=True
        )

        destination = folder / filename

        if destination.exists():

            logger.info(
                "UP TO DATE: %s",
                filename
            )

            skipped += 1
            continue

        logger.info(
            "DOWNLOAD: %s",
            filename
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
                filename
            )

            failed += 1
            continue

        for old_file in folder.glob("PromoFull*.gz"):

            if old_file.name == filename:
                continue

            old_meta = parse_filename(old_file.name)

            if (
                old_meta
                and old_meta["date"] == meta["date"]
            ):

                logger.info(
                    "REMOVE OLD SAME DAY: %s",
                    old_file.name
                )

                old_file.unlink()

    logger.info("Finished")

    logger.info("Downloaded: %d", downloaded)
    logger.info("Skipped: %d", skipped)
    logger.info("Failed: %d", failed)

    return downloaded_files



if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Download PromoFull files for stores already present in data/test_feeds",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            download_promofull(test=args.test)
        )

    except Exception:

        logger.exception(
            "PromoFull downloader crashed"
        )

        raise