import asyncio
import logging
import re

from pathlib import Path
from datetime import datetime

from clients.laibcatalog import LaibcatalogClient
from chains.registry import CHAINS

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "feeds"

CHAIN = CHAINS["machsenei_hashuk"]
CHAIN_ID = CHAIN.chain_id


LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_DIR / "prices.log"
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


FILENAME_PATTERN = re.compile(
    r"Price"
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
        / "prices"
    )



async def download_prices():

    client = LaibcatalogClient(CHAIN_ID)

    logger.info("Getting files from API...")


    try:

        files = await client.get_files()


    except Exception:

        logger.exception(
            "Failed getting file list from Laibcatalog"
        )

        return



    price_files = [
        f["fileName"]
        for f in files
        if (
            f["fileName"].startswith("Price")
            and not f["fileName"].startswith("PriceFull")
        )
    ]


    logger.info(
        "Found %d Price files",
        len(price_files)
    )



    # newest Price per store
    latest_files = {}


    for filename in price_files:

        meta = parse_filename(filename)


        if not meta:

            logger.warning(
                "Skipping invalid filename: %s",
                filename
            )

            continue



        store_key = (
            meta["chain"],
            meta["subchain"],
            meta["store"],
        )


        try:

            file_datetime = datetime.strptime(
                meta["date"] + meta["time"],
                "%Y%m%d%H%M%S"
            )

        except ValueError:

            logger.warning(
                "Invalid datetime: %s",
                filename
            )

            continue



        if (
            store_key not in latest_files
            or file_datetime > latest_files[store_key][0]
        ):

            latest_files[store_key] = (
                file_datetime,
                filename,
                meta
            )



    logger.info(
        "Keeping %d newest Price files",
        len(latest_files)
    )



    downloaded = 0
    skipped = 0
    failed = 0



    for _, filename, meta in latest_files.values():

        folder = get_storage_path(meta)

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


        else:

            logger.info(
                "DOWNLOAD: %s",
                filename
            )


            try:

                url = client.build_download_url(
                    filename
                )


                content = await client.download_file(
                    url
                )


                destination.write_bytes(
                    content
                )


                downloaded += 1


            except Exception:

                logger.exception(
                    "FAILED downloading %s",
                    filename
                )

                failed += 1

                continue



        # Always remove old snapshots
        for old_file in folder.glob(
            "Price*.gz"
        ):

            if old_file.name != filename:

                try:

                    logger.info(
                        "REMOVE OLD: %s",
                        old_file.name
                    )

                    old_file.unlink()


                except Exception:

                    logger.exception(
                        "FAILED removing %s",
                        old_file.name
                    )



    logger.info("Finished")

    logger.info(
        "Downloaded: %d",
        downloaded
    )

    logger.info(
        "Skipped: %d",
        skipped
    )

    logger.info(
        "Failed: %d",
        failed
    )



if __name__ == "__main__":

    try:

        asyncio.run(
            download_prices()
        )


    except Exception:

        logger.exception(
            "Prices downloader crashed"
        )

        raise