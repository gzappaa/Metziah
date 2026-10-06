"""
monitoring/detect_pharmacy_stores.py

It detects only pharmacies for shufersal for now.

Update the Shufersal store list in chains_pharm.json
from Shufersal BE Pharm stores.
"""

import json
import re
from pathlib import Path


STORES_PATH = Path("data/stores/shufersal.json")
CHAINS_PATH = Path("data/reference/chains_pharm.json")

SHUFERSAL_CHAIN_ID = "7290027600007"


def normalize_store_id(store_id: object) -> str:
    """Remove leading zeroes from a store ID."""
    value = str(store_id).strip()

    if not value:
        return value

    return str(int(value))


def is_be_pharm(name: object) -> bool:
    """
    Return whether a store name contains the BE Pharm marker.

    BE Pharm is a major Israeli drugstore and pharmacy chain
    owned by Shufersal. We identify BE Pharm stores by their
    store name containing "BE" or "Be".
    """
    if not name:
        return False

    return bool(
        re.search(
            r"\bBE\b",
            str(name),
            re.IGNORECASE,
        )
    )


def get_be_stores() -> list[str]:
    """Return normalized Shufersal BE Pharm store IDs."""
    with STORES_PATH.open(
        encoding="utf-8"
    ) as f:
        stores = json.load(f)

    store_ids = []

    for store in stores:
        if not is_be_pharm(store.get("name")):
            continue

        store_id = normalize_store_id(
            store.get("store_id")
        )

        if store_id:
            store_ids.append(store_id)

    return sorted(
        set(store_ids),
        key=lambda value: int(value),
    )


def update_chain_config(store_ids: list[str]) -> None:
    """Update Shufersal stores in chains_pharm.json."""
    with CHAINS_PATH.open(
        encoding="utf-8"
    ) as f:
        chains = json.load(f)

    chain = chains.get(SHUFERSAL_CHAIN_ID)

    if chain is None:
        raise KeyError(
            f"Chain {SHUFERSAL_CHAIN_ID} not found"
        )

    chain["stores"] = store_ids

    with CHAINS_PATH.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            chains,
            f,
            ensure_ascii=False,
            indent=4,
        )
        f.write("\n")


def main() -> None:
    store_ids = get_be_stores()

    update_chain_config(store_ids)

    print(
        f"Updated Shufersal: {len(store_ids)} BE Pharm stores"
    )

    for store_id in store_ids:
        print(f"  {store_id}")


if __name__ == "__main__":
    main()