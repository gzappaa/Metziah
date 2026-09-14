# inspection/files/all_files_report.py

import csv
import gzip
import io
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from xml.etree import ElementTree


"""
RUN IT AFTER DOWNLOADING EVERYFILE AVAILABLE in downloaders/

What this script does:

- Scans every file under data/feeds/{chain}/{store}/{prices,pricesfull,promos,promosfull}.
- Does not assume the extension tells us the real format.
- Actually tries to read every file.
- Detects and recursively opens gzip, zip, nested zip, XML, text, and unknown binary content.
- Reports exactly which files fail and why.
- Keeps nested archives in memory; it does not extract anything into the feed directories.
- Groups filenames into their structural patterns and shows examples.
- Checks today's prices vs pricesfull and promos vs promofull.
- Flags pairs where the normal file is at least 80% of the Full file size, since those are worth investigating as possible snapshots rather than deltas.
- Writes the detailed report to placeholder_inspection.txt.
- Writes individual failures to placeholder_failures.csv.

The main goal is to establish what formats and packaging patterns actually exist
in the feeds, and whether there are any files that we won't be able to reliably
open later during ingestion.
"""

BASE_DIR = Path(__file__).resolve().parents[2]

FEEDS_DIR = BASE_DIR / "data" / "feeds"
OUTPUT_FILE = BASE_DIR / "inspection" / "reports" / "files_report.txt"
FAILURES_FILE = BASE_DIR / "inspection" / "reports" / "files_failures.csv"

FEED_TYPES = {
    "prices",
    "pricesfull",
    "promos",
    "promosfull",
}

SIZE_THRESHOLD = 0.80
MAX_RECURSION = 8
XML_SAMPLE_SIZE = 64 * 1024


# ============================================================
# Filename structure inspection
# ============================================================

def classify_filename(filename):
    """
    Discover the structural shape of a filename.

    This is intentionally structural only. It does not try to
    determine whether a numeric field is actually a store,
    subchain, etc.
    """
    name = filename

    # Handle compound extensions first.
    if name.endswith(".xml.gz"):
        name = name[:-7]
        extension = ".xml.gz"
    elif name.endswith(".gz"):
        name = name[:-3]
        extension = ".gz"
    elif "." in name:
        name, ext = name.rsplit(".", 1)
        extension = "." + ext
    else:
        extension = ""

    match = re.match(
        r"^(?P<type>[A-Za-z]+)(?P<body>.*)$",
        name,
    )

    if not match:
        return None

    body = match.group("body")
    blocks = body.split("-")

    if not blocks or not all(block.isdigit() for block in blocks):
        return None

    # First numeric block is the chain ID.
    if len(blocks[0]) < 10:
        return None

    result = ["{TYPE}", "{CHAIN}"]
    remaining = blocks[1:]

    if not remaining:
        return None

    def classify_tail(block):
        length = len(block)

        if length in (10, 12, 14):
            return "{DATETIME}"

        if length == 8:
            return "{DATE}"

        if length in (2, 4, 6):
            return "{TIME}"

        return None

    i = 0

    while i < len(remaining):
        block = remaining[i]
        semantic = classify_tail(block)

        if semantic == "{DATETIME}":
            result.append(semantic)
            i += 1
            break

        if semantic == "{DATE}":
            result.append("{DATE}")
            i += 1

            if i < len(remaining):
                next_block = remaining[i]

                if len(next_block) in (2, 4, 6):
                    result.append("{TIME}")
                    i += 1

            break

        # A block containing date+time/store without separators.
        if i == len(remaining) - 1:
            compound = split_compound_block(block)

            if compound:
                result.extend(compound)
                i += 1
                break

        if len(result) == 2:
            result.append("{SUBCHAIN_OR_STORE}")
        else:
            result.append("{STORE}")

        i += 1

    while i < len(remaining):
        result.append("{FIELD}")
        i += 1

    return "-".join(result) + extension


def split_compound_block(block):
    if re.search(r"\d{8}\d{6}$", block):
        return ["{STORE}{DATETIME}"]

    if re.search(r"\d{8}\d{4}$", block):
        return ["{STORE}{DATETIME}"]

    if re.search(r"\d{8}\d{2}$", block):
        return ["{STORE}{DATETIME}"]

    if re.search(r"\d{8}$", block):
        return ["{STORE}{DATE}"]

    return None


# ============================================================
# File format detection
# ============================================================

def is_gzip(data):
    return len(data) >= 2 and data[:2] == b"\x1f\x8b"


