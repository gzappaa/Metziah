import csv
import gzip
import json
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET


BASE_DIR = Path(__file__).resolve().parents[2]

FEEDS_DIR = BASE_DIR / "data" / "feeds"
REFERENCE_DIR = BASE_DIR / "data" / "reference"

CHAINS_FILE = REFERENCE_DIR / "chains.json"
EXTRA_CHAINS_FILE = REFERENCE_DIR / "extra_chains.json"

REPORT_FILE = BASE_DIR / "inspection" / "reports" / "items_report.txt"


def load_chain_names():
    """
    Returns:
        {
            chain_id: normalized English name
        }

    chains.json and extra_chains.json are merged.
    extra_chains.json takes precedence if the same chain exists.
    """
    chains = {}

    for path in (CHAINS_FILE, EXTRA_CHAINS_FILE):
        if not path.exists():
            continue

        with path.open(encoding="utf-8") as f:
            data = json.load(f)

        for chain_id, metadata in data.items():
            if not isinstance(metadata, dict):
                continue

            name = metadata.get("name_en_normalized")

            if name:
                chains[str(chain_id)] = name

    return chains


def get_latest_pricefull_files():
    """
    Walk:

        data/feeds/{chain_id}/{store_id}/pricesfull/

    and return the newest physical file for every store.

    No filename parsing is performed.
    The filesystem modification time is used to determine
    the latest downloaded file.
    """
    latest_files = []

    if not FEEDS_DIR.exists():
        return latest_files

    for chain_dir in FEEDS_DIR.iterdir():
        if not chain_dir.is_dir():
            continue

        chain_id = chain_dir.name

        for store_dir in chain_dir.iterdir():
            if not store_dir.is_dir():
                continue

            store_id = store_dir.name
            pricesfull_dir = store_dir / "pricesfull"

            if not pricesfull_dir.is_dir():
                continue

            files = [
                path
                for path in pricesfull_dir.iterdir()
                if path.is_file()
            ]

            if not files:
                continue

            latest = max(
                files,
                key=lambda path: path.stat().st_mtime,
            )

            latest_files.append(
                (
                    chain_id,
                    store_id,
                    latest,
                )
            )

    return latest_files


def iter_xml_from_path(path):
    """
    Yield XML events from:

        .xml
        .gz
        .xml.gz
        .zip
        extensionless / unknown files

    Filename extensions are treated as hints, not guaranteed truth.

    Fallbacks:
        GZIP -> ZIP
        unknown -> GZIP -> ZIP -> plain XML

    For ZIP files, every XML-like member is inspected.
    """

    suffixes = [suffix.lower() for suffix in path.suffixes]

    # ------------------------------------------------------------
    # ZIP
    # ------------------------------------------------------------

    def iter_zip():
        with zipfile.ZipFile(path) as zf:
            members = [
                name
                for name in zf.namelist()
                if not name.endswith("/")
                and (
                    name.lower().endswith(".xml")
                    or name.lower().endswith(".xml.gz")
                )
            ]

            if not members:
                raise ValueError("ZIP contains no XML files")

            for member in members:
                with zf.open(member) as raw:
                    if member.lower().endswith(".gz"):
                        with gzip.GzipFile(fileobj=raw) as xml_file:
                            yield from ET.iterparse(
                                xml_file,
                                events=("end",),
                            )
                    else:
                        yield from ET.iterparse(
                            raw,
                            events=("end",),
                        )

    # ------------------------------------------------------------
    # ZIP by extension
    # ------------------------------------------------------------

    if ".zip" in suffixes:
        yield from iter_zip()
        return

    # ------------------------------------------------------------
    # GZIP by extension
    # ------------------------------------------------------------

    if ".gz" in suffixes:
        try:
            with gzip.open(path, "rb") as f:
                yield from ET.iterparse(
                    f,
                    events=("end",),
                )

            return

        except (
            gzip.BadGzipFile,
            OSError,
            EOFError,
            ET.ParseError,
        ):
            # Some files are incorrectly named .gz but are
            # actually ZIP archives.
            yield from iter_zip()
            return

    # ------------------------------------------------------------
    # XML by extension
    # ------------------------------------------------------------

    if ".xml" in suffixes:
        with path.open("rb") as f:
            yield from ET.iterparse(
                f,
                events=("end",),
            )

        return

    # ------------------------------------------------------------
    # Unknown / extensionless
    #
    # Try:
    #     GZIP -> ZIP -> plain XML
    # ------------------------------------------------------------

    try:
        with gzip.open(path, "rb") as f:
            yield from ET.iterparse(
                f,
                events=("end",),
            )

        return

    except (
        gzip.BadGzipFile,
        OSError,
        EOFError,
        ET.ParseError,
    ):
        pass

    try:
        yield from iter_zip()
        return

    except zipfile.BadZipFile:
        pass

    # Final fallback: plain XML
    with path.open("rb") as f:
        yield from ET.iterparse(
            f,
            events=("end",),
        )


