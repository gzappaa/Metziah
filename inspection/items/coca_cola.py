import gzip
import json
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET


BASE_DIR = Path(__file__).resolve().parents[2]

FEEDS_DIR = BASE_DIR / "data" / "feeds"
REFERENCE_DIR = BASE_DIR / "data" / "reference"

CHAINS_FILE = REFERENCE_DIR / "chains.json"
EXTRA_CHAINS_FILE = REFERENCE_DIR / "extra_chains.json"

REPORT_FILE = BASE_DIR / "inspection" / "reports" / "coca_cola_report.txt"

TARGET_ITEM_CODE = "7290110115227"


def load_chain_names():
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
    Get the newest physical file from:

        data/feeds/{chain_id}/{store_id}/pricesfull/

    No filename parsing.
    No file_tracking.csv.
    Subchains are ignored.
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
                (chain_id, store_id, latest)
            )

    return latest_files


def local_name(tag):
    if not isinstance(tag, str):
        return ""

    return tag.rsplit("}", 1)[-1].lower()


def find_text(element, names):
    """
    Find the first non-empty text value whose tag matches
    one of the supplied names.
    """
    names = {name.lower() for name in names}

    for child in element.iter():
        if local_name(child.tag) in names:
            if child.text and child.text.strip():
                return child.text.strip()

    return None


def extract_item_name_from_root(root):
    """
    Find the exact TARGET_ITEM_CODE and return the name belonging
    to the same product/item subtree.
    """
    parent_map = {
        child: parent
        for parent in root.iter()
        for child in parent
    }

    for element in root.iter():
        if local_name(element.tag) != "itemcode":
            continue

        if not element.text:
            continue

        if element.text.strip() != TARGET_ITEM_CODE:
            continue

        # Walk upward through the XML structure.
        # Look for a product/item container containing the name.
        current = element

        for _ in range(10):
            current = parent_map.get(current)

            if current is None:
                break

            name = find_text(
                current,
                {
                    "itemname",
                    "productname",
                    "itemdescription",
                },
            )

            if name:
                return name

    return None


def extract_item_name_from_file(file_obj):
    tree = ET.parse(file_obj)
    root = tree.getroot()

    return extract_item_name_from_root(root)


def extract_from_zip(path):
    """
    Extract XML/XML.GZ content from a ZIP archive.
    """

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
                        name = extract_item_name_from_file(
                            xml_file
                        )
                else:
                    name = extract_item_name_from_file(raw)

                if name:
                    return name

    return None


def extract_item_name(path):
    """
    Parse one PriceFull and return the name associated with
    TARGET_ITEM_CODE.

    Filename extensions are treated as hints, not guaranteed
    truth.

    Supported formats:

        .zip  -> ZIP
        .gz   -> GZIP, then ZIP fallback
        .xml  -> XML
        no extension / unknown -> GZIP, ZIP, then XML

    This handles cases where:
        - a gzip file has no .gz extension
        - a ZIP file is incorrectly named .gz
        - an extensionless file is plain XML
    """

    suffixes = [suffix.lower() for suffix in path.suffixes]

    # ---------------------------------------------------------
    # ZIP
    # ---------------------------------------------------------

    if ".zip" in suffixes:
        return extract_from_zip(path)

    # ---------------------------------------------------------
    # GZIP
    # ---------------------------------------------------------

    if ".gz" in suffixes:
        try:
            with gzip.open(path, "rb") as f:
                return extract_item_name_from_file(f)

        except (
            gzip.BadGzipFile,
            OSError,
            EOFError,
        ):
            # Some files are incorrectly named .gz but are
            # actually ZIP archives.
            try:
                return extract_from_zip(path)

            except zipfile.BadZipFile:
                raise

    # ---------------------------------------------------------
    # XML
    # ---------------------------------------------------------

    if ".xml" in suffixes:
        with path.open("rb") as f:
            return extract_item_name_from_file(f)

    # ---------------------------------------------------------
    # Unknown / extensionless
    # ---------------------------------------------------------

    # First try GZIP.
    try:
        with gzip.open(path, "rb") as f:
            return extract_item_name_from_file(f)

    except (
        gzip.BadGzipFile,
        OSError,
        EOFError,
    ):
        pass

    # Then try ZIP.
    try:
        return extract_from_zip(path)

    except zipfile.BadZipFile:
        pass

    # Finally assume plain XML.
    with path.open("rb") as f:
        return extract_item_name_from_file(f)


