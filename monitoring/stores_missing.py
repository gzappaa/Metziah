"""
monitoring/stores_missing.py

Finds stores tracked in feeds but missing from the publisher Stores JSON.

Before running, generate file_tracking.csv:

    python -m utils.file_tracking.load_file_tracking --report generate

Groups records by (source, chain_id).

Also detects registered chains published by a different source.
"""

import csv
import json
import re
from pathlib import Path

from downloaders.common import normalize_store_id


TRACKING_FILE = Path("data/reference/file_tracking.csv")
STORES_DIR = Path("data/stores")

CHAINS_FILES = [
    Path("data/reference/chains.json"),
    Path("data/reference/chains_extra.json"),
]

OUTPUT_FILE = Path("monitoring/data/stores_missing_from_registry.json")

PLACEHOLDER_CHAIN_ID = "0000000000000"


def store_id_candidates(store_id: str) -> list[str]:
    """Return original ID followed by versions without leading zeros."""
    store_id = str(store_id).strip()

    candidates = [store_id]
    current = store_id

    while current.startswith("0") and len(current) > 1:
        current = current[1:]
        candidates.append(current)

    return candidates


def get_store_pairs(stores_data) -> set[tuple[str, str]]:
    """Extract registered (chain_id, normalized_store_id) pairs."""
    if isinstance(stores_data, list):
        stores = stores_data
    elif isinstance(stores_data, dict):
        if isinstance(stores_data.get("stores"), list):
            stores = stores_data["stores"]
        else:
            stores = list(stores_data.values())
    else:
        return set()

    pairs = set()

    for store in stores:
        if not isinstance(store, dict):
            continue

        chain_id = str(store.get("chain_id") or "").strip()
        store_id = store.get("store_id")

        if not chain_id or store_id is None:
            continue

        normalized_store_id = normalize_store_id(str(store_id)).strip()

        if normalized_store_id:
            pairs.add((chain_id, normalized_store_id))

    return pairs


def load_chains() -> dict:
    """Load and merge chains.json and chains_extra.json."""
    chains = {}

    for chains_file in CHAINS_FILES:
        if not chains_file.exists():
            continue

        with chains_file.open("r", encoding="utf-8") as f:
            chains.update(json.load(f))

    return chains


def extract_store_id_from_filename(
    filename: str,
    chain_id: str,
) -> str:
    """
    Extract store ID from filenames when the tracking CSV field is empty.

    Example:
        Price0000000000000-7999-202206130915.gz
        -> 7999
    """
    if not filename or not chain_id:
        return ""

    pattern = rf"{re.escape(chain_id)}-(\d+)-"
    match = re.search(pattern, filename)

    return match.group(1) if match else ""


def load_feed_data() -> dict:
    """
    Return feed records grouped by (source, chain_id).

    Chain IDs and feed sources are preserved as published.
    Store IDs are extracted from filenames when missing from the CSV.
    """
    feed_data = {}

    with TRACKING_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            filename = (row.get("filename") or "").strip()

            if filename.lower().startswith("stores"):
                continue

            source = (row.get("source") or "").strip().lower()
            chain_id = (row.get("chain_id") or "").strip()
            store_id = (row.get("store_id") or "").strip()

            if not source or not chain_id:
                continue

            if not store_id:
                store_id = extract_store_id_from_filename(
                    filename,
                    chain_id,
                )

            if not store_id:
                continue

            key = (source, chain_id)
            feed_data.setdefault(key, set()).add(store_id)

    return feed_data


def find_chain_anomalies(
    feed_data: dict,
    chains: dict,
) -> list[dict]:
    """Find registered chains published by a different source."""
    anomalies = []

    for source, chain_id in sorted(feed_data):
        chain = chains.get(chain_id)

        if not chain:
            continue

        owner = (chain.get("name_en_normalized") or "").strip().lower()

        if not owner or owner == "unknown":
            continue

        if owner != source:
            anomalies.append(
                {
                    "source": source,
                    "chain_id": chain_id,
                    "registered_owner": owner,
                }
            )

    return anomalies


def find_missing_stores(
    source: str,
    chain_id: str,
    store_ids: set[str],
) -> list[str]:
    """Compare exact (chain_id, store_id) pairs against the publisher's registry."""
    stores_file = STORES_DIR / f"{source}.json"

    if not stores_file.exists():
        print(f"WARNING: Stores file does not exist: {stores_file}")
        return sorted(store_ids)

    with stores_file.open("r", encoding="utf-8") as f:
        stores_data = json.load(f)

    registered_pairs = get_store_pairs(stores_data)

    missing = []

    for store_id in sorted(store_ids):
        normalized_store_id = normalize_store_id(store_id).strip()

        is_registered = any(
            (chain_id, candidate) in registered_pairs
            for candidate in store_id_candidates(normalized_store_id)
        )

        if not is_registered:
            missing.append(store_id)

    return missing


def main():
    if not TRACKING_FILE.exists():
        print(
            f"WARNING: File tracking does not exist: {TRACKING_FILE}\n"
            "Generate it first with:\n"
            "  python -m utils.file_tracking.load_file_tracking --report generate"
        )
        return

    chains = load_chains()
    feed_data = load_feed_data()

    anomalies = find_chain_anomalies(feed_data, chains)

    if anomalies:
        print("\nCHAIN SOURCE ANOMALIES:")
        for anomaly in anomalies:
            print(
                f"  {anomaly['source']} publishes chain "
                f"{anomaly['chain_id']} (registered owner: "
                f"{anomaly['registered_owner']})"
            )

    missing = {}

    for (source, chain_id), store_ids in sorted(feed_data.items()):
        if chain_id not in chains:
            print(
                f"WARNING: No chain found in chains.json or chains_extra.json "
                f"for chain_id '{chain_id}' (source='{source}')"
            )

        source_missing = find_missing_stores(
            source,
            chain_id,
            store_ids,
        )

        if not source_missing:
            continue

        key = f"{source}:{chain_id}"

        missing[key] = {
            "source": source,
            "chain_id": chain_id,
            "store_ids": source_missing,
        }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            missing,
            f,
            ensure_ascii=False,
            indent=4,
        )
        f.write("\n")

    print(f"\nWritten: {OUTPUT_FILE}")
    print(f"Source/chain combinations with missing stores: {len(missing)}")

    for key, data in missing.items():
        print(f"{key}: {len(data['store_ids'])} stores")
        print("  " + ", ".join(data["store_ids"]))


if __name__ == "__main__":
    main()