# scheduler.py

import asyncio
import json
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
    get_downloaded_promofull_files,
    get_downloaded_unloaded_promo_files,
    get_downloaded_pricefull_files,
    get_downloaded_unloaded_price_files,
)
from utils.prices.update_prices import load_files as load_price_files
from utils.promos.update_promos import load_files as load_promo_files

from downloaders.prices import download_prices
from downloaders.pricesfull import download_pricefull
from downloaders.promos import download_promos
from downloaders.promosfull import download_promofull
from utils.file_tracking.load_file_tracking import update_file_tracking
from downloaders.common import normalize_store_id
from utils.products.update_products import discover_new_products
from utils.file_tracking.cache import refresh_html_caches
from utils.file_tracking.data_enrichment.populate_file_sizes import main as populate_file_sizes

FEEDS_DIR = (
    PROJECT_DIR / "data" / "test_feeds"
    if settings.ENV == "test"
    else PROJECT_DIR / "data" / "feeds"
)

CHAINS_FILE = PROJECT_DIR / "data" / "reference" / "chains.json"
CHAINS_EXTRA_FILE = PROJECT_DIR / "data" / "reference" / "chains_extra.json"
IGNORED_STORES_FILE = PROJECT_DIR / "data" / "reference" / "ignored_stores.json"

logger = setup_logging("scheduler")


# ---------------------------------------------------------------------------
# Price snapshot/skip rules
#
# Two independent, evidence-driven exceptions to "Price is a delta":
#
#   1. Every chain published via LaibcatalogClient is known to publish
#      Price as a full snapshot, not a delta -- so it must reconcile
#      removed items the same way PriceFull does.
#
#   2. A handful of specific stores in a few chains have Price files
#      whose delta/snapshot behavior is not yet confirmed. Rather than
#      risk silently wrong reconciliation, they're skipped entirely
#      (loaded=false stays forever, same as any other failed file)
#      until someone confirms how they behave. This list lives in
#      data/reference/ignored_stores.json:
#
#          [{"chain": "<chain_id>", "stores": ["<store_id>", ...]}, ...]
# ---------------------------------------------------------------------------

def _load_chain_metadata() -> dict:
    """
    Same convention as update_prices._load_chain_metadata(): kept as a
    separate copy so scheduler.py has no import-time dependency on it.
    chains_extra.json entries take precedence over chains.json.
    """
    with CHAINS_FILE.open("r", encoding="utf-8") as f:
        chains = json.load(f)

    if CHAINS_EXTRA_FILE.exists():
        with CHAINS_EXTRA_FILE.open("r", encoding="utf-8") as f:
            chains.update(json.load(f))

    return chains




def _is_laibcatalog_chain(chain_id, chain_metadata: dict) -> bool:
    chain = chain_metadata.get(str(chain_id))
    return bool(chain and chain.get("client") == "LaibcatalogClient")


def _load_ignored_price_stores() -> set:
    """
    Returns a set of (chain_id, normalized_store_id) pairs whose Price
    (delta/snapshot) files should not be loaded at all, for now.
    """
    if not IGNORED_STORES_FILE.exists():
        return set()

    with IGNORED_STORES_FILE.open("r", encoding="utf-8") as f:
        entries = json.load(f)

    ignored = set()

    for entry in entries:
        chain_id = str(entry["chain"])

        for store_id in entry.get("stores", []):
            ignored.add((chain_id, normalize_store_id(store_id)))

    return ignored


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


# Price files from snapshot sources are temporary snapshots: after a
# successful load, older Price files for that store are removed.
# Price delta files and PriceFull files are historical and are never
# deleted. Cleanup happens only after loading succeeds.

