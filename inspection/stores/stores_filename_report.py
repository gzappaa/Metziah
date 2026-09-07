from pathlib import Path
from collections import Counter, defaultdict
import re


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "feeds"
REPORT_FILE = (
    BASE_DIR
    / "inspection"
    / "reports"
    / "stores_filename_report.txt"
)


# Used ONLY to identify the variable parts of filenames so we can
# group filenames with the same structural pattern.
#
# This is an inspection tool, not the production Stores filename parser.
CHAIN_ID_RE = re.compile(r"\d{13}")
DATE_RE = re.compile(r"\d{8}")
DATETIME_RE = re.compile(r"\d{12,14}")
TIME_RE = re.compile(r"\d{3,6}")


def normalize_filename(filename: str) -> str:
    """
    Turn a real Stores filename into a structural representation.

    Examples:

        Stores5144744100002-000-20260905-000248.xml.gz

    becomes:

        Stores{CHAIN_ID}-000-{DATE}-{TIME}.xml.gz

        StoresFull7290058289400-000-202609050500.gz

    becomes:

        StoresFull{CHAIN_ID}-000-{DATETIME}.gz
    """

    name = filename

    # Remove the extension before inspecting numeric components.
    if name.lower().endswith(".xml.gz"):
        stem = name[:-7]
        extension = ".xml.gz"
    elif name.lower().endswith(".xml"):
        stem = name[:-4]
        extension = ".xml"
    elif name.lower().endswith(".gz"):
        stem = name[:-3]
        extension = ".gz"
    else:
        stem = name
        extension = ""

    # The chain ID is the first 13-digit number immediately after
    # Stores / StoresFull.
    match = re.match(
        r"^Stores(?:Full)?(\d{13})(.*)$",
        stem,
        re.IGNORECASE,
    )

    if not match:
        return f"UNRECOGNIZED:{filename}"

    structure = (
        stem[: match.start(1)]
        + "{CHAIN_ID}"
        + match.group(2)
    )

    # Replace timestamp components from longest to shortest.
    structure = re.sub(r"\d{14}", "{DATETIME14}", structure)
    structure = re.sub(r"\d{12}", "{DATETIME12}", structure)
    structure = re.sub(r"\d{8}", "{DATE}", structure)

    # Replace any remaining numeric components.
    structure = re.sub(r"\d+", "{NUMBER}", structure)

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


def scan_files() -> list[Path]:
    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"Data directory does not exist: {DATA_DIR}"
        )

    files = []

    for path in DATA_DIR.glob("**/stores/*"):
        if not path.is_file():
            continue

        if not path.name.lower().startswith("stores"):
            continue

        files.append(path)

    return files


def main():
    files = scan_files()

    structure_counts = Counter()
    structure_examples = defaultdict(list)
    structure_chains = defaultdict(Counter)
    extension_counts = Counter()

    for path in files:
        filename = path.name

        structure = normalize_filename(filename)
        extension = get_extension(filename)

        structure_counts[structure] += 1
        extension_counts[extension] += 1

        # Keep up to 5 real filename examples for each structure.
        if len(structure_examples[structure]) < 5:
            structure_examples[structure].append(filename)

        # The chain ID is taken from the feed directory.
        chain_id = path.parent.parent.name
        structure_chains[structure][chain_id] += 1

    lines = []

    lines.append("STORES FILENAME STRUCTURE REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Data directory: {DATA_DIR}")
    lines.append(f"Total Stores files: {len(files)}")
    lines.append("")

    # ------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------

    lines.append("EXTENSIONS")
    lines.append("-" * 80)

    for extension, count in extension_counts.most_common():
        percentage = (
            count / len(files) * 100
            if files
            else 0
        )

        lines.append(
            f"{extension:<12} {count:>8} ({percentage:6.2f}%)"
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
            count / len(files) * 100
            if files
            else 0
        )

        lines.append("")
        lines.append(f"{number}. {structure}")
        lines.append(
            f"   Count: {count} ({percentage:.2f}%)"
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
            lines.append(f"      {example}")

    lines.append("")

    # ------------------------------------------------------------
    # Duplicate exact filenames
    # ------------------------------------------------------------

    exact_counts = Counter(path.name for path in files)

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
    # Full file list
    # ------------------------------------------------------------

    lines.append("ALL STORES FILES")
    lines.append("-" * 80)

    for path in sorted(files):
        relative = path.relative_to(BASE_DIR)
        lines.append(str(relative))

    lines.append("")

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"Scanned {len(files)} Stores files.")
    print(
        f"Found {len(structure_counts)} filename structures."
    )
    print(f"Report written to:")
    print(REPORT_FILE)


if __name__ == "__main__":
    main()