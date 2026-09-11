import csv
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

TRACKING_FILE = (
    PROJECT_ROOT
    / "data"
    / "reference"
    / "file_tracking.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "inspection"
    / "reports"
    / "file_tracking_report.txt"
)


PRICE_SNAPSHOT_RATIO = 0.75
TINY_FILE_SIZE = 1


def load_records() -> list[dict]:
    with TRACKING_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(csv.DictReader(f))


def size_bytes(record: dict) -> int | None:
    value = (record.get("file_size") or "").strip()

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def format_size(size: int | None) -> str:
    if size is None:
        return "N/A"
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024**2:.2f} MB"


def group_by_source(records):
    result = defaultdict(list)

    for record in records:
        source = record.get("source", "").strip()
        if source:
            result[source].append(record)

    return result


def file_type_counts(records):
    counts = defaultdict(int)

    for record in records:
        counts[record.get("file_type", "").strip()] += 1

    return dict(sorted(counts.items()))


def get_biggest_files(records, limit=20):
    records_with_size = [
        record
        for record in records
        if size_bytes(record) is not None
    ]

    return sorted(
        records_with_size,
        key=size_bytes,
        reverse=True,
    )[:limit]


def get_tiny_files(records):
    return [
        record
        for record in records
        if (
            size_bytes(record) is not None
            and size_bytes(record) <= TINY_FILE_SIZE
        )
    ]


def get_zero_byte_files(records):
    return [
        record
        for record in records
        if size_bytes(record) == 0
    ]


def get_missing_downloads(records):
    return [
        record
        for record in records
        if record.get("downloaded", "").strip().lower() == "false"
    ]


def build_price_snapshot_report(records):
    """
    Compare Price and PriceFull for the same source, chain_id and store_id.

    A Price is considered a snapshot candidate when it is at least
    PRICE_SNAPSHOT_RATIO of the corresponding PriceFull size.

    Only report Price files classified as snapshot candidates.
    """

    price_full = {}
    prices = []

    for record in records:
        file_type = record.get("file_type", "").strip()

        key = (
            record.get("source", "").strip(),
            record.get("chain_id", "").strip(),
            record.get("store_id", "").strip(),
            record.get("file_date", "").strip(),
        )

        if file_type == "PriceFull":
            price_full[key] = record

        elif file_type == "Price":
            prices.append(record)

    snapshots = []

    for price in prices:
        key = (
            price.get("source", "").strip(),
            price.get("chain_id", "").strip(),
            price.get("store_id", "").strip(),
            price.get("file_date", "").strip(),
        )

        full = price_full.get(key)

        if not full:
            continue

        price_size = size_bytes(price)
        full_size = size_bytes(full)

        if price_size is None or full_size is None:
            continue

        if full_size == 0:
            continue

        ratio = price_size / full_size

        if ratio >= PRICE_SNAPSHOT_RATIO:
            snapshots.append(
                {
                    "source": price["source"],
                    "chain_id": price["chain_id"],
                    "store_id": price["store_id"],
                    "file_date": price["file_date"],
                    "price_size": price_size,
                    "price_full_size": full_size,
                    "ratio": ratio,
                    "price_filename": price["filename"],
                    "price_full_filename": full["filename"],
                }
            )

    return snapshots