def format_chain_name(chain_id, chain_names):
    return chain_names.get(chain_id, chain_id)


def main():
    chain_names = load_chain_names()
    latest_files = get_latest_pricefull_files()

    total_files = len(latest_files)

    print(f"Latest PriceFull files found: {total_files}")

    # chain_id -> name -> set(store_ids)
    chain_variations = defaultdict(
        lambda: defaultdict(set)
    )

    stores_with_item = set()
    stores_without_item = []
    unreadable_files = []

    for index, (chain_id, store_id, path) in enumerate(
        latest_files,
        start=1,
    ):
        if index == 1 or index % 500 == 0 or index == total_files:
            print(
                f"Processing PriceFull files: "
                f"{index:,}/{total_files:,}"
            )

        try:
            name = extract_item_name(path)

            if name:
                chain_variations[chain_id][name].add(store_id)

                stores_with_item.add(
                    (chain_id, store_id)
                )

            else:
                stores_without_item.append(
                    (chain_id, store_id)
                )

        except Exception as exc:
            unreadable_files.append(
                {
                    "chain": chain_id,
                    "store": store_id,
                    "path": str(path.relative_to(BASE_DIR)),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    # Global unique names across all chains.
    global_names = set()

    for variations in chain_variations.values():
        global_names.update(variations.keys())

    lines = []

    lines.append("COCA COLA ITEM TEST")
    lines.append("=" * 80)
    lines.append(f"ItemCode: {TARGET_ITEM_CODE}")
    lines.append("")

    lines.append(
        f"Total stores with item: {len(stores_with_item)}"
    )

    lines.append(
        f"Total variations of name: {len(global_names)}"
    )

    lines.append("")

    lines.append("GLOBAL NAME VARIATIONS")
    lines.append("-" * 80)

    for name in sorted(global_names):
        lines.append(name)

    lines.append("")

    lines.append("BY CHAIN")
    lines.append("-" * 80)

    sorted_chains = sorted(
        chain_variations.items(),
        key=lambda item: format_chain_name(
            item[0],
            chain_names,
        ).lower(),
    )

    for chain_id, variations in sorted_chains:
        chain_name = format_chain_name(
            chain_id,
            chain_names,
        )

        lines.append("")
        lines.append(
            f"{chain_name} [{chain_id}]"
        )

        for name in sorted(variations):
            store_count = len(variations[name])

            lines.append(
                f"  {name} "
                f"({store_count} store"
                f"{'' if store_count == 1 else 's'})"
            )

        lines.append(
            f"  Total variation {chain_name}: "
            f"{len(variations)}"
        )

    lines.append("")
    lines.append("STORES WHERE ITEM WAS NOT FOUND")
    lines.append("-" * 80)

    for chain_id, store_id in sorted(stores_without_item):
        chain_name = format_chain_name(
            chain_id,
            chain_names,
        )

        lines.append(
            f"{chain_name} [{chain_id}] - store {store_id}"
        )

    lines.append("")
    lines.append("UNREADABLE FILES")
    lines.append("-" * 80)

    for item in unreadable_files:
        lines.append(
            f"{item['chain']} / store {item['store']}: "
            f"{item['path']}"
        )
        lines.append(
            f"  {item['error']}"
        )

    lines.append("")
    lines.append(
        f"Stores where item was not found: "
        f"{len(stores_without_item)}"
    )

    lines.append(
        f"Unreadable files: "
        f"{len(unreadable_files)}"
    )

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print(
        f"Report written to: {REPORT_FILE}"
    )


if __name__ == "__main__":
    main()