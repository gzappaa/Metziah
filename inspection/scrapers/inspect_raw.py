"""
inspection/scrapers/inspect_raw.py

Inspect field/path occurrence across all raw product JSON files.

Rules:
- Actual values are ignored.
- Array indexes are ignored.
- Array length is ignored.
- Dynamic ID/object keys are replaced with "*".
- Language-map keys are preserved as a language-map marker.
- Each path counts at most once per product.

Output:
    inspection/reports/product_field_occurrences.json
"""

import json
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = PROJECT_ROOT / "data" / "raw"

OUTPUT_FILE = (
    PROJECT_ROOT
    / "inspection"
    / "reports"
    / "product_field_occurrences.json"
)

OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True,
)


LANGUAGE_KEYS = {
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
}


def is_language_map(value):
    """
    Detect objects whose keys are language IDs.

    Example:
        {"1": "...", "2": "..."}

    These are NOT dynamic ID maps.
    """
    if not isinstance(value, dict) or not value:
        return False

    return set(value) <= LANGUAGE_KEYS


def is_dynamic_key_map(value):
    """
    Detect objects where the keys are dynamic IDs.

    Examples:
        {
            "6120": {...},
            "9822": {...}
        }

        {
            "10033": {...},
            "10036": {...}
        }

    Language maps are explicitly excluded.
    """
    if not isinstance(value, dict) or not value:
        return False

    if is_language_map(value):
        return False

    keys = list(value)

    # Dynamic IDs should be numeric strings.
    if not all(
        isinstance(key, str)
        and key.isdigit()
        for key in keys
    ):
        return False

    # Require at least one actual object/value.
    return True


def iter_product_paths(value, path="root"):
    """
    Yield structural field paths.

    Dynamic object keys become "*".
    Array indexes are omitted.
    """
    if isinstance(value, dict):
        if is_language_map(value):
            # The language IDs themselves are not interesting.
            # Inspect the structure of their values.
            for child in value.values():
                yield from iter_product_paths(
                    child,
                    path,
                )
            return

        if is_dynamic_key_map(value):
            for child in value.values():
                dynamic_path = f"{path} / *"

                yield dynamic_path

                yield from iter_product_paths(
                    child,
                    dynamic_path,
                )
            return

        for key, child in value.items():
            child_path = (
                f"{path} / {key}"
            )

            yield child_path

            yield from iter_product_paths(
                child,
                child_path,
            )

    elif isinstance(value, list):
        # No indexes.
        for item in value:
            yield from iter_product_paths(
                item,
                path,
            )


def load_products():
    """
    Load every product from every retailer directory.
    """
    records = []

    retailer_dirs = sorted(
        path
        for path in RAW_DIR.iterdir()
        if path.is_dir()
    )

    for retailer_dir in retailer_dirs:
        retailer = retailer_dir.name

        files = sorted(
            retailer_dir.glob("*.json")
        )

        print(
            f"{retailer}: "
            f"scanning {len(files)} JSON files..."
        )

        for json_file in files:
            try:
                data = json.loads(
                    json_file.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
            ) as exc:
                print(
                    f"WARNING: failed to read "
                    f"{json_file}: {exc}"
                )
                continue

            products = data.get("products")

            if not isinstance(
                products,
                list,
            ):
                continue

            for product in products:
                if isinstance(
                    product,
                    dict,
                ):
                    records.append(
                        {
                            "retailer": retailer,
                            "file": json_file,
                            "product": product,
                        }
                    )

    return records


def build_report(records):
    """
    Count field paths across products.

    A path is counted once per product, even if it occurs
    multiple times inside an array.
    """
    field_counts = Counter()

    field_retailers = defaultdict(
        Counter
    )

    total_products = len(records)

    retailer_counts = Counter()

    for index, record in enumerate(
        records,
        start=1,
    ):
        retailer = record["retailer"]

        retailer_counts[retailer] += 1

        paths = set(
            iter_product_paths(
                record["product"]
            )
        )

        for path in paths:
            field_counts[path] += 1

            field_retailers[path][
                retailer
            ] += 1

        if index % 5000 == 0:
            print(
                f"  Processed "
                f"{index:,}/{total_products:,} "
                f"({index / total_products * 100:.1f}%)"
            )

    # All unique structural paths, independent of occurrence count.
    structures = sorted(field_counts)

    fields = {}

    for path in sorted(
        field_counts,
        key=lambda item: (
            -field_counts[item],
            item,
        ),
    ):
        count = field_counts[path]

        fields[path] = {
            "products": count,
            "percentage": round(
                count
                / total_products
                * 100,
                2,
            ),
            "retailers": dict(
                sorted(
                    field_retailers[path].items()
                )
            ),
        }

    return {
        "summary": {
            "total_product_occurrences": (
                total_products
            ),
            "unique_field_paths": len(
                structures
            ),
            "retailers": dict(
                sorted(
                    retailer_counts.items()
                )
            ),
        },

        "structures": structures,

        "fields": fields,
    }


def main():
    records = load_products()

    if not records:
        print("No products found.")
        return

    print()
    print(
        f"Loaded {len(records):,} "
        f"product occurrences."
    )

    print(
        "Counting field occurrences..."
    )

    print()

    report = build_report(
        records
    )

    OUTPUT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()

    print(
        f"Products scanned: "
        f"{report['summary']['total_product_occurrences']:,}"
    )

    print(
        f"Unique field paths: "
        f"{report['summary']['unique_field_paths']:,}"
    )

    print(
        f"Report written to: "
        f"{OUTPUT_FILE.relative_to(PROJECT_ROOT)}"
    )


if __name__ == "__main__":
    main()