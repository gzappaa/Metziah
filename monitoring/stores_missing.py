'''
Some stores tracked in the feeds are not present in the Stores registry.
Before adding those stores to the database, we first need to discover all
filenames from all stores and generate file_tracking.csv:

    python -m utils.file_tracking.load_file_tracking --report generate

If file_tracking.csv does not exist, print a warning and generate it first.
The store must exist in the database before loading products, promotions,
or prices; otherwise those loaders will fail.
'''

import csv
import json
from pathlib import Path
from downloaders.common import normalize_store_id

TRACKING_FILE = Path("data/reference/file_tracking.csv")
STORES_DIR = Path("data/stores")
CHAINS_FILES = [
    Path("data/reference/chains.json"),
    Path("data/reference/chains_extra.json"),
]
OUTPUT_FILE = Path("monitoring/data/stores_missing_from_registry.json")


def store_id_candidates(store_id: str) -> list[str]:
    """Return the original ID followed by versions with leading zeros removed."""
    store_id = str(store_id).strip()

    candidates = [store_id]

    current = store_id
    while current.startswith("0") and len(current) > 1:
        current = current[1:]
        candidates.append(current)

    return candidates


def get_store_ids(stores_data) -> set[str]:
    """Extract store IDs from the Stores JSON."""
    if isinstance(stores_data, list):
        stores = stores_data
    elif isinstance(stores_data, dict):
        if isinstance(stores_data.get("stores"), list):
            stores = stores_data["stores"]
        else:
            stores = list(stores_data.values())
    else:
        return set()

    return {
        normalize_store_id(store["store_id"]).strip()
        for store in stores
        if isinstance(store, dict) and "store_id" in store
    }


def load_chains() -> dict:
    """Load and merge chains.json and chains_extra.json."""
    chains = {}

    for chains_file in CHAINS_FILES:
        with chains_file.open("r", encoding="utf-8") as f:
            chains.update(json.load(f))

    return chains


def main():
    if not TRACKING_FILE.exists():
        print(
            f"WARNING: File tracking does not exist: {TRACKING_FILE}\n"
            "Generate it first with:\n"
            "  python -m utils.file_tracking.load_file_tracking --report generate"
        )
        return
    
    chains = load_chains()

    # chain_id -> {
    #     "source": source name,
    #     "store_ids": set(...)
    # }
    feed_data: dict[str, dict] = {}

    with TRACKING_FILE.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            chain_id = row["chain_id"].strip()
            source = row["source"].strip()
            store_id = row["store_id"].strip()

            if not chain_id or not source or not store_id:
                continue

            if chain_id not in feed_data:
                feed_data[chain_id] = {
                    "source": source,
                    "store_ids": set(),
                }

            feed_data[chain_id]["store_ids"].add(store_id)

    missing = {}

    for chain_id, data in sorted(feed_data.items()):
        source = data["source"]
        store_ids = data["store_ids"]

        stores_file = STORES_DIR / f"{source}.json"

        if not stores_file.exists():
            print(f"WARNING: Stores file does not exist: {stores_file}")
            source_missing = sorted(store_ids)
        else:
            with stores_file.open("r", encoding="utf-8") as f:
                stores_data = json.load(f)

            registry_store_ids = get_store_ids(stores_data)

            source_missing = []

            for store_id in sorted(store_ids):
                candidates = store_id_candidates(store_id)

                if not any(candidate in registry_store_ids for candidate in candidates):
                    source_missing.append(store_id)

        if chain_id not in chains:
            print(
                f"WARNING: No chain found in chains.json or chains_extra.json "
                f"for chain_id '{chain_id}'"
            )

        # Normally only output missing stores.
        # For chain 0000000000000, output ALL tracked stores.
        if not source_missing and chain_id != "0000000000000":
            continue

        missing[source] = {
            "chain_id": chain_id,
            "store_ids": (
                sorted(store_ids)
                if chain_id == "0000000000000"
                else source_missing
            ),
        }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(missing, f, ensure_ascii=False, indent=4)
        f.write("\n")

    print(f"Written: {OUTPUT_FILE}")
    print(f"Sources with missing stores: {len(missing)}")

    for source, data in missing.items():
        print(
            f"{source}: chain_id={data['chain_id']}, "
            f"{len(data['store_ids'])} stores"
        )
        print("  " + ", ".join(data["store_ids"]))


if __name__ == "__main__":
    
    main()