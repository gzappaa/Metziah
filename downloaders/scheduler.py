# scheduler.py

import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

sys.path.insert(0, str(PROJECT_DIR))

from config import settings
from logging_config import setup_logging
from db import get_connection
from database.repository import mark_files_downloaded
from utils.update_prices import load_files

from downloaders.prices import download_prices
from downloaders.pricesfull import download_pricefull
from downloaders.promos import download_promos
from downloaders.promosfull import download_promofull
from utils.load_file_tracking import update_file_tracking


FEEDS_DIR = (
    PROJECT_DIR / "data" / "test_feeds"
    if settings.ENV == "test"
    else PROJECT_DIR / "data" / "feeds"
)

logger = setup_logging("scheduler")


def mark_downloaded(downloaded_files):

    if not downloaded_files:
        return

    filenames = [
        path.name
        for path in downloaded_files
    ]

    with get_connection() as conn:

        updated = mark_files_downloaded(
            conn,
            filenames,
        )

        conn.commit()

    logger.info(
        "Marked %d file(s) as downloaded",
        updated,
    )


def run_file_tracking():

    logger.info(
        "Updating file tracking"
    )

    try:

        inserted = asyncio.run(
            update_file_tracking()
        )

    except Exception:

        logger.exception(
            "File tracking update failed"
        )

        return False

    logger.info(
        "File tracking updated: %d new file(s)",
        inserted,
    )

    return True


def run_prices_and_load():

    logger.info(
        "Starting prices download"
    )

    try:

        downloaded_files = asyncio.run(
            download_prices(
                test=settings.ENV == "test"
            )
        )

    except Exception:

        logger.exception(
            "Prices download failed"
        )

        return

    if not downloaded_files:

        logger.info(
            "No new price files downloaded"
        )

        return

    mark_downloaded(
        downloaded_files
    )

    logger.info(
        "Loading %d downloaded price file(s) into DB",
        len(downloaded_files),
    )

    with get_connection() as conn:

        loaded_files = load_files(
            conn,
            downloaded_files,
            FEEDS_DIR,
        )

    logger.info(
        "Successfully loaded %d price file(s)",
        len(loaded_files),
    )


def run_promos():

    logger.info(
        "Starting promos download"
    )

    try:

        downloaded_files = asyncio.run(
            download_promos(
                test=settings.ENV == "test"
            )
        )

    except Exception:

        logger.exception(
            "Promo download failed"
        )

        return

    mark_downloaded(
        downloaded_files
    )

    logger.info(
        "Promo download finished: %d new file(s)",
        len(downloaded_files),
    )


def run_pricesfull():

    logger.info(
        "Starting pricesfull download"
    )

    try:

        downloaded_files = asyncio.run(
            download_pricefull(
                test=settings.ENV == "test"
            )
        )

    except Exception:

        logger.exception(
            "PriceFull download failed"
        )

        return

    mark_downloaded(
        downloaded_files
    )

    logger.info(
        "PriceFull download finished: %d new file(s)",
        len(downloaded_files),
    )


def run_promosfull():

    logger.info(
        "Starting promosfull download"
    )

    try:

        downloaded_files = asyncio.run(
            download_promofull(
                test=settings.ENV == "test"
            )
        )

    except Exception:

        logger.exception(
            "PromoFull download failed"
        )

        return

    mark_downloaded(
        downloaded_files
    )

    logger.info(
        "PromoFull download finished: %d new file(s)",
        len(downloaded_files),
    )


def run_all():

    if settings.ENV == "test":

        logger.info(
            "TEST ENV: skipping PriceFull"
        )

        run_promosfull()
        run_promos()
        run_prices_and_load()

    else:

        run_pricesfull()
        run_promosfull()
        run_promos()
        run_prices_and_load()


def main():

    logger.info(
        "Scheduler started | ENV=%s | FEEDS_DIR=%s",
        settings.ENV,
        FEEDS_DIR,
    )

    if len(sys.argv) > 1:

        command = sys.argv[1]

        if command == "prices":

            if run_file_tracking():
                run_prices_and_load()

        elif command == "pricesfull":

            if run_file_tracking():
                run_pricesfull()

        elif command == "promos":

            if run_file_tracking():
                run_promos()

        elif command == "promosfull":

            if run_file_tracking():
                run_promosfull()

        elif command == "all":

            if run_file_tracking():
                run_all()

        else:

            logger.error(
                "Unknown command: %s",
                command,
            )

        return

    # Normal scheduler execution.
    if run_file_tracking():
        run_all()


if __name__ == "__main__":
    main()