def cleanup_old_price_files(loaded_files):
    """
    Delete older Price snapshot files after the newest snapshot
    Price file has been successfully loaded.

    Only Price files loaded with snapshot=True are cleaned up.
    PriceFull files and normal Price delta files are never deleted.
    """
    for filepath, snapshot in loaded_files:
        filepath = Path(filepath)

        if not snapshot or filepath.parent.name != "prices":
            continue

        for old_file in filepath.parent.glob("Price*.gz"):
            if old_file == filepath:
                continue

            try:
                old_file.unlink()

                logger.info(
                    "Deleted old Price snapshot file: %s",
                    old_file.name,
                )

            except Exception:
                logger.exception(
                    "Failed deleting old Price snapshot file: %s",
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

    chain_metadata = _load_chain_metadata()
    ignored_price_stores = _load_ignored_price_stores()

    with get_connection() as conn:

        # ---------------------------------------------------------
        # 1. Load pending PriceFull snapshots.
        #
        # Price deltas are only eligible after their same-day
        # PriceFull baseline has loaded successfully.
        # ---------------------------------------------------------

        pricefull_files = get_downloaded_pricefull_files(conn)

        if pricefull_files:
            filepaths = [
                (
                    FEEDS_DIR
                    / str(row[0])
                    / normalize_store_id(row[2])
                    / "pricesfull"
                    / row[4],
                    row[3],
                    True,
                )
                for row in pricefull_files
            ]

            logger.info(
                "Loading %d pending PriceFull file(s)",
                len(filepaths),
            )

            loaded_pricefull = load_price_files(
                conn,
                filepaths,
                FEEDS_DIR,
            )


            if loaded_pricefull:
                discover_new_products(
                    conn,
                    loaded_pricefull,
                    FEEDS_DIR,
                )

        else:
            loaded_pricefull = []

            logger.info(
                "No pending PriceFull files to load"
            )

        logger.info(
            "Successfully loaded %d PriceFull file(s)",
            len(loaded_pricefull),
        )

        # ---------------------------------------------------------
        # 2. Load eligible Price deltas.
        #
        # get_downloaded_unloaded_price_files() only returns a
        # Price file when the same chain/store/date has a loaded
        # PriceFull file.
        # ---------------------------------------------------------

        price_files = get_downloaded_unloaded_price_files(conn)

        if not price_files:
            logger.info(
                "No eligible Price files to load"
            )
            return

        files_to_load = []

        for row in price_files:
            chain_id, _sub_chain_id, store_id, file_type, filename, _file_date = row

            if (
                str(chain_id),
                normalize_store_id(store_id),
            ) in ignored_price_stores:
                logger.info(
                    "IGNORING Price file (in ignored_stores.json): "
                    "chain=%s store=%s filename=%s",
                    chain_id,
                    store_id,
                    filename,
                )
                continue

            filepath = (
                FEEDS_DIR
                / str(chain_id)
                / normalize_store_id(row[2])
                / "prices"
                / filename
            )

            snapshot = _is_laibcatalog_chain(
                chain_id,
                chain_metadata,
            )

            files_to_load.append(
                (filepath, file_type, snapshot)
            )

        if not files_to_load:
            logger.info(
                "No eligible Price files to load after filtering"
            )
            return

        logger.info(
            "Loading %d eligible Price file(s)",
            len(files_to_load),
        )

        loaded_files = load_price_files(
            conn,
            files_to_load,
            FEEDS_DIR,
        )

        if loaded_files:
            discover_new_products(
                conn,
                loaded_files,
                FEEDS_DIR,
            )

        logger.info(
            "Successfully loaded %d Price file(s)",
            len(loaded_files),
        )

        snapshot_by_path = {
            Path(filepath): snapshot
            for filepath, _file_type, snapshot in files_to_load
        }

        loaded_snapshot_files = [
            (
                Path(filepath),
                snapshot_by_path.get(Path(filepath), False),
            )
            for filepath in loaded_files
        ]

        cleanup_old_price_files(loaded_snapshot_files)


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
                    / normalize_store_id(row[2])
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

    logger.info(
        "Successfully loaded %d PromoFull file(s)",
        len(loaded_promofull),
    )

    # ---------------------------------------------------------
    # 4. Load eligible Promo deltas.
    #
    # get_downloaded_unloaded_promo_files() is responsible for
    # checking that the required same-day PromoFull baseline
    # has loaded=True.
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
                / normalize_store_id(row[2])
                / "promos"
                / row[4],
                row[3],
            )
            for row in promo_files
        ]

        logger.info(
            "Loading %d eligible Promo files",
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
    # Refresh HTML caches before each stage; Shufersal listings expire after ~30 minutes.

    run_pricesfull()

    asyncio.run(refresh_html_caches())
    run_prices_and_load()

    asyncio.run(refresh_html_caches())
    run_promos_and_load()


def main():
    logger.info("Starting scheduler")
    logger.info("ENV=%s", settings.ENV)
    logger.info("FEEDS_DIR=%s", FEEDS_DIR)

    test_mode = settings.ENV == "test"
    test_flag = "--test" in sys.argv[1:]

    if test_mode and not test_flag:
        logger.error(
            "ENV=test detected, but --test was not provided. "
            "Refusing to run."
        )
        return

    if test_flag and not test_mode:
        logger.error(
            "--test was provided, but ENV is not 'test'. "
            "Refusing to run."
        )
        return

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "--test":
            command = "all"

        if command == "prices":
            run_file_tracking()
            run_pricesfull()
            run_prices_and_load()
            populate_file_sizes()

        elif command == "pricesfull":
            run_file_tracking()
            run_pricesfull()
            populate_file_sizes()

        elif command == "promos":
            run_file_tracking()
            run_promos_and_load()
            populate_file_sizes()

        elif command == "promosfull":
            run_file_tracking()
            asyncio.run(
                download_promofull(
                    test=settings.ENV == "test"
                )
            )
            populate_file_sizes()

        elif command == "all":
            run_file_tracking()
            run_all()
            populate_file_sizes()

        else:
            logger.error(
                "Unknown command: %s",
                command,
            )

        return

    run_file_tracking()
    run_all()
    populate_file_sizes()


if __name__ == "__main__":
    main()