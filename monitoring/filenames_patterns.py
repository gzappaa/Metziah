import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

FILE_TRACKING = (
    BASE_DIR
    / "data"
    / "reference"
    / "file_tracking.csv"
)

REPORT_FILE = (
    BASE_DIR
    / "monitoring"
    / "data"
    / "filename_patterns.json"
)


# ---------------------------------------------------------------------------
# Structural components
# ---------------------------------------------------------------------------

CHAIN_ID_RE = re.compile(r"\d{13}")

DATE_RE = re.compile(r"\d{8}")

TIME_RE = re.compile(r"\d{6}")

NUMBER_RE = re.compile(r"\d+")

FILE_TYPE_RE = re.compile(
    r"^(PriceFull|Price|PromoFull|Promo|Stores)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Filename normalization
# ---------------------------------------------------------------------------

def normalize_filename(filename: str) -> str:
    """
    Convert a real filename into a structural representation.

    This is an inspection tool only.

    It does NOT validate filenames and does NOT use the production parser.

    The purpose is to discover all filename structures that actually occur
    in file_tracking.csv.
    """

    name = filename.strip()

    # ------------------------------------------------------------
    # Remove extension.
    # ------------------------------------------------------------

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

    structure = stem

    # ------------------------------------------------------------
    # File type
    # ------------------------------------------------------------

    match = FILE_TYPE_RE.match(structure)

    if match:
        structure = (
            "{file_type}"
            + structure[match.end():]
        )

    # ------------------------------------------------------------
    # Chain ID
    #
    # Do this before generic numbers.
    # ------------------------------------------------------------

    structure = CHAIN_ID_RE.sub(
        "{chain_id}",
        structure,
        count=1,
    )

    # ------------------------------------------------------------
    # Date/time
    #
    # Handle explicit separators first:
    #
    # 20260801-202020
    #
    # Then handle:
    #
    # 20260801202020
    # ------------------------------------------------------------

    structure = re.sub(
        r"(?<!\d)\d{8}[-_]\d{6}(?!\d)",
        "{date}-{time}",
        structure,
    )

    structure = re.sub(
        r"(?<!\d)\d{14}(?!\d)",
        "{datetime}",
        structure,
    )

    # Date by itself.
    structure = re.sub(
        r"(?<!\d)\d{8}(?!\d)",
        "{date}",
        structure,
    )

    # Time by itself.
    structure = re.sub(
        r"(?<!\d)\d{6}(?!\d)",
        "{time}",
        structure,
    )

    # ------------------------------------------------------------
    # Remaining numeric components.
    #
    # This captures things such as:
    #
    # 010
    # 001
    # 123
    # etc.
    # ------------------------------------------------------------

    structure = NUMBER_RE.sub(
        "{number}",
        structure,
    )

    return structure + extension


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_files() -> list[dict]:
    """
    Load all records from file_tracking.csv.

    Unlike the previous version, this does not restrict the scan to
    PriceFull. The goal is to discover filename structures across all
    tracked file types.
    """

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

            filename = (
                row.get("filename") or ""
            ).strip()

            if not filename:
                continue

            records.append(row)

    return records


# ---------------------------------------------------------------------------
# Structure discovery
# ---------------------------------------------------------------------------

def discover_structures(
    records: list[dict],
) -> dict[str, dict]:

    structures = {}

    for record in records:

        filename = record["filename"]

        structure = normalize_filename(
            filename
        )

        if structure not in structures:
            structures[structure] = {
                "count": 0,
                "examples": [],
                "file_types": Counter(),
                "sources": Counter(),
            }

        entry = structures[structure]

        entry["count"] += 1

        file_type = (
            record.get("file_type")
            or "<unknown>"
        )

        source = (
            record.get("source")
            or "<unknown>"
        )

        entry["file_types"][file_type] += 1
        entry["sources"][source] += 1

        # Keep real examples.
        if len(entry["examples"]) < 10:
            entry["examples"].append(filename)

    return structures


# ---------------------------------------------------------------------------
# JSON conversion
# ---------------------------------------------------------------------------

def build_output(
    records: list[dict],
    structures: dict[str, dict],
) -> dict:

    result = {
        "metadata": {
            "file_tracking": str(FILE_TRACKING),
            "total_records": len(records),
            "unique_structures": len(structures),
        },
        "structures": [],
    }

    for structure, entry in sorted(
        structures.items(),
        key=lambda item: (
            -item[1]["count"],
            item[0],
        ),
    ):

        result["structures"].append(
            {
                "structure": structure,
                "count": entry["count"],
                "file_types": dict(
                    entry["file_types"]
                ),
                "sources": dict(
                    entry["sources"]
                ),
                "examples": entry["examples"],
            }
        )

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():

    records = load_files()

    structures = discover_structures(
        records
    )

    output = build_output(
        records,
        structures,
    )

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Scanned {len(records)} records."
    )

    print(
        f"Found {len(structures)} unique filename structures."
    )

    print(
        "Report written to:"
    )

    print(
        REPORT_FILE
    )


if __name__ == "__main__":
    main()