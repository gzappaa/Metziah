# inspection/stores/store_data_report.py

from collections import Counter, defaultdict
from pathlib import Path
import json


BASE_DIR = Path(__file__).resolve().parents[2]
STORES_DIR = BASE_DIR / "data" / "stores"
REPORT_FILE = (
    BASE_DIR
    / "inspection"
    / "reports"
    / "stores_data_report.txt"
)


# Fields expected to come from the Stores XML/source data.
REQUIRED_FIELDS = [
    "name",
    "address",
    "city",
]

# Optional source field. It is reported separately and does not
# make a store incomplete.
OPTIONAL_FIELDS = [
    "zip_code",
]


def is_present(value) -> bool:
    """Return True when a field contains a meaningful value."""
    if value is None:
        return False

    if isinstance(value, str):
        value = value.strip()

        if not value or value.lower() == "unknown":
            return False

    return True


def display_filename(filename: str) -> str:
    """Remove .json from a filename when displaying it in the report."""
    if filename.lower().endswith(".json"):
        return filename[:-5]

    return filename


def load_store_files() -> list[tuple[Path, list[dict]]]:
    if not STORES_DIR.exists():
        raise FileNotFoundError(
            f"Stores directory does not exist: {STORES_DIR}"
        )

    results = []

    for path in sorted(STORES_DIR.glob("*.json")):
        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            print(f"ERROR reading {path}: {exc}")
            continue

        if not isinstance(data, list):
            print(
                f"WARNING: {path.name} does not contain a JSON list"
            )
            continue

        stores = [
            store
            for store in data
            if isinstance(store, dict)
        ]

        results.append((path, stores))

    return results


def calculate_completeness(store: dict) -> float:
    """Calculate completeness using only required source fields."""
    present = sum(
        is_present(store.get(field))
        for field in REQUIRED_FIELDS
    )

    return present / len(REQUIRED_FIELDS) * 100