def build_report(records) -> str:
    by_source = group_by_source(records)

    lines = []

    lines.append("FILE TRACKING REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Tracking file: {TRACKING_FILE}")
    lines.append(f"Total files: {len(records):,}")
    lines.append(f"Sources: {len(by_source):,}")
    lines.append("")

    # ------------------------------------------------------------------
    # Overall file types
    # ------------------------------------------------------------------

    lines.append("OVERALL FILE TYPES")
    lines.append("-" * 80)

    for file_type, count in file_type_counts(records).items():
        lines.append(f"{file_type:<15} {count:>8,}")

    lines.append("")

    # ------------------------------------------------------------------
    # Files per source
    # ------------------------------------------------------------------

    lines.append("FILES PER SOURCE")
    lines.append("-" * 80)

    for source, source_records in sorted(by_source.items()):
        lines.append(
            f"{source:<30} {len(source_records):>8,}"
        )

    lines.append("")

    # ------------------------------------------------------------------
    # File types per source
    # ------------------------------------------------------------------

    lines.append("FILE TYPES PER SOURCE")
    lines.append("-" * 80)

    for source, source_records in sorted(by_source.items()):
        lines.append("")
        lines.append(source)

        counts = file_type_counts(source_records)

        for file_type, count in counts.items():
            lines.append(
                f"  {file_type:<15} {count:>8,}"
            )

    lines.append("")

    # ------------------------------------------------------------------
    # Sources missing price / promo files
    # ------------------------------------------------------------------

    lines.append("SOURCES WITH MISSING FILE TYPES")
    lines.append("-" * 80)

    expected_types = {
        "Price",
        "PriceFull",
        "Promo",
        "PromoFull",
    }

    for source, source_records in sorted(by_source.items()):
        present = {
            record.get("file_type", "").strip()
            for record in source_records
        }

        missing = sorted(expected_types - present)

        if missing:
            lines.append(
                f"{source}: missing {', '.join(missing)}"
            )

    lines.append("")

    # ------------------------------------------------------------------
    # Tiny / zero-byte files
    # ------------------------------------------------------------------

    zero_files = get_zero_byte_files(records)
    tiny_files = get_tiny_files(records)

    lines.append("ZERO-BYTE FILES")
    lines.append("-" * 80)

    if not zero_files:
        lines.append("None")

    for record in zero_files:
        lines.append(
            f"{record['filename']} | "
            f"source={record['source']} | "
            f"type={record['file_type']} | "
            f"chain={record['chain_id']} | "
            f"store={record['store_id']}"
        )

    lines.append("")
    lines.append(f"Zero-byte files: {len(zero_files):,}")
    lines.append("")

    lines.append("TINY FILES (<= 1 BYTE)")
    lines.append("-" * 80)

    if not tiny_files:
        lines.append("None")

    for record in tiny_files:
        lines.append(
            f"{record['filename']} | "
            f"source={record['source']} | "
            f"type={record['file_type']} | "
            f"size={size_bytes(record)} B"
        )

    lines.append("")

    # ------------------------------------------------------------------
    # Biggest files
    # ------------------------------------------------------------------

    lines.append("BIGGEST FILES")
    lines.append("-" * 80)

    for record in get_biggest_files(records):
        lines.append(
            f"{format_size(size_bytes(record)):>10} | "
            f"{record['file_type']:<10} | "
            f"{record['source']:<25} | "
            f"chain={record['chain_id']} | "
            f"store={record['store_id']} | "
            f"{record['filename']}"
        )

    lines.append("")

    # ------------------------------------------------------------------
    # Price snapshot detection
    # ------------------------------------------------------------------

    snapshots = build_price_snapshot_report(records)

    lines.append("PRICE FILES THAT APPEAR TO BE SNAPSHOTS")
    lines.append("-" * 80)
    lines.append(
        f"Threshold: Price >= "
        f"{PRICE_SNAPSHOT_RATIO:.0%} of matching PriceFull"
    )
    lines.append("")

    if not snapshots:
        lines.append("None")

    for item in snapshots:
        lines.append(
            f"{item['source']:<25} | "
            f"chain={item['chain_id']} | "
            f"store={item['store_id']} | "
            f"date={item['file_date']} | "
            f"Price={format_size(item['price_size'])} | "
            f"PriceFull={format_size(item['price_full_size'])} | "
            f"ratio={item['ratio']:.1%}"
        )

    lines.append("")
    lines.append(
        f"Price snapshot candidates: {len(snapshots):,}"
    )
    lines.append("")

    # ------------------------------------------------------------------
    # Download status
    # ------------------------------------------------------------------

    not_downloaded = get_missing_downloads(records)

    lines.append("FILES NOT MARKED AS DOWNLOADED")
    lines.append("-" * 80)
    lines.append(
        f"Count: {len(not_downloaded):,}"
    )

    if not_downloaded:
        by_source_not_downloaded = defaultdict(int)

        for record in not_downloaded:
            by_source_not_downloaded[
                record.get("source", "").strip()
            ] += 1

        for source, count in sorted(
            by_source_not_downloaded.items()
        ):
            lines.append(
                f"{source:<30} {count:>8,}"
            )

    lines.append("")

    # ------------------------------------------------------------------
    # Chain IDs per source
    # ------------------------------------------------------------------

    lines.append("CHAIN IDS PER SOURCE")
    lines.append("-" * 80)

    for source, source_records in sorted(by_source.items()):
        chain_ids = sorted(
            {
                record.get("chain_id", "").strip()
                for record in source_records
                if record.get("chain_id")
            }
        )

        lines.append(
            f"{source}: {', '.join(chain_ids)}"
        )

    lines.append("")

    return "\n".join(lines)


def main():
    records = load_records()

    report = build_report(records)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        f.write(report)

    print(f"Written: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()