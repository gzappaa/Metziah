'''
The stores file for each source is currently the source of truth for
the stores published by that source.

The Stores file tells us which chain_id each store belongs to.

For example, a source may publish:

    Stores9999999999999-000-001-20260101-000000

    inside: <Root>
        <ChainID>9999999999999</ChainID>  <- parse and get the chain_id
        <ChainName>test</ChainName>
        <LastUpdateDate>2026-01-01</LastUpdateDate>
        <LastUpdateTime>00:00:00.211</LastUpdateTime>
        <SubChains>

and get_stores.py creates:

    chain_id = 9999999999999
    store_id = 1

However, the same source may later publish a price file such as:

    Price7777777777777-000-003-20260101-000001

This means that the source is publishing store 3 under chain_id
7777777777777, even though the existing stores file may currently
have store 3 under chain_id 9999999999999.

When the price file is loaded, chain_id 7777777777777 must exist so
that the store can be associated with the correct chain.

monitoring/chains_missing.py detects these chain IDs that appear in
feed filenames but are missing from the chain registry.

This script then uses that information to update the source's stores
file, changing the affected store's chain_id to the chain_id found
in the feed filename.

For example:

    9999999999999 + store 3

becomes:

    7777777777777 + store 3

The updated stores file is then used by seed_stores, together with
chains_extra.json, so the newly discovered chain and its store can
be added to the database.

This allows the source's actual feed filenames to become the source
of truth for the chain_id of a store when the Stores file has not yet
been updated by the source.
'''

import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parents[2]

FILENAME_CHAINS_FILE = (
    BASE_DIR
    / "monitoring"
    / "data"
    / "filename_chains.json"
)

STORES_DIR = (
    BASE_DIR
    / "data"
    / "stores"
)


def load_json(path: Path) -> dict:
    with path.open(
        encoding="utf-8",
    ) as file:
        return json.load(file)


def write_json(
    path: Path,
    data,
) -> None:
    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=4,
        )

        file.write("\n")


def find_store(
    stores: list[dict],
    store_id: str,
) -> dict | None:
    padded_store_id = store_id.zfill(3)

    for store in stores:
        current_store_id = str(
            store.get("store_id", "")
        )

        if current_store_id == padded_store_id:
            return store

    for store in stores:
        current_store_id = str(
            store.get("store_id", "")
        )

        if current_store_id == str(
            int(store_id)
        ):
            return store

    return None


def enrich_source(
    source: str,
    source_data: dict,
) -> None:
    unknown_chain_ids = source_data.get(
        "unknown_chain_ids",
        [],
    )

    unknown_store_ids = source_data.get(
        "unknown_store_ids",
        {},
    )

    if not unknown_chain_ids:
        return

    stores_file = (
        STORES_DIR
        / f"{source}.json"
    )

    if not stores_file.exists():
        logger.error(
            "Stores file not found: source='%s', path='%s'",
            source,
            stores_file,
        )
        return

    stores = load_json(stores_file)

    if not isinstance(stores, list):
        logger.error(
            "Invalid stores file: source='%s', expected a list",
            source,
        )
        return

    changed = False

    for unknown_chain_id in unknown_chain_ids:
        store_ids = unknown_store_ids.get(
            unknown_chain_id,
            [],
        )

        for store_id in store_ids:
            store = find_store(
                stores,
                store_id,
            )

            if store is None:
                logger.error(
                    "Store not found: "
                    "source='%s', chain_id='%s', store_id='%s'",
                    source,
                    unknown_chain_id,
                    store_id,
                )
                continue

            old_chain_id = store.get(
                "chain_id"
            )

            if old_chain_id == unknown_chain_id:
                continue

            store["chain_id"] = unknown_chain_id
            changed = True

            logger.info(
                "Enriched store chain ID: "
                "source='%s', store_id='%s', "
                "chain_id='%s' -> '%s'",
                source,
                store_id,
                old_chain_id,
                unknown_chain_id,
            )

    if changed:
        write_json(
            stores_file,
            stores,
        )

        logger.info(
            "Updated stores file: %s",
            stores_file,
        )


def main() -> None:
    filename_chains = load_json(
        FILENAME_CHAINS_FILE
    )

    for source, source_data in filename_chains.items():
        enrich_source(
            source,
            source_data,
        )


if __name__ == "__main__":
    main()