"""
inspection/scrapers/check_parsed_products.py

Inspect parsed product JSONL files for duplicate barcodes and differences.

Scans:
    data/parsed/**/products_parsed.jsonl

Writes:
    inspection/scrapers/reports/check_parsed_products.txt

The report contains a summary and, for duplicate barcodes, only the fields
whose values differ between records.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


COMPARE_FIELDS = [
    "local_name",
    "name_he",
    "name_en",
    "name_ru",
    "brand_name_he",
    "brand_name_en",
    "brand_name_ru",
    "department_name",
    "family_name_he",
    "family_name_en",
    "category_path_he",
    "category_path_en",
    "categories_paths",
    "ingredients_he",
    "ingredients_en",
    "ingredients_ru",
    "description_he",
    "description_en",
    "description_ru",
    "nutrition_facts",
    "nutrition_values",
    "main_image_url",
    "images",
    "nutrition_image_url",
]


def normalize(value):
    """Normalize JSON values for stable comparison."""
    if isinstance(value, list):
        return [normalize(item) for item in value]

    if isinstance(value, dict):
        return {key: normalize(value[key]) for key in sorted(value)}

    return value


def format_value(value):
    """Format a value compactly while preserving Unicode."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    )


def load_products(root):
    """Load products from every products_parsed.jsonl below root."""
    products = defaultdict(list)
    files = sorted(root.rglob("products_parsed.jsonl"))

    if not files:
        raise SystemExit(
            f"No products_parsed.jsonl files found under {root}"
        )

    total_rows = 0
    invalid_json = 0
    missing_barcode = 0

    for path in files:
        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, 1):
                line = line.strip()

                if not line:
                    continue

                total_rows += 1

                try:
                    product = json.loads(line)
                except json.JSONDecodeError:
                    invalid_json += 1
                    continue

                barcode = product.get("barcode")

                if barcode in (None, ""):
                    missing_barcode += 1
                    continue

                barcode = str(barcode).strip()

                products[barcode].append(
                    {
                        "product": product,
                        "file": path,
                        "line": line_number,
                    }
                )

    return (
        files,
        products,
        total_rows,
        invalid_json,
        missing_barcode,
    )


def get_differences(records):
    """Return only fields with different values across duplicate records."""
    differences = {}

    for field in COMPARE_FIELDS:
        values = [
            normalize(record["product"].get(field))
            for record in records
        ]

        serialized = {
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
            )
            for value in values
        }

        if len(serialized) > 1:
            differences[field] = values

    return differences


def build_report(root):
    """Build the complete inspection report."""
    (
        files,
        products,
        total_rows,
        invalid_json,
        missing_barcode,
    ) = load_products(root)

    duplicates = {
        barcode: records
        for barcode, records in products.items()
        if len(records) > 1
    }

    changed = {
        barcode: records
        for barcode, records in duplicates.items()
        if get_differences(records)
    }

    duplicate_rows = sum(
        len(records) - 1
        for records in duplicates.values()
    )

    lines = [
        "PARSED PRODUCT DUPLICATE INSPECTION",
        "=" * 80,
        "",
        f"Root:                         {root}",
        f"Files scanned:                {len(files)}",
        f"Product rows:                 {total_rows}",
        f"Unique barcodes:              {len(products)}",
        f"Duplicate barcode groups:     {len(duplicates)}",
        f"Duplicate rows:               {duplicate_rows}",
        f"Groups with differences:      {len(changed)}",
        f"Groups completely identical:  "
        f"{len(duplicates) - len(changed)}",
        f"Invalid JSON rows:            {invalid_json}",
        f"Missing barcode rows:         {missing_barcode}",
        "",
    ]

    if not duplicates:
        lines.append("No duplicate barcodes found.")
        return "\n".join(lines) + "\n"

    if not changed:
        lines.extend(
            [
                "No duplicate barcode groups have differences in the",
                "enrichment fields being compared.",
                "",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "DUPLICATES WITH DIFFERENCES",
            "=" * 80,
            "",
        ]
    )

    for barcode in sorted(changed):
        records = changed[barcode]
        differences = get_differences(records)

        lines.extend(
            [
                f"DUPLICATE BARCODE: {barcode}",
                "-" * 80,
                f"Occurrences: {len(records)}",
                "",
            ]
        )

        for record in records:
            product = record["product"]
            company = product.get("company")

            lines.append(
                f"  {company or '<unknown>'} | "
                f"{record['file']}:{record['line']}"
            )

        lines.extend(
            [
                "",
                "DIFFERENCES",
                "-" * 80,
            ]
        )

        for field, values in differences.items():
            lines.append("")
            lines.append(field)

            for record, value in zip(records, values):
                company = record["product"].get("company")

                lines.append(
                    f"  {company or '<unknown>'}:"
                )
                lines.append(
                    f"    {format_value(value)}"
                )

        lines.extend(["", ""])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Inspect duplicate barcodes in parsed product JSONL files."
        )
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/parsed"),
        help="Root directory containing parsed product files.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "inspection/scrapers/reports/"
            "check_parsed_products.txt"
        ),
        help="Output report path.",
    )

    args = parser.parse_args()

    report = build_report(args.root)

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        report,
        encoding="utf-8",
    )

    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()