def is_zip(data):
    return len(data) >= 4 and data[:4] == b"PK\x03\x04"


def looks_like_xml(data):
    if not data:
        return False

    sample = data[:XML_SAMPLE_SIZE]

    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]

    sample = sample.lstrip()

    return (
        sample.startswith(b"<?xml")
        or sample.startswith(b"<")
    )


def is_probably_text(data):
    if not data:
        return True

    sample = data[:XML_SAMPLE_SIZE]

    if b"\x00" in sample:
        return False

    printable = sum(
        1
        for byte in sample
        if byte in (9, 10, 13) or 32 <= byte <= 126
    )

    return printable / len(sample) > 0.85


# ============================================================
# XML inspection
# ============================================================

def inspect_xml_bytes(data):
    """
    Lightweight XML check.

    Does not parse the XML tree. Only checks that the content
    is non-empty and begins like XML.
    """
    if not data:
        return {
            "success": False,
            "root": "",
            "error": "Empty XML content",
        }

    sample = data[:XML_SAMPLE_SIZE]

    # Remove UTF-8 BOM if present.
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]

    # Ignore whitespace before the XML content.
    sample = sample.lstrip()

    if not (
        sample.startswith(b"<?xml")
        or sample.startswith(b"<")
    ):
        return {
            "success": False,
            "root": "",
            "error": "Content does not look like XML",
        }

    return {
        "success": True,
        "root": "",
        "error": "",
    }


# ============================================================
# Recursive container inspection
# ============================================================

def inspect_bytes(data, level=0, label="file"):
    """
    Recursively inspect compressed/container data.

    Examples handled:

        gzip -> XML
        gzip -> ZIP -> XML
        gzip -> ZIP -> ZIP -> XML
        ZIP -> XML
        ZIP -> gzip -> XML
        etc.

    Nothing is extracted to disk.
    """
    if level > MAX_RECURSION:
        return {
            "success": False,
            "format": "recursion_limit",
            "path": label,
            "details": "Maximum recursion depth reached",
            "children": [],
        }

    # --------------------------------------------------------
    # GZIP
    # --------------------------------------------------------

    if is_gzip(data):
        try:
            decompressed = gzip.decompress(data)

        except Exception as exc:
            return {
                "success": False,
                "format": "gzip",
                "path": label,
                "details": f"{type(exc).__name__}: {exc}",
                "children": [],
            }

        child = inspect_bytes(
            decompressed,
            level=level + 1,
            label=f"{label} -> gzip",
        )

        return {
            "success": child["success"],
            "format": "gzip",
            "path": label,
            "details": f"decompressed: {len(decompressed):,} bytes",
            "children": [child],
        }

    # --------------------------------------------------------
    # ZIP
    # --------------------------------------------------------

    if is_zip(data):
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))

            members = archive.infolist()

            if not members:
                return {
                    "success": False,
                    "format": "zip",
                    "path": label,
                    "details": "Empty ZIP archive",
                    "children": [],
                }

            children = []
            overall_success = True

            for member in members:
                if member.is_dir():
                    continue

                try:
                    member_data = archive.read(member)

                except Exception as exc:
                    child = {
                        "success": False,
                        "format": "zip-member",
                        "path": f"{label} -> {member.filename}",
                        "details": (
                            f"{type(exc).__name__}: {exc}"
                        ),
                        "children": [],
                    }

                    children.append(child)
                    overall_success = False
                    continue

                child = inspect_bytes(
                    member_data,
                    level=level + 1,
                    label=f"{label} -> {member.filename}",
                )

                children.append(child)

                if not child["success"]:
                    overall_success = False

            return {
                "success": overall_success,
                "format": "zip",
                "path": label,
                "details": (
                    f"{len(members)} archive member(s)"
                ),
                "children": children,
            }

        except Exception as exc:
            return {
                "success": False,
                "format": "zip",
                "path": label,
                "details": f"{type(exc).__name__}: {exc}",
                "children": [],
            }

    # --------------------------------------------------------
    # XML
    # --------------------------------------------------------

    if looks_like_xml(data):
        result = inspect_xml_bytes(data)

        if result["success"]:
            return {
                "success": True,
                "format": "xml",
                "path": label,
                "details": f"root={result['root']}",
                "children": [],
            }

        return {
            "success": False,
            "format": "xml",
            "path": label,
            "details": result["error"],
            "children": [],
        }

    # --------------------------------------------------------
    # Plain text / unknown
    # --------------------------------------------------------

    if is_probably_text(data):
        return {
            "success": True,
            "format": "text",
            "path": label,
            "details": "Readable text, not XML",
            "children": [],
        }

    return {
        "success": False,
        "format": "unknown-binary",
        "path": label,
        "details": "Unknown binary format",
        "children": [],
    }