def local_name(tag):
    """
    Handles XML namespaces:

        {namespace}ItemCode -> ItemCode
    """
    if not isinstance(tag, str):
        return ""

    return tag.rsplit("}", 1)[-1].lower()


def extract_item_codes(path):
    """
    Extract all unique ItemCode values from an XML feed.
    """
    item_codes = set()

    for _, element in iter_xml_from_path(path):
        if local_name(element.tag) == "itemcode":
            if element.text:
                item_code = element.text.strip()

                if item_code:
                    item_codes.add(item_code)

        # Always clear elements to keep memory usage low.
        element.clear()

    return item_codes


def gtin_checksum_valid(code):
    """
    Validate GTIN/EAN/UPC check digit.

    Supported lengths:
        8   EAN-8
        12  UPC-A / GTIN-12
        13  EAN-13 / GTIN-13
        14  GTIN-14
    """
    if not code.isdigit():
        return False

    if len(code) not in {8, 12, 13, 14}:
        return False

    digits = [int(x) for x in code]

    check_digit = digits[-1]
    body = digits[:-1]

    total = 0
    weight = 3

    for digit in reversed(body):
        total += digit * weight
        weight = 1 if weight == 3 else 3

    calculated = (10 - (total % 10)) % 10

    return calculated == check_digit


def code_category(code):
    """
    Human-readable classification for the report.
    """
    if not code.isdigit():
        return "non_numeric"

    if len(code) in {8, 12, 13, 14}:
        if gtin_checksum_valid(code):
            return "valid_gtin"

        return "invalid_gtin_checksum"

    return "other_numeric"


def format_percentage(value):
    return f"{value:.2f}%"


