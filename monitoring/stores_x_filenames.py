import csv
import json
from pathlib import Path


TRACKING_FILE = Path("data/reference/file_tracking.csv")
STORES_DIR = Path("data/stores")
CHAINS_FILE = Path("data/reference/chains.json")
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
        str(store["store_id"]).strip()
        for store in stores
        if isinstance(store, dict) and "store_id" in store
    }


def load_chains() -> dict:
    with CHAINS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    chains = load_chains()

    # source -> store IDs appearing in file_tracking
    feed_store_ids: dict[str, set[str]] = {}

    with TRACKING_FILE.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            source = row["source"].strip()
            store_id = row["store_id"].strip()

            if not source or not store_id:
                continue

            feed_store_ids.setdefault(source, set()).add(store_id)

    missing = {}

    for source, store_ids in sorted(feed_store_ids.items()):
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

        if not source_missing:
            continue

        # Find the chain ID from chains.json using the source name.
        chain_id = None

        for candidate_chain_id, chain in chains.items():
            if chain.get("name_en_normalized") == source:
                chain_id = candidate_chain_id
                break

        if chain_id is None:
            print(
                f"WARNING: No chain found in chains.json "
                f"for source '{source}'"
            )
            continue

        missing[source] = {
            "chain_id": chain_id,
            "store_ids": source_missing,
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
            f"{len(data['store_ids'])} missing"
        )
        print("  " + ", ".join(data["store_ids"]))


if __name__ == "__main__":
    main()