"""
Seeds the `stores` table from geocoded stores JSON files under data/stores/.

In normal mode, all stores are seeded.

In --test mode, only stores whose (chain_id, store_id) directories exist
under data/test_feeds/ are seeded.

Store IDs are matched ignoring leading zeroes:
    006 == 06 == 6

Chain metadata is loaded from data/reference/chains.json, which is the
source of truth for chain names.

Safe to re-run any time (upsert on chain_id, store_id).

Usage:
    python -m utils.stores.seed_stores
    python -m utils.stores.seed_stores --test
"""

import argparse
import json
import logging
from pathlib import Path

from database.repository import ensure_chain, upsert_stores
from db import get_connection
from models.store import Store

from logging_config import setup_general_logging


setup_general_logging()
logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

STORES_DIR = PROJECT_ROOT / "data" / "stores"

CHAINS_REFERENCE_FILE = (
    PROJECT_ROOT / "data" / "reference" / "chains.json"
)

CHAINS_EXTRA_REFERENCE_FILE = (
    PROJECT_ROOT / "data" / "reference" / "chains_extra.json"
)


def normalize_store_id(store_id) -> str:
    """
    Normalize store IDs for comparison.

    Examples:
        006 -> 6
        06  -> 6
        6   -> 6
        069 -> 69
    """
    value = str(store_id).strip()

    if value.isdigit():
        return value.lstrip("0") or "0"

    return value


def load_stores_from_json(path: Path) -> list[Store]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    return [
        Store(
            chain_id=entry["chain_id"],
            store_id=normalize_store_id(entry["store_id"]),
            name=entry["name"],
            address=entry.get("address"),
            city=entry.get("city"),
            zip_code=entry.get("zip_code"),
            latitude=entry.get("latitude"),
            longitude=entry.get("longitude"),
        )
        for entry in raw
    ]


def load_chains_from_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_test_store_keys(test_feeds_dir: Path) -> set[tuple[str, str]]:
    """
    Read the exact chain/store directories present in test_feeds.

    Expected structure:

        data/test_feeds/
            7290000000003/
                006/
                007/
                008/
            7290000000004/
                001/
                002/

    Returns normalized (chain_id, store_id) pairs.
    """

    if not test_feeds_dir.exists():
        raise FileNotFoundError(
            f"Test feeds directory does not exist: {test_feeds_dir}"
        )

    test_store_keys = set()

    for chain_dir in test_feeds_dir.iterdir():
        if not chain_dir.is_dir():
            continue

        chain_id = str(chain_dir.name).strip()

        for store_dir in chain_dir.iterdir():
            if not store_dir.is_dir():
                continue

            store_id = normalize_store_id(store_dir.name)

            test_store_keys.add(
                (
                    chain_id,
                    store_id,
                )
            )

    return test_store_keys


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Seed only stores present in data/test_feeds",
    )

    args = parser.parse_args()

    chains = load_chains_from_json(
        CHAINS_REFERENCE_FILE
    )

    chains_extra = {}

    if CHAINS_EXTRA_REFERENCE_FILE.exists():
        chains_extra = load_chains_from_json(
            CHAINS_EXTRA_REFERENCE_FILE
        )

        chains.update(chains_extra)

        logger.info(
            "Loaded %d extra chain(s) from %s",
            len(chains_extra),
            CHAINS_EXTRA_REFERENCE_FILE,
        )

    store_files = sorted(
        STORES_DIR.glob("*.json")
    )

    logger.info(
        "Found %d store JSON file(s) under %s",
        len(store_files),
        STORES_DIR,
    )

    if not store_files:
        return

    if args.test:
        test_feeds_dir = (
            PROJECT_ROOT / "data" / "test_feeds"
        )

        test_store_keys = load_test_store_keys(
            test_feeds_dir
        )

        logger.info(
            "Found %d store(s) in test feeds",
            len(test_store_keys),
        )
    else:
        test_store_keys = None

    all_stores = []

    for store_file in store_files:
        stores = load_stores_from_json(store_file)

        if test_store_keys is not None:
            stores = [
                store
                for store in stores
                if (
                    str(store.chain_id).strip(),
                    normalize_store_id(store.store_id),
                ) in test_store_keys
            ]

        if stores:
            if args.test:
                logger.info(
                    "Selected %d store(s) from %s",
                    len(stores),
                    store_file,
                )
            else:
                logger.info(
                    "Loaded %d store(s) from %s",
                    len(stores),
                    store_file,
                )

            all_stores.extend(stores)

    if not all_stores:
        logger.info("No stores to seed.")
        return

    chain_ids = {
        store.chain_id
        for store in all_stores
    }

    if args.test:
        chain_ids.update(chains_extra)

    with get_connection() as conn:
        for chain_id in chain_ids:
            chain = chains.get(chain_id)

            if chain is None:
                raise KeyError(
                    f"Chain {chain_id} is not defined in "
                    f"{CHAINS_REFERENCE_FILE}"
                )

            ensure_chain(
                conn,
                chain_id,
                chain["name_he_normalized"],
                chain["name_en_normalized"],
            )

        upsert_stores(
            conn,
            all_stores,
        )

        conn.commit()

    logger.info(
        "Seeded %d store(s) across %d chain(s)",
        len(all_stores),
        len(chain_ids),
    )


if __name__ == "__main__":
    main()