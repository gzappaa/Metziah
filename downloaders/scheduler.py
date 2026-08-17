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
from database.repository import (
    mark_files_downloaded,
    get_latest_downloaded_price_files,
    get_downloaded_promofull_files,
    get_downloaded_unloaded_promo_files,
)
from utils.update_prices import load_files as load_price_files
from utils.update_promos import load_files as load_promo_files

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


# Price files are temporary snapshots: keep only the successfully loaded
# latest Price file per store. PriceFull snapshots are historical and are
# never deleted. Cleanup happens only after loading succeeds, so a failed
# load leaves the previous Price file available as a fallback.

def cleanup_old_price_files(loaded_files):
    """
    Delete older Price snapshot files after the newest Price file
    has been successfully loaded.

    PriceFull files are never touched.
    If loading fails, this function is never called, so the old
    Price file remains available as a fallback.
    """
    for filepath in loaded_files:
        filepath = Path(filepath)

        if filepath.parent.name != "prices":
            continue

        for old_file in filepath.parent.glob("Price*.gz"):
            if old_file == filepath:
                continue

            try:
                old_file.unlink()

                logger.info(
                    "Deleted old Price file: %s",
                    old_file.name,
                )

            except Exception:
                logger.exception(
                    "Failed deleting old Price file: %s",
                    old_file.name,
                )


def run_file_tracking():
    logger.info("Updating file tracking")

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
    logger.info("Starting prices download")

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

    if downloaded_files:
        mark_downloaded(downloaded_files)

    with get_connection() as conn:
        latest_files = get_latest_downloaded_price_files(conn)

        logger.info("Latest price files selected:")
        for row in latest_files:
            logger.info(
                "SELECTED: chain=%s store=%s type=%s filename=%s",
                row[0],
                row[2],
                row[3],
                row[4],
            )

        if not latest_files:
            logger.info(
                "No downloaded Price/PriceFull files to load"
            )
            return

        filepaths = [
            FEEDS_DIR
            / str(row[0])
            / str(row[1])
            / str(row[2])
            / (
                "pricesfull"
                if row[3] == "PriceFull"
                else "prices"
            )
            / row[4]
            for row in latest_files
        ]

        logger.info(
            "Loading %d latest Price/PriceFull file(s)",
            len(filepaths),
        )

        loaded_files = load_price_files(
            conn,
            filepaths,
            FEEDS_DIR,
        )

    logger.info(
        "Successfully loaded %d price file(s)",
        len(loaded_files),
    )

    cleanup_old_price_files(loaded_files)


def run_promos_and_load():
    """
    Download PromoFull and Promo files, then process them
    in dependency order.

    PromoFull is the authoritative snapshot and must be
    successfully loaded before Promo delta files for the
    corresponding chain/store are eligible.
    """

    # ---------------------------------------------------------
    # 1. Download PromoFull.
    # ---------------------------------------------------------

    logger.info("Starting promosfull download")

    try:
        downloaded_promofull = asyncio.run(
            download_promofull(
                test=settings.ENV == "test"
            )
        )

    except Exception:
        logger.exception(
            "PromoFull download failed"
        )
        return

    if downloaded_promofull:
        mark_downloaded(downloaded_promofull)

    logger.info(
        "PromoFull download finished: %d new file(s)",
        len(downloaded_promofull),
    )

    # ---------------------------------------------------------
    # 2. Download Promo deltas.
    # ---------------------------------------------------------

    logger.info("Starting promos download")

    try:
        downloaded_promos = asyncio.run(
            download_promos(
                test=settings.ENV == "test"
            )
        )

    except Exception:
        logger.exception(
            "Promo download failed"
        )
        return

    if downloaded_promos:
        mark_downloaded(downloaded_promos)

    logger.info(
        "Promo download finished: %d new file(s)",
        len(downloaded_promos),
    )

    # ---------------------------------------------------------
    # 3. Load pending PromoFull snapshots.
    #
    # PromoFull is authoritative and may remove promotions,
    # groups, and items that disappeared from the snapshot.
    #
    # Only successfully loaded PromoFull files become the
    # baseline that allows Promo delta files to be processed.
    # ---------------------------------------------------------

    with get_connection() as conn:
        promofull_files = get_downloaded_promofull_files(conn)

        if promofull_files:
            filepaths = [
                (
                    FEEDS_DIR
                    / str(row[0])
                    / str(row[1])
                    / str(row[2])
                    / "promosfull"
                    / row[4],
                    row[3],
                )
                for row in promofull_files
            ]

            logger.info(
                "Loading %d pending PromoFull file(s)",
                len(filepaths),
            )

            loaded_promofull = load_promo_files(
                conn,
                filepaths,
                FEEDS_DIR,
            )

        else:
            loaded_promofull = []

            logger.info(
                "No pending PromoFull files to load"
            )

    # IMPORTANT:
    # This must happen BEFORE get_pending_promo_files().
    #
    # A Promo delta is only eligible after its required
    # PromoFull baseline has loaded=True.

    logger.info(
        "Successfully loaded %d PromoFull file(s)",
        len(loaded_promofull),
    )

    # ---------------------------------------------------------
    # 4. Load eligible Promo deltas.
    #
    # get_pending_promo_files() is responsible for checking
    # that the required PromoFull baseline has loaded=True.
    #
    # Promo files never perform reconciliation.
    # ---------------------------------------------------------

    with get_connection() as conn:
        promo_files = get_downloaded_unloaded_promo_files(conn)

        if not promo_files:
            logger.info(
                "No eligible Promo files to load"
            )
            return

        filepaths = [
            (
                FEEDS_DIR
                / str(row[0])
                / str(row[1])
                / str(row[2])
                / "promos"
                / row[4],
                row[3],
            )
            for row in promo_files
        ]

        logger.info(
            "Loading %d eligible Promo file(s)",
            len(filepaths),
        )

        loaded_promos = load_promo_files(
            conn,
            filepaths,
            FEEDS_DIR,
        )

    logger.info(
        "Successfully loaded %d Promo file(s)",
        len(loaded_promos),
    )


def run_pricesfull():
    logger.info("Starting pricesfull download")

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

    mark_downloaded(downloaded_files)

    logger.info(
        "PriceFull download finished: %d new file(s)",
        len(downloaded_files),
    )


def run_all():
    if settings.ENV == "test":
        logger.info(
            "TEST ENV: skipping PriceFull"
        )

        run_promos_and_load()
        run_prices_and_load()

    else:
        run_pricesfull()
        run_promos_and_load()
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
                run_promos_and_load()

        elif command == "promosfull":
            if run_file_tracking():
                # Download only; loading is handled by
                # run_promos_and_load().
                logger.info(
                    "Starting standalone promosfull download"
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

                mark_downloaded(downloaded_files)

                logger.info(
                    "PromoFull download finished: %d new file(s)",
                    len(downloaded_files),
                )

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