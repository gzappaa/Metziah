from collections import Counter, defaultdict
from pathlib import Path
import csv
import re


BASE_DIR = Path(__file__).resolve().parents[2]

FILE_TRACKING = (
    BASE_DIR
    / "data"
    / "reference"
    / "file_tracking.csv"
)

REPORT_FILE = (
    BASE_DIR
    / "inspection"
    / "reports"
    / "pricefull_filename_report.txt"
)


CHAIN_ID_RE = re.compile(r"\d{13}")
DATETIME_RE = re.compile(r"\d{12,14}")
DATE_RE = re.compile(r"\d{8}")


def normalize_filename(filename: str) -> str:
    """
    Turn a real PriceFull filename into a structural representation.

    This is an inspection tool only. It does not determine whether a
    filename is valid according to the production filename parser.
    """

    name = filename

    # Remove extension before inspecting numeric components.
    lower = name.lower()

    if lower.endswith(".xml.gz"):
        stem = name[:-7]
        extension = ".xml.gz"
    elif lower.endswith(".xml"):
        stem = name[:-4]
        extension = ".xml"
    elif lower.endswith(".gz"):
        stem = name[:-3]
        extension = ".gz"
    else:
        stem = name
        extension = ""

    # Replace 13-digit chain IDs first.
    structure = CHAIN_ID_RE.sub(
        "{CHAIN_ID}",
        stem,
        count=1,
    )

    # Replace datetime components from longest to shortest.
    structure = re.sub(
        r"\d{14}",
        "{DATETIME14}",
        structure,
    )

    structure = re.sub(
        r"\d{12}",
        "{DATETIME12}",
        structure,
    )

    structure = re.sub(
        r"\d{8}",
        "{DATE}",
        structure,
    )

    # Replace remaining numeric components.
    structure = re.sub(
        r"\d+",
        "{NUMBER}",
        structure,
    )

    return structure + extension


def get_extension(filename: str) -> str:
    lower = filename.lower()

    if lower.endswith(".xml.gz"):
        return ".xml.gz"

    if lower.endswith(".xml"):
        return ".xml"

    if lower.endswith(".gz"):
        return ".gz"

    return Path(filename).suffix.lower() or "<no extension>"


def load_pricefull_files() -> list[dict]:
    if not FILE_TRACKING.exists():
        raise FileNotFoundError(
            f"File tracking file does not exist: {FILE_TRACKING}"
        )

    records = []

    with FILE_TRACKING.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            if row.get("file_type") != "PriceFull":
                continue

            filename = (
                row.get("filename") or ""
            ).strip()

            if not filename:
                continue

            records.append(row)

    return records


def main():

    records = load_pricefull_files()

    structure_counts = Counter()
    structure_examples = defaultdict(list)
    structure_sources = defaultdict(Counter)
    structure_chains = defaultdict(Counter)
    structure_dates = defaultdict(Counter)
    extension_counts = Counter()

    for record in records:

        filename = record["filename"]
        structure = normalize_filename(filename)
        extension = get_extension(filename)

        structure_counts[structure] += 1
        extension_counts[extension] += 1

        source = record.get("source") or "<unknown>"
        chain_id = record.get("chain_id") or "<unknown>"
        file_date = record.get("file_date") or "<unknown>"

        structure_sources[structure][source] += 1
        structure_chains[structure][chain_id] += 1
        structure_dates[structure][file_date] += 1

        # Keep up to 5 real filename examples.
        if len(structure_examples[structure]) < 5:
            structure_examples[structure].append(filename)

    lines = []

    lines.append("PRICEFULL FILENAME STRUCTURE REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(
        f"File tracking: {FILE_TRACKING}"
    )
    lines.append(
        f"Total PriceFull records: {len(records)}"
    )
    lines.append("")

    # ------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------

    lines.append("EXTENSIONS")
    lines.append("-" * 80)

    for extension, count in extension_counts.most_common():

        percentage = (
            count / len(records) * 100
            if records
            else 0
        )

        lines.append(
            f"{extension:<12} "
            f"{count:>8} "
            f"({percentage:6.2f}%)"
        )

    lines.append("")

    # ------------------------------------------------------------
    # Filename structures
    # ------------------------------------------------------------

    lines.append("FILENAME STRUCTURES")
    lines.append("-" * 80)

    for number, (structure, count) in enumerate(
        structure_counts.most_common(),
        start=1,
    ):

        percentage = (
            count / len(records) * 100
            if records
            else 0
        )

        lines.append("")
        lines.append(
            f"{number}. {structure}"
        )
        lines.append(
            f"   Count: {count} "
            f"({percentage:.2f}%)"
        )

        lines.append("   Sources:")

        for source, source_count in (
            structure_sources[structure].most_common()
        ):
            lines.append(
                f"      {source}: {source_count}"
            )

        lines.append("   Chains:")

        for chain_id, chain_count in (
            structure_chains[structure].most_common()
        ):
            lines.append(
                f"      {chain_id}: {chain_count}"
            )

        lines.append("   Examples:")

        for example in structure_examples[structure]:
            lines.append(
                f"      {example}"
            )

    lines.append("")

    # ------------------------------------------------------------
    # Exact duplicate filenames
    # ------------------------------------------------------------

    exact_counts = Counter(
        record["filename"]
        for record in records
    )

    duplicates = {
        filename: count
        for filename, count in exact_counts.items()
        if count > 1
    }

    lines.append("DUPLICATE FILENAMES")
    lines.append("-" * 80)

    if duplicates:

        for filename, count in sorted(
            duplicates.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(
                f"{count:>5}  {filename}"
            )

    else:
        lines.append("None")

    lines.append("")

    # ------------------------------------------------------------
    # File date coverage
    # ------------------------------------------------------------

    lines.append("FILE DATE RANGE")
    lines.append("-" * 80)

    dates = [
        record["file_date"]
        for record in records
        if record.get("file_date")
    ]

    if dates:
        lines.append(
            f"Earliest: {min(dates)}"
        )
        lines.append(
            f"Latest:   {max(dates)}"
        )
    else:
        lines.append("None")

    lines.append("")

    # ------------------------------------------------------------
    # Full PriceFull file list
    # ------------------------------------------------------------

    lines.append("ALL PRICEFULL FILES")
    lines.append("-" * 80)

    for record in sorted(
        records,
        key=lambda row: (
            row.get("file_date") or "",
            row.get("source") or "",
            row.get("chain_id") or "",
            row.get("store_id") or "",
            row.get("filename") or "",
        ),
    ):

        lines.append(
            f"{record.get('filename', '')} | "
            f"{record.get('source', '')} | "
            f"{record.get('chain_id', '')} | "
            f"{record.get('sub_chain_id', '')} | "
            f"{record.get('store_id', '')} | "
            f"{record.get('file_date', '')}"
        )

    lines.append("")

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(
        f"Scanned {len(records)} PriceFull records."
    )
    print(
        f"Found {len(structure_counts)} filename structures."
    )
    print("Report written to:")
    print(REPORT_FILE)


if __name__ == "__main__":
    main()