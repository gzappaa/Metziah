"""
Adds stores observed in feeds but missing from the publisher Stores JSON.

Reads:
    monitoring/data/stores_missing_from_registry.json

Each store is inserted with a descriptive fallback name and no other
metadata.

Safe to re-run (upsert on chain_id, store_id).

Usage:
    python -m utils.stores.data_enrichment.add_unregistered_stores
"""

import json
import logging
from pathlib import Path

from database.repository import ensure_chain, upsert_stores
from db import get_connection
from models.store import Store

from logging_config import setup_general_logging


setup_general_logging()
logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[3]

MISSING_STORES_FILE = (
    PROJECT_ROOT
    / "monitoring"
    / "data"
    / "stores_missing_from_registry.json"
)

CHAINS_REFERENCE_FILE = (
    PROJECT_ROOT
    / "data"
    / "reference"
    / "chains.json"
)

CHAINS_EXTRA_REFERENCE_FILE = (
    PROJECT_ROOT
    / "data"
    / "reference"
    / "chains_extra.json"
)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main():
    missing_stores = load_json(MISSING_STORES_FILE)

    chains = load_json(CHAINS_REFERENCE_FILE)

    if CHAINS_EXTRA_REFERENCE_FILE.exists():
        chains_extra = load_json(CHAINS_EXTRA_REFERENCE_FILE)
        chains.update(chains_extra)

    all_stores = []

    for source, data in missing_stores.items():
        chain_id = data["chain_id"]

        if chain_id not in chains:
            raise KeyError(
                f"Chain {chain_id} for source '{source}' is not defined "
                f"in chains.json or chains_extra.json"
            )

        for store_id in data["store_ids"]:
            store = Store(
                chain_id=chain_id,
                store_id=store_id,
                name=f"Unregistered store - {source} - {store_id}",
                address=None,
                city=None,
                zip_code=None,
                latitude=None,
                longitude=None,
            )

            all_stores.append(store)

            logger.info(
                "Adding unregistered store: source='%s', "
                "chain_id='%s', store_id='%s'",
                source,
                chain_id,
                store_id,
            )

    if not all_stores:
        logger.info("No unregistered stores to add.")
        return

    chain_ids = {store.chain_id for store in all_stores}

    with get_connection() as conn:
        for chain_id in chain_ids:
            chain = chains[chain_id]

            ensure_chain(
                conn,
                chain_id,
                chain["name_he_normalized"],
                chain["name_en_normalized"],
            )

        upsert_stores(conn, all_stores)
        conn.commit()

    logger.info(
        "Added %d unregistered store(s) across %d chain(s)",
        len(all_stores),
        len(chain_ids),
    )


if __name__ == "__main__":
    main()