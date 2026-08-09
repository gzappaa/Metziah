"""
Seeds the `stores` table from a geocoded JSON file (e.g.
data/stores/machsenei_hashuk.json). This unblocks load_prices.py --
get_store_id() raises KeyError on purpose if a store hasn't been seeded,
so this has to run before any price file for a new chain can load.

Safe to re-run any time (upsert on chain_id, store_id) -- including
after a DROP DATABASE, or after re-geocoding a store.

Usage:
    python -m utils.seed_stores data/stores/machsenei_hashuk.json
"""

import argparse
import json
import logging
from pathlib import Path

from database.repository import ensure_chain, upsert_stores
from db import get_connection
from models.store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def load_stores_from_json(path: Path) -> list[Store]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    return [
        Store(
            chain_id=entry["chain_id"],
            store_id=entry["store_id"],
            name=entry["name"],
            address=entry.get("address"),
            city=entry.get("city"),
            zip_code=entry.get("zip_code"),
            latitude=entry.get("latitude"),
            longitude=entry.get("longitude"),
        )
        for entry in raw
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()

    stores = load_stores_from_json(args.json_path)
    logger.info("Loaded %d store(s) from %s", len(stores), args.json_path)

    if not stores:
        return

    chain_ids = {s.chain_id for s in stores}

    with get_connection() as conn:
        for chain_id in chain_ids:
            ensure_chain(conn, chain_id)

        upsert_stores(conn, stores)
        conn.commit()

    logger.info("Seeded %d store(s) across %d chain(s)", len(stores), len(chain_ids))


if __name__ == "__main__":
    main()