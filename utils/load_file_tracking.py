import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from config import settings
from chains.registry import CHAINS
from clients.laibcatalog import LaibcatalogClient
from database.repository import insert_file_tracking
from db import get_connection
from logging_config import setup_general_logging


setup_general_logging()
logger = logging.getLogger(__name__)


FEEDS_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "test_feeds"
    if settings.ENV == "test"
    else Path(__file__).resolve().parent.parent / "data" / "feeds"
)


FILENAME_PATTERN = re.compile(
    r"^(?P<file_type>PriceFull|Price|PromoFull|Promo|Stores)"
    r"(?P<chain_id>\d+)"
    r"(?:-(?P<sub_chain_id>\d+)-(?P<store_id>\d+))?"
    r"-(?P<timestamp>\d{8}-\d{6})"
    r"\.gz$"
)


def parse_filename(filename: str) -> dict:
    match = FILENAME_PATTERN.match(filename)

    if not match:
        raise ValueError(
            f"Unrecognized feed filename: {filename}"
        )

    data = match.groupdict()

    timestamp = datetime.strptime(
        data["timestamp"],
        "%Y%m%d-%H%M%S",
    )

    return {
        "chain_id": data["chain_id"],
        "sub_chain_id": data["sub_chain_id"],
        "store_id": data["store_id"],
        "file_type": data["file_type"],
        "filename": filename,
        "file_date": timestamp.date(),
    }


def get_local_path(record: dict) -> Path:
    file_type_dirs = {
        "Price": "prices",
        "PriceFull": "pricesfull",
        "Promo": "promos",
        "PromoFull": "promosfull",
    }

    if record["file_type"] == "Stores":
        raise ValueError(
            "Stores files are not supported by local feed path resolution"
        )

    return (
        FEEDS_DIR
        / record["chain_id"]
        / record["sub_chain_id"]
        / record["store_id"]
        / file_type_dirs[record["file_type"]]
        / record["filename"]
    )


async def get_file_records(chain_id: str) -> list[dict]:
    client = LaibcatalogClient(chain_id)

    files = await client.get_files()

    records = []

    for file in files:
        filename = file["fileName"]

        try:
            record = parse_filename(filename)

        except ValueError:
            logger.warning(
                "Skipping unrecognized filename: %s",
                filename,
            )
            continue

        records.append(record)

    return records


async def update_file_tracking():
    all_files = []

    for chain_key, config in CHAINS.items():

        logger.info(
            "Getting file list for %s (%s)",
            config.name,
            config.chain_id,
        )

        files = await get_file_records(
            config.chain_id
        )

        logger.info(
            "Found %d file(s)",
            len(files),
        )

        for record in files:
            record["downloaded"] = get_local_path(record).exists()

        all_files.extend(files)

    if not all_files:
        logger.info("No files found")
        return 0

    with get_connection() as conn:

        inserted = insert_file_tracking(
            conn,
            all_files,
        )

        conn.commit()

    logger.info(
        "Inserted %d new file(s) out of %d discovered",
        inserted,
        len(all_files),
    )

    return inserted


async def main():
    await update_file_tracking()


if __name__ == "__main__":
    asyncio.run(main())