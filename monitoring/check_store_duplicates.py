import csv
import json
from collections import defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

FILE_TRACKING = BASE_DIR / "data" / "reference" / "file_tracking.csv"
STORES_DIR = BASE_DIR / "data" / "stores"

MONITORING_DATA_DIR = BASE_DIR / "monitoring" / "data"
OUTPUT_FILE = MONITORING_DATA_DIR / "store_duplicates.json"


def check_file_tracking() -> list[dict]:
    groups = defaultdict(set)

    with FILE_TRACKING.open(
        newline="",
        encoding="utf-8-sig",
    ) as f:
        for row in csv.DictReader(f):
            groups[
                (row["chain_id"], row["store_id"])
            ].add(row["sub_chain_id"])

    findings = []

    for (chain_id, store_id), sub_chains in sorted(groups.items()):
        if len(sub_chains) <= 1:
            continue

        findings.append(
            {
                "chain_id": chain_id,
                "store_id": store_id,
                "sub_chains": sorted(sub_chains),
            }
        )

    return findings


def check_subchain_files(
    file_tracking_findings: list[dict],
) -> list[dict]:
    rows = []

    with FILE_TRACKING.open(
        newline="",
        encoding="utf-8-sig",
    ) as f:
        rows = list(csv.DictReader(f))

    findings = []

    for finding in file_tracking_findings:
        chain_id = finding["chain_id"]
        store_id = finding["store_id"]
        sub_chains = finding["sub_chains"]

        files_by_subchain = defaultdict(dict)

        for row in rows:
            if (
                row["chain_id"] != chain_id
                or row["store_id"] != store_id
                or row["sub_chain_id"] not in sub_chains
            ):
                continue

            files_by_subchain[
                row["sub_chain_id"]
            ][row["filename"]] = row

        all_filenames = set().union(
            *(
                files.keys()
                for files in files_by_subchain.values()
            )
        )

        file_comparison = []

        for filename in sorted(all_filenames):
            entries = {
                sub_chain: files_by_subchain[sub_chain].get(filename)
                for sub_chain in sub_chains
            }

            present = {
                sub_chain: entry is not None
                for sub_chain, entry in entries.items()
            }

            sizes = {
                sub_chain: (
                    int(entry["file_size"])
                    if entry and entry["file_size"]
                    else None
                )
                for sub_chain, entry in entries.items()
            }

            same_size = None

            if all(
                entry is not None
                for entry in entries.values()
            ):
                same_size = (
                    len(set(sizes.values())) == 1
                )

            file_comparison.append(
                {
                    "filename": filename,
                    "present": present,
                    "sizes": sizes,
                    "same_size": same_size,
                }
            )

        findings.append(
            {
                "chain_id": chain_id,
                "store_id": store_id,
                "sub_chains": {
                    sub_chain: {
                        "file_count": len(
                            files_by_subchain[sub_chain]
                        ),
                    }
                    for sub_chain in sub_chains
                },
                "files": file_comparison,
            }
        )

    return findings


def check_store_files() -> list[dict]:
    groups = defaultdict(list)

    for path in sorted(STORES_DIR.glob("*.json")):
        with path.open(encoding="utf-8-sig") as f:
            stores = json.load(f)

        for store in stores:
            key = (
                store.get("chain_id"),
                store.get("store_id"),
            )

            groups[key].append(store)

    findings = []

    for (chain_id, store_id), stores in sorted(groups.items()):
        if len(stores) <= 1:
            continue

        unique_records = {
            json.dumps(
                store,
                ensure_ascii=False,
                sort_keys=True,
            )
            for store in stores
        }

        if len(unique_records) == 1:
            continue

        findings.append(
            {
                "chain_id": chain_id,
                "store_id": store_id,
                "stores": [
                    {
                        "name": store.get("name"),
                        "address": store.get("address"),
                        "city": store.get("city"),
                        "zip_code": store.get("zip_code"),
                        "latitude": store.get("latitude"),
                        "longitude": store.get("longitude"),
                    }
                    for store in stores
                ],
            }
        )

    return findings


def main() -> None:
    file_tracking_findings = check_file_tracking()
    subchain_file_findings = check_subchain_files(
        file_tracking_findings
    )
    store_file_findings = check_store_files()

    result = {
        "file_tracking": file_tracking_findings,
        "subchain_files": subchain_file_findings,
        "store_files": store_file_findings,
    }

    MONITORING_DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_FILE.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"File tracking findings: "
        f"{len(file_tracking_findings)}"
    )
    print(
        f"Subchain file comparisons: "
        f"{len(subchain_file_findings)}"
    )
    print(
        f"Store file duplicates: "
        f"{len(store_file_findings)}"
    )
    print(f"Written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()