# ============================================================
# File inspection
# ============================================================

def inspect_file(path):
    try:
        data = path.read_bytes()

    except Exception as exc:
        return {
            "success": False,
            "size": 0,
            "format": "unreadable",
            "details": f"{type(exc).__name__}: {exc}",
            "tree": None,
        }

    result = inspect_bytes(
        data,
        label=path.name,
    )

    return {
        "success": result["success"],
        "size": len(data),
        "format": result["format"],
        "details": result["details"],
        "tree": result,
    }


# ============================================================
# Tree formatting
# ============================================================

def format_tree(node, indent=2):
    if node is None:
        return []

    marker = "OK" if node["success"] else "FAIL"

    lines = [
        f"{' ' * indent}[{marker}] "
        f"{node['format']}: {node['details']}"
    ]

    for child in node.get("children", []):
        lines.extend(
            format_tree(
                child,
                indent=indent + 2,
            )
        )

    return lines


def collect_failures(node, failures):
    if node is None:
        return

    if not node["success"]:
        failures.append(
            {
                "path": node["path"],
                "format": node["format"],
                "details": node["details"],
            }
        )

    for child in node.get("children", []):
        collect_failures(child, failures)


def collect_formats(node, counter):
    if node is None:
        return

    counter[node["format"]] += 1

    for child in node.get("children", []):
        collect_formats(child, counter)


# ============================================================
# Feed discovery
# ============================================================

def discover_files():
    """
    Discover files under:

        data/feeds/{chain}/{store}/{feed_type}/...

    We don't assume anything about the filename or extension.
    """
    files = []

    if not FEEDS_DIR.exists():
        return files

    for chain_dir in sorted(FEEDS_DIR.iterdir()):
        if not chain_dir.is_dir():
            continue

        for store_dir in sorted(chain_dir.iterdir()):
            if not store_dir.is_dir():
                continue

            for feed_type in sorted(FEED_TYPES):
                feed_dir = store_dir / feed_type

                if not feed_dir.is_dir():
                    continue

                for path in feed_dir.rglob("*"):
                    if path.is_file():
                        files.append(
                            {
                                "path": path,
                                "chain": chain_dir.name,
                                "store": store_dir.name,
                                "feed_type": feed_type,
                            }
                        )

    return files


# ============================================================
# Today's Full vs normal comparison
# ============================================================

def extract_date_from_filename(filename):
    """
    Look for YYYYMMDD anywhere in the filename.

    This is intentionally independent of filename structure.
    """
    matches = re.findall(r"(20\d{6})", filename)

    for value in matches:
        try:
            parsed = date(
                int(value[:4]),
                int(value[4:6]),
                int(value[6:8]),
            )

            return parsed

        except ValueError:
            continue

    return None


def get_today_files(files):
    today = date.today()

    return [
        item
        for item in files
        if extract_date_from_filename(
            item["path"].name
        ) == today
    ]


def build_size_comparisons(files):
    """
    Pair today's Full and normal files by chain/store.

    If multiple files exist for the same chain/store/type,
    all combinations are reported.
    """
    today_files = get_today_files(files)

    grouped = defaultdict(
        lambda: defaultdict(list)
    )

    for item in today_files:
        key = (
            item["chain"],
            item["store"],
        )

        grouped[key][item["feed_type"]].append(item)

    comparisons = []

    for (chain, store), types in sorted(grouped.items()):
        for full_type, normal_type in (
            ("pricesfull", "prices"),
            ("promosfull", "promos"),
        ):
            full_files = types.get(full_type, [])
            normal_files = types.get(normal_type, [])

            for full in full_files:
                for normal in normal_files:
                    full_size = full["path"].stat().st_size
                    normal_size = normal["path"].stat().st_size

                    if full_size == 0:
                        ratio = None
                    else:
                        ratio = normal_size / full_size

                    comparisons.append(
                        {
                            "chain": chain,
                            "store": store,
                            "full_type": full_type,
                            "normal_type": normal_type,
                            "full": full["path"],
                            "normal": normal["path"],
                            "full_size": full_size,
                            "normal_size": normal_size,
                            "ratio": ratio,
                            "suspicious": (
                                ratio is not None
                                and ratio >= SIZE_THRESHOLD
                            ),
                        }
                    )

    return comparisons


# ============================================================
# Main
# ============================================================