def main():
    files = load_store_files()

    total_stores = 0
    total_files = len(files)

    # Required-field counts across all chains.
    required_field_counts = Counter()

    # Optional-field counts across all chains.
    optional_field_counts = Counter()

    # chain_id -> store count
    stores_by_chain = Counter()

    # chain_id -> JSON filename
    chain_files = {}

    # chain_id -> field -> present count
    chain_field_counts = defaultdict(Counter)

    # Overall completeness buckets based only on required fields.
    completeness_buckets = Counter()

    # chain_id -> completeness bucket -> count
    chain_completeness = defaultdict(Counter)

    # (chain_id, store_id) -> records
    chain_store_records = defaultdict(list)

    malformed_records = []
    empty_field_examples = defaultdict(list)

    for path, stores in files:
        for index, store in enumerate(stores):
            total_stores += 1

            chain_id = str(
                store.get("chain_id")
                or "<missing>"
            )

            store_id = str(
                store.get("store_id")
                or "<missing>"
            )

            stores_by_chain[chain_id] += 1

            # Remember which JSON file this chain came from.
            chain_files[chain_id] = path.name

            # Keep the actual record for duplicate inspection.
            chain_store_records[
                (chain_id, store_id)
            ].append(
                {
                    "path": path.name,
                    "index": index,
                    "store": store,
                }
            )

            # ----------------------------------------------------
            # Required field completeness
            # ----------------------------------------------------

            for field in REQUIRED_FIELDS:
                if is_present(store.get(field)):
                    required_field_counts[field] += 1
                    chain_field_counts[chain_id][field] += 1
                else:
                    if len(empty_field_examples[field]) < 20:
                        empty_field_examples[field].append(
                            (
                                chain_id,
                                store_id,
                                path.name,
                            )
                        )

            # ----------------------------------------------------
            # Optional field completeness
            # ----------------------------------------------------

            for field in OPTIONAL_FIELDS:
                if is_present(store.get(field)):
                    optional_field_counts[field] += 1
                    chain_field_counts[chain_id][field] += 1
                else:
                    if len(empty_field_examples[field]) < 20:
                        empty_field_examples[field].append(
                            (
                                chain_id,
                                store_id,
                                path.name,
                            )
                        )

            # ----------------------------------------------------
            # Required-field completeness score
            # ----------------------------------------------------

            score = calculate_completeness(store)

            if score == 100:
                bucket = "100%"
            elif score >= 66.67:
                bucket = "66-99%"
            elif score >= 33.33:
                bucket = "33-66%"
            else:
                bucket = "0-32%"

            completeness_buckets[bucket] += 1
            chain_completeness[chain_id][bucket] += 1

            # ----------------------------------------------------
            # Basic record validation
            # ----------------------------------------------------

            if not is_present(store.get("chain_id")):
                malformed_records.append(
                    (
                        path.name,
                        index,
                        "missing chain_id",
                    )
                )

            if not is_present(store.get("store_id")):
                malformed_records.append(
                    (
                        path.name,
                        index,
                        "missing store_id",
                    )
                )

    # ------------------------------------------------------------
    # Duplicate store IDs
    # ------------------------------------------------------------

    duplicates = {
        key: records
        for key, records in chain_store_records.items()
        if key[1] != "<missing>" and len(records) > 1
    }

    # ------------------------------------------------------------
    # Calculate complete/incomplete stores per chain
    # ------------------------------------------------------------

    complete_stores_by_chain = Counter()

    for chain_id in stores_by_chain:
        complete_stores_by_chain[chain_id] = (
            chain_completeness[chain_id]["100%"]
        )

    incomplete_stores_by_chain = {
        chain_id: stores_by_chain[chain_id]
        - complete_stores_by_chain[chain_id]
        for chain_id in stores_by_chain
    }

    # ------------------------------------------------------------
    # Build report
    # ------------------------------------------------------------

    lines = []

    lines.append("STORES DATA COMPLETENESS REPORT")
    lines.append("=" * 100)
    lines.append("")
    lines.append(f"Stores directory: {STORES_DIR}")
    lines.append(f"JSON files analyzed: {total_files}")
    lines.append(f"Chains: {len(stores_by_chain)}")
    lines.append(f"Total stores: {total_stores}")
    lines.append("")

    # ------------------------------------------------------------
    # Stores per chain
    # ------------------------------------------------------------

    lines.append("STORES PER CHAIN")
    lines.append("-" * 100)

    for chain_id, count in stores_by_chain.most_common():
        percentage = (
            count / total_stores * 100
            if total_stores
            else 0
        )

        filename = display_filename(
            chain_files.get(
                chain_id,
                "<unknown file>",
            )
        )

        lines.append(
            f"{chain_id} ({filename}): "
            f"{count:>8} stores "
            f"({percentage:6.2f}%)"
        )

    lines.append("")

    # ------------------------------------------------------------
    # Required field completeness — all chains
    # ------------------------------------------------------------

    lines.append(
        "REQUIRED FIELD COMPLETENESS — ALL CHAINS"
    )
    lines.append("-" * 100)

    for field in REQUIRED_FIELDS:
        present = required_field_counts[field]
        missing = total_stores - present

        present_percentage = (
            present / total_stores * 100
            if total_stores
            else 0
        )

        missing_percentage = (
            missing / total_stores * 100
            if total_stores
            else 0
        )

        lines.append(
            f"{field:<15} "
            f"present: {present:>8} ({present_percentage:6.2f}%)   "
            f"missing: {missing:>8} ({missing_percentage:6.2f}%)"
        )

    lines.append("")

    # ------------------------------------------------------------
    # Optional field completeness — all chains
    # ------------------------------------------------------------

    lines.append(
        "OPTIONAL FIELD COMPLETENESS — ALL CHAINS"
    )
    lines.append("-" * 100)

    for field in OPTIONAL_FIELDS:
        present = optional_field_counts[field]
        missing = total_stores - present

        present_percentage = (
            present / total_stores * 100
            if total_stores
            else 0
        )

        missing_percentage = (
            missing / total_stores * 100
            if total_stores
            else 0
        )

        lines.append(
            f"{field:<15} "
            f"present: {present:>8} ({present_percentage:6.2f}%)   "
            f"missing: {missing:>8} ({missing_percentage:6.2f}%)"
        )

    lines.append("")

    # ------------------------------------------------------------
    # Field completeness per chain
    # ------------------------------------------------------------

    lines.append("FIELD COMPLETENESS — PER CHAIN")
    lines.append("-" * 100)

    header = (
        f"{'Chain ID / File':<55}"
        f"{'Stores':>9}"
    )

    for field in REQUIRED_FIELDS:
        header += f"{field:>13}"

    for field in OPTIONAL_FIELDS:
        header += f"{field:>13}"

    lines.append(header)
    lines.append("-" * 100)

    for chain_id in sorted(stores_by_chain):
        count = stores_by_chain[chain_id]

        filename = display_filename(
            chain_files.get(
                chain_id,
                "<unknown file>",
            )
        )

        chain_display = f"{chain_id} ({filename})"

        line = f"{chain_display:<55}{count:>9}"

        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            present = chain_field_counts[chain_id][field]

            percentage = (
                present / count * 100
                if count
                else 0
            )

            line += f"{percentage:>12.2f}%"

        lines.append(line)

    lines.append("")

    # ------------------------------------------------------------
    # Required-field store completeness
    # ------------------------------------------------------------

    lines.append(
        "STORE COMPLETENESS — REQUIRED FIELDS ONLY"
    )
    lines.append("-" * 100)

    for bucket in [
        "100%",
        "66-99%",
        "33-66%",
        "0-32%",
    ]:
        count = completeness_buckets[bucket]

        percentage = (
            count / total_stores * 100
            if total_stores
            else 0
        )

        lines.append(
            f"{bucket:<12} "
            f"{count:>8} stores "
            f"({percentage:6.2f}%)"
        )

    lines.append("")

    # ------------------------------------------------------------
    # Complete/incomplete stores per chain
    # ------------------------------------------------------------

    lines.append(
        "COMPLETE vs INCOMPLETE STORES — PER CHAIN"
    )
    lines.append("-" * 100)

    header = (
        f"{'Chain ID / File':<55}"
        f"{'Stores':>9}"
        f"{'Complete':>12}"
        f"{'Incomplete':>13}"
        f"{'Complete %':>13}"
    )

    lines.append(header)
    lines.append("-" * 100)

    for chain_id in sorted(stores_by_chain):
        total = stores_by_chain[chain_id]
        complete = complete_stores_by_chain[chain_id]
        incomplete = incomplete_stores_by_chain[chain_id]

        percentage = (
            complete / total * 100
            if total
            else 0
        )

        filename = display_filename(
            chain_files.get(
                chain_id,
                "<unknown file>",
            )
        )

        chain_display = f"{chain_id} ({filename})"

        lines.append(
            f"{chain_display:<55}"
            f"{total:>9}"
            f"{complete:>12}"
            f"{incomplete:>13}"
            f"{percentage:>12.2f}%"
        )

    lines.append("")

    # ------------------------------------------------------------
    # Duplicate store IDs
    # ------------------------------------------------------------

    lines.append("DUPLICATE STORE IDs WITHIN CHAIN")
    lines.append("-" * 100)

    if duplicates:
        for (chain_id, store_id), records in sorted(
            duplicates.items()
        ):
            filename = display_filename(
                chain_files.get(
                    chain_id,
                    "<unknown file>",
                )
            )

            stores = [
                record["store"]
                for record in records
            ]

            identical = all(
                store == stores[0]
                for store in stores[1:]
            )

            lines.append(
                f"{chain_id} ({filename}) / {store_id} "
                f"({len(records)} occurrences)"
            )

            lines.append(
                f"    Identical records: "
                f"{'YES' if identical else 'NO'}"
            )

            for record in records:
                lines.append(
                    f"    {display_filename(record['path'])} "
                    f"| record {record['index']}"
                )

                if not identical:
                    lines.append(
                        f"        name={record['store'].get('name')!r}"
                    )
                    lines.append(
                        f"        address={record['store'].get('address')!r}"
                    )
                    lines.append(
                        f"        city={record['store'].get('city')!r}"
                    )
                    lines.append(
                        f"        zip_code={record['store'].get('zip_code')!r}"
                    )
    else:
        lines.append("None")

    lines.append("")

    # ------------------------------------------------------------
    # Malformed records
    # ------------------------------------------------------------

    lines.append("MALFORMED RECORDS")
    lines.append("-" * 100)

    if malformed_records:
        for filename, index, reason in malformed_records:
            lines.append(
                f"{display_filename(filename)} | "
                f"record {index} | {reason}"
            )
    else:
        lines.append("None")

    lines.append("")

    # ------------------------------------------------------------
    # Examples of missing fields
    # ------------------------------------------------------------

    lines.append("EXAMPLES OF MISSING FIELDS")
    lines.append("-" * 100)

    for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        examples = empty_field_examples[field]

        lines.append("")
        lines.append(f"{field}:")

        if not examples:
            lines.append("    None")
            continue

        for chain_id, store_id, filename in examples:
            lines.append(
                f"    chain={chain_id} "
                f"store={store_id} "
                f"file={display_filename(filename)}"
            )

    lines.append("")

    # ------------------------------------------------------------
    # Write report
    # ------------------------------------------------------------

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"Analyzed {total_stores} stores.")
    print(f"Found {len(stores_by_chain)} chains.")
    print("Report written to:")
    print(REPORT_FILE)


if __name__ == "__main__":
    main()