def main():
    chain_names = load_chain_names()

    # chain_id -> set of unique ItemCodes
    chain_items = {}

    # Files that failed to open/parse.
    unreadable_files = []

    # Statistics about files.
    chain_files = Counter()
    chain_failed_files = Counter()

    latest_files = get_latest_pricefull_files()

    print(f"Latest PriceFull files found: {len(latest_files)}")

    for chain_id, store_id, path in latest_files:
        chain_items.setdefault(chain_id, set())

        try:
            item_codes = extract_item_codes(path)

            chain_items[chain_id].update(item_codes)
            chain_files[chain_id] += 1

        except Exception as exc:
            chain_failed_files[chain_id] += 1

            unreadable_files.append(
                {
                    "chain": chain_id,
                    "store": store_id,
                    "path": str(path.relative_to(BASE_DIR)),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    # ------------------------------------------------------------
    # Global statistics
    # ------------------------------------------------------------

    total_items = sum(
        len(items)
        for items in chain_items.values()
    )

    global_length_counts = Counter()
    global_categories = Counter()

    for items in chain_items.values():
        for code in items:
            global_length_counts[len(code)] += 1
            global_categories[code_category(code)] += 1

    recognized_gtin_total = sum(
        global_categories[key]
        for key in (
            "valid_gtin",
            "invalid_gtin_checksum",
        )
    )

    valid_gtin = global_categories["valid_gtin"]

    if total_items:
        valid_ratio_all = (
            valid_gtin / total_items * 100
        )
    else:
        valid_ratio_all = 0

    if recognized_gtin_total:
        valid_ratio_recognized = (
            valid_gtin / recognized_gtin_total * 100
        )
    else:
        valid_ratio_recognized = 0

    # ------------------------------------------------------------
    # Report
    # ------------------------------------------------------------

    lines = []

    lines.append(
        "DISCARD 4 — PRICEFULL ITEMCODE INSPECTION"
    )
    lines.append("=" * 60)
    lines.append("")
    lines.append(
        f"Latest PriceFull files inspected: "
        f"{len(latest_files):,}"
    )
    lines.append(
        f"Chains found: {len(chain_items):,}"
    )
    lines.append(
        f"Total unique ItemCodes: {total_items:,}"
    )
    lines.append("")

    lines.append("GENERAL SUMMARY")
    lines.append("-" * 60)

    if global_length_counts:
        lines.append("ItemCode lengths:")

        for length, count in sorted(
            global_length_counts.items()
        ):
            percentage = (
                count / total_items * 100
            )

            lines.append(
                f"  {length:>2} digits: "
                f"{count:>10,} "
                f"({percentage:>6.2f}%)"
            )
    else:
        lines.append("ItemCode lengths: none")

    lines.append("")
    lines.append("Code validation:")

    lines.append(
        f"  Valid GTIN/EAN/UPC checksum: "
        f"{global_categories['valid_gtin']:,} "
        f"({format_percentage(valid_ratio_all)} "
        f"of all unique codes)"
    )

    lines.append(
        f"  Invalid checksum: "
        f"{global_categories['invalid_gtin_checksum']:,}"
    )

    lines.append(
        f"  Other numeric lengths: "
        f"{global_categories['other_numeric']:,}"
    )

    lines.append(
        f"  Non-numeric: "
        f"{global_categories['non_numeric']:,}"
    )

    lines.append("")
    lines.append(
        "Valid ratio among 8/12/13/14-digit codes: "
        f"{format_percentage(valid_ratio_recognized)}"
    )

    # ------------------------------------------------------------
    # Per-chain summary
    # ------------------------------------------------------------

    lines.append("")
    lines.append("CHAIN SUMMARY")
    lines.append("=" * 60)

    sorted_chains = sorted(
        chain_items.items(),
        key=lambda item: (
            chain_names.get(
                item[0],
                "",
            ).lower(),
            item[0],
        ),
    )

    for chain_id, items in sorted_chains:
        name = chain_names.get(
            chain_id,
            "UNKNOWN",
        )

        length_counts = Counter(
            len(code)
            for code in items
        )

        categories = Counter(
            code_category(code)
            for code in items
        )

        chain_total = len(items)
        chain_valid = categories["valid_gtin"]

        chain_valid_ratio = (
            chain_valid / chain_total * 100
            if chain_total
            else 0
        )

        lines.append("")
        lines.append(
            f"{name} [{chain_id}]"
        )
        lines.append("-" * 60)

        lines.append(
            f"Files: {chain_files[chain_id]:,}"
        )

        lines.append(
            f"Unreadable files: "
            f"{chain_failed_files[chain_id]:,}"
        )

        lines.append(
            f"Unique items: {chain_total:,}"
        )

        if length_counts:
            lines.append("ItemCode lengths:")

            for length, count in sorted(
                length_counts.items()
            ):
                percentage = (
                    count / chain_total * 100
                )

                lines.append(
                    f"  {length:>2} digits: "
                    f"{count:>10,} "
                    f"({percentage:>6.2f}%)"
                )
        else:
            lines.append(
                "ItemCode lengths: none"
            )

        lines.append("Code validation:")

        lines.append(
            f"  Valid GTIN/EAN/UPC: "
            f"{chain_valid:,} "
            f"({format_percentage(chain_valid_ratio)})"
        )

        lines.append(
            f"  Invalid checksum: "
            f"{categories['invalid_gtin_checksum']:,}"
        )

        lines.append(
            f"  Other numeric lengths: "
            f"{categories['other_numeric']:,}"
        )

        lines.append(
            f"  Non-numeric: "
            f"{categories['non_numeric']:,}"
        )

    # ------------------------------------------------------------
    # Unreadable files
    # ------------------------------------------------------------

    lines.append("")
    lines.append("=" * 60)
    lines.append("UNREADABLE FILES")
    lines.append("=" * 60)

    if unreadable_files:
        lines.append(
            f"Total unreadable files: "
            f"{len(unreadable_files):,}"
        )

        for entry in unreadable_files:
            lines.append("")
            lines.append(
                f"Chain: {entry['chain']}"
            )
            lines.append(
                f"Store: {entry['store']}"
            )
            lines.append(
                f"File:  {entry['path']}"
            )
            lines.append(
                f"Error: {entry['error']}"
            )
    else:
        lines.append("None.")

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(
        f"Report written to: {REPORT_FILE}"
    )


if __name__ == "__main__":
    main()