def main():
    print(f"Feeds directory: {FEEDS_DIR}")
    print()

    files = discover_files()

    print(f"Files discovered: {len(files):,}")

    if not files:
        print("No feed files found.")
        return

    structures = defaultdict(list)
    structure_unparsed = []

    format_counter = Counter()
    failures = []

    by_feed_type = Counter()
    by_chain = Counter()
    by_store = defaultdict(set)

    file_results = []

    # --------------------------------------------------------
    # Inspect every file
    # --------------------------------------------------------

    for number, item in enumerate(files, start=1):
        path = item["path"]

        by_feed_type[item["feed_type"]] += 1
        by_chain[item["chain"]] += 1
        by_store[item["chain"]].add(item["store"])

        structure = classify_filename(path.name)

        if structure:
            structures[structure].append(path.name)
        else:
            structure_unparsed.append(path.name)

        result = inspect_file(path)

        collect_formats(
            result["tree"],
            format_counter,
        )

        if not result["success"]:
            file_failures = []

            collect_failures(
                result["tree"],
                file_failures,
            )

            if not file_failures:
                file_failures = [
                    {
                        "path": path.name,
                        "format": result["format"],
                        "details": result["details"],
                    }
                ]

            for failure in file_failures:
                failures.append(
                    {
                        "chain": item["chain"],
                        "store": item["store"],
                        "feed_type": item["feed_type"],
                        "file": str(path),
                        "failure_path": failure["path"],
                        "format": failure["format"],
                        "details": failure["details"],
                    }
                )

        file_results.append(
            {
                **item,
                **result,
            }
        )

        if number % 500 == 0:
            print(
                f"  inspected {number:,}/{len(files):,}"
            )

    # --------------------------------------------------------
    # Size comparison
    # --------------------------------------------------------

    comparisons = build_size_comparisons(files)

    suspicious = [
        comparison
        for comparison in comparisons
        if comparison["suspicious"]
    ]

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

    sorted_structures = sorted(
        structures.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as output:

        output.write(
            "============================================================\n"
        )
        output.write(
            "FEED FILE INSPECTION\n"
        )
        output.write(
            "============================================================\n\n"
        )

        output.write(
            f"Feeds directory: {FEEDS_DIR}\n"
        )
        output.write(
            f"Files discovered: {len(files):,}\n"
        )
        output.write(
            f"Files successfully opened: "
            f"{len(files) - len({f['file'] for f in failures}):,}\n"
        )
        output.write(
            f"Files with failures: "
            f"{len({f['file'] for f in failures}):,}\n\n"
        )

        # ----------------------------------------------------
        # Chains / stores
        # ----------------------------------------------------

        output.write(
            "CHAINS / STORES\n"
        )
        output.write(
            "------------------------------------------------------------\n"
        )
        output.write(
            f"Chains: {len(by_chain):,}\n"
        )
        output.write(
            f"Stores: "
            f"{sum(len(stores) for stores in by_store.values()):,}\n\n"
        )

        for chain, count in sorted(by_chain.items()):
            output.write(
                f"{chain}: "
                f"{len(by_store[chain]):,} stores, "
                f"{count:,} files\n"
            )

        output.write("\n")

        # ----------------------------------------------------
        # Feed types
        # ----------------------------------------------------

        output.write(
            "FEED TYPES\n"
        )
        output.write(
            "------------------------------------------------------------\n"
        )

        for feed_type, count in sorted(
            by_feed_type.items()
        ):
            output.write(
                f"{feed_type}: {count:,}\n"
            )

        output.write("\n")

        # ----------------------------------------------------
        # Filename structures
        # ----------------------------------------------------

        output.write(
            "FILENAME STRUCTURES\n"
        )
        output.write(
            "------------------------------------------------------------\n"
        )

        output.write(
            f"Unique structures: "
            f"{len(sorted_structures):,}\n\n"
        )

        for number, (structure, filenames) in enumerate(
            sorted_structures,
            start=1,
        ):
            output.write(
                f"{number}. {structure}\n"
            )
            output.write(
                f"   Count: {len(filenames):,}\n"
            )
            output.write(
                "   Examples:\n"
            )

            for example in filenames[:5]:
                output.write(
                    f"      {example}\n"
                )

            output.write("\n")

        if structure_unparsed:
            output.write(
                "UNPARSED FILENAME STRUCTURES\n"
            )
            output.write(
                "------------------------------------------------------------\n"
            )

            for filename in sorted(
                set(structure_unparsed)
            ):
                output.write(
                    f"{filename}\n"
                )

            output.write("\n")

        # ----------------------------------------------------
        # Formats
        # ----------------------------------------------------

        output.write(
            "CONTENT / FORMAT DETECTION\n"
        )
        output.write(
            "------------------------------------------------------------\n"
        )

        for fmt, count in format_counter.most_common():
            output.write(
                f"{fmt}: {count:,}\n"
            )

        output.write("\n")

        # ----------------------------------------------------
        # Full vs normal
        # ----------------------------------------------------

        output.write(
            "TODAY FULL VS NORMAL SIZE CHECK\n"
        )
        output.write(
            "------------------------------------------------------------\n"
        )

        output.write(
            f"Today's date: {date.today().isoformat()}\n"
        )
        output.write(
            f"Pairs checked: {len(comparisons):,}\n"
        )
        output.write(
            f"Pairs >= {SIZE_THRESHOLD:.0%}: "
            f"{len(suspicious):,}\n\n"
        )

        for comparison in suspicious:
            ratio = comparison["ratio"]

            output.write(
                f"{comparison['chain']} / "
                f"{comparison['store']} / "
                f"{comparison['full_type']} "
                f"vs {comparison['normal_type']}\n"
            )

            output.write(
                f"  Full:   "
                f"{comparison['full_size']:,} bytes\n"
            )

            output.write(
                f"  Normal: "
                f"{comparison['normal_size']:,} bytes\n"
            )

            output.write(
                f"  Ratio:  {ratio:.2%}\n"
            )

            output.write(
                f"  Full file:   "
                f"{comparison['full'].name}\n"
            )

            output.write(
                f"  Normal file: "
                f"{comparison['normal'].name}\n\n"
            )

        # ----------------------------------------------------
        # Failures
        # ----------------------------------------------------

        output.write(
            "FAILED FILES\n"
        )
        output.write(
            "------------------------------------------------------------\n"
        )

        failed_files = sorted(
            {
                failure["file"]
                for failure in failures
            }
        )

        output.write(
            f"Unique failed files: "
            f"{len(failed_files):,}\n\n"
        )

        for failure in failures:
            output.write(
                f"Chain: {failure['chain']}\n"
            )
            output.write(
                f"Store: {failure['store']}\n"
            )
            output.write(
                f"Type:  {failure['feed_type']}\n"
            )
            output.write(
                f"File:  {failure['file']}\n"
            )
            output.write(
                f"Path:  {failure['failure_path']}\n"
            )
            output.write(
                f"Format: {failure['format']}\n"
            )
            output.write(
                f"Error:  {failure['details']}\n"
            )
            output.write("\n")

        # ----------------------------------------------------
        # Detailed successful nested structures
        # ----------------------------------------------------

        output.write(
            "NESTED FORMAT EXAMPLES\n"
        )
        output.write(
            "------------------------------------------------------------\n"
        )

        seen_trees = set()

        for result in file_results:
            tree = result["tree"]

            if not tree:
                continue

            lines = format_tree(tree)

            # Ignore files that are simply XML.
            if len(lines) <= 1:
                continue

            signature = tuple(
                line.strip()
                for line in lines
            )

            if signature in seen_trees:
                continue

            seen_trees.add(signature)

            output.write(
                f"\nFile: {result['path']}\n"
            )

            for line in lines:
                output.write(
                    f"  {line}\n"
                )

            if len(seen_trees) >= 100:
                break

    # --------------------------------------------------------
    # Failure CSV
    # --------------------------------------------------------

    with FAILURES_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "chain",
                "store",
                "feed_type",
                "file",
                "failure_path",
                "format",
                "details",
            ],
        )

        writer.writeheader()
        writer.writerows(failures)

    # --------------------------------------------------------
    # Console summary
    # --------------------------------------------------------

    unique_failed_files = {
        failure["file"]
        for failure in failures
    }

    print()
    print("=" * 60)
    print("INSPECTION COMPLETE")
    print("=" * 60)
    print(f"Files:              {len(files):,}")
    print(
        f"Successful files:   "
        f"{len(files) - len(unique_failed_files):,}"
    )
    print(
        f"Failed files:       "
        f"{len(unique_failed_files):,}"
    )
    print(
        f"Filename structures:{len(sorted_structures):,}"
    )
    print(
        f"Size pairs:         {len(comparisons):,}"
    )
    print(
        f">=80% pairs:        {len(suspicious):,}"
    )
    print()
    print(f"Report:   {OUTPUT_FILE}")
    print(f"Failures: {FAILURES_FILE}")


if __name__ == "__main__":
    main()