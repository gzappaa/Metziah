"""
inspection/scrapers/inspect_nutritional_parsed.py

Inspect nutritional fields across all parsed product JSONL files.

This is a discovery/inspection tool, not a validation or filtering tool.

The report intentionally keeps every nutritional field encountered at least
once, including rare or unusual nutrients. The output is intended to serve
as the source of truth for designing the normalized nutrition schema later.


Output:
    inspection/reports/nutrition_fields.json
    inspection/reports/nutrition_fields.txt
"""


from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


PARSED_DIR = Path("data/parsed")
REPORT_DIR = Path("inspection/reports")
REPORT_FILE = REPORT_DIR / "nutrition_fields.json"
REPORT_TEXT_FILE = REPORT_DIR / "nutrition_fields.txt"


def get_names(value: Any) -> list[str]:
    """Extract non-empty names from a localized names dictionary."""
    if not isinstance(value, dict):
        return []

    return [
        str(name).strip()
        for name in value.values()
        if name is not None and str(name).strip()
    ]


def add_values(
    target: set[str],
    values: list[str],
) -> None:
    """Add non-empty values to a set."""
    for value in values:
        if value:
            target.add(value)


def product_key(product: dict[str, Any], filename: str) -> str:
    """Return the best available identifier for a product."""
    return str(
        product.get("barcode")
        or product.get("local_barcode")
        or product.get("item_code")
        or product.get("product_id")
        or product.get("id")
        or filename
    )


def get_unit_names(unit: Any) -> list[str]:
    """Extract all available names from a unit-of-measure object."""
    if not isinstance(unit, dict):
        return []

    names = get_names(unit.get("names"))

    default_name = unit.get("defaultName")
    if default_name is not None and str(default_name).strip():
        names.append(str(default_name).strip())

    return list(dict.fromkeys(names))


def get_nutrient_names(nutrient: dict[str, Any]) -> list[str]:
    """Extract nutrient names from a nutrition value object."""
    names = get_names(nutrient.get("names"))

    if not names:
        name = nutrient.get("name")
        if name is not None and str(name).strip():
            names.append(str(name).strip())

    return list(dict.fromkeys(names))


def register_nutrient(
    stats: dict[str, dict[str, Any]],
    *,
    name: str,
    source: str,
    path: str,
    product: str,
    value: Any = None,
    units: list[str] | None = None,
    sizes: list[str] | None = None,
    value_less_than: bool | None = None,
) -> None:
    """Register an observed nutrient and its normalization metadata."""
    if not name.strip():
        return

    entry = stats.setdefault(
        name,
        {
            "count": 0,
            "sources": set(),
            "paths": set(),
            "units": set(),
            "sizes": set(),
            "value_types": set(),
            "value_less_than": set(),
            "examples": [],
        },
    )

    entry["count"] += 1
    entry["sources"].add(source)
    entry["paths"].add(path)

    add_values(entry["units"], units or [])
    add_values(entry["sizes"], sizes or [])

    if value is not None:
        if isinstance(value, bool):
            entry["value_types"].add("boolean")
        elif isinstance(value, (int, float)):
            entry["value_types"].add("number")
        elif isinstance(value, str):
            entry["value_types"].add("string")
        else:
            entry["value_types"].add(type(value).__name__)

    if value_less_than is not None:
        entry["value_less_than"].add(str(value_less_than).lower())

    if len(entry["examples"]) < 5:
        example = {
            "product": product,
            "value": value,
        }

        if units:
            example["units"] = units

        if sizes:
            example["sizes"] = sizes

        if value_less_than is not None:
            example["valueLessThan"] = value_less_than

        entry["examples"].append(example)


def inspect_nutrition_facts(
    nutrition_facts: Any,
    stats: dict[str, dict[str, Any]],
    product: dict[str, Any],
    filename: str,
) -> None:
    """Inspect nutritionFacts structures."""
    if not isinstance(nutrition_facts, list):
        return

    product_id = product_key(product, filename)

    for fact in nutrition_facts:
        if not isinstance(fact, dict):
            continue

        nutrition_fact = fact.get("nutritionFact") or {}

        names = get_names(nutrition_fact.get("name"))

        if not names:
            name = nutrition_fact.get("name")
            if name is not None and str(name).strip():
                names = [str(name).strip()]

        unit_names = get_unit_names(fact.get("unitOfMeasure"))
        value = fact.get("value")

        for name in names:
            register_nutrient(
                stats,
                name=name,
                source="nutritionFacts",
                path="nutritionFacts.nutritionFact.name",
                product=product_id,
                value=value,
                units=unit_names,
            )

        if not names and nutrition_fact.get("id") is not None:
            register_nutrient(
                stats,
                name=f"id:{nutrition_fact['id']}",
                source="nutritionFacts",
                path="nutritionFacts.nutritionFact.id",
                product=product_id,
                value=value,
                units=unit_names,
            )


def inspect_nutrition_values(
    nutrition_values: Any,
    stats: dict[str, dict[str, Any]],
    product: dict[str, Any],
    filename: str,
) -> None:
    """Inspect nutritionValues structures."""
    if not isinstance(nutrition_values, dict):
        return

    product_id = product_key(product, filename)

    size_names: dict[Any, list[str]] = {}

    sizes = nutrition_values.get("sizes") or []

    if isinstance(sizes, list):
        for size in sizes:
            if not isinstance(size, dict):
                continue

            size_id = size.get("id")
            names = get_names(size.get("names"))

            if size_id is not None:
                size_names[size_id] = names

    values = nutrition_values.get("values") or []

    if not isinstance(values, list):
        return

    for nutrient in values:
        if not isinstance(nutrient, dict):
            continue

        nutrient_names = get_nutrient_names(nutrient)
        size_values = nutrient.get("sizeValues") or []

        if not isinstance(size_values, list):
            continue

        for size_value in size_values:
            if not isinstance(size_value, dict):
                continue

            size_id = size_value.get("sizeId")
            value = size_value.get("value")
            value_less_than = size_value.get("valueLessThan")

            unit_names = get_unit_names(
                size_value.get("unitOfMeasure")
            )

            current_size_names = size_names.get(size_id, [])

            for name in nutrient_names:
                register_nutrient(
                    stats,
                    name=name,
                    source="nutritionValues",
                    path="nutritionValues.values.sizeValues.value",
                    product=product_id,
                    value=value,
                    units=unit_names,
                    sizes=current_size_names,
                    value_less_than=value_less_than,
                )

        if not nutrient_names:
            nutrient_id = nutrient.get("id")

            if nutrient_id is not None:
                register_nutrient(
                    stats,
                    name=f"id:{nutrient_id}",
                    source="nutritionValues",
                    path="nutritionValues.values.id",
                    product=product_id,
                )

        elif not size_values:
            for name in nutrient_names:
                register_nutrient(
                    stats,
                    name=name,
                    source="nutritionValues",
                    path="nutritionValues.values.names",
                    product=product_id,
                )


def inspect_product(
    product: dict[str, Any],
    stats: dict[str, dict[str, Any]],
    filename: str,
    field_presence: dict[str, int],
) -> None:
    """Inspect all nutrition-related fields in one product."""
    for field in (
        "nutrition_facts",
        "nutrition_values",
        "nutrition_image_url",
    ):
        if product.get(field) is not None:
            field_presence[field] += 1

    inspect_nutrition_facts(
        product.get("nutrition_facts"),
        stats,
        product,
        filename,
    )

    inspect_nutrition_values(
        product.get("nutrition_values"),
        stats,
        product,
        filename,
    )


def scan_file(
    path: Path,
    stats: dict[str, dict[str, Any]],
    field_presence: dict[str, int],
) -> tuple[int, int]:
    """Scan one JSONL file."""
    products = 0
    invalid_lines = 0

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            try:
                product = json.loads(line)
            except json.JSONDecodeError:
                invalid_lines += 1
                continue

            if not isinstance(product, dict):
                continue

            products += 1

            inspect_product(
                product,
                stats,
                path.name,
                field_presence,
            )

    return products, invalid_lines


def make_serializable(
    stats: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Convert sets to JSON-compatible lists."""
    result = {}

    for name, data in stats.items():
        result[name] = {
            "count": data["count"],
            "sources": sorted(data["sources"]),
            "paths": sorted(data["paths"]),
            "units": sorted(data["units"]),
            "sizes": sorted(data["sizes"]),
            "value_types": sorted(data["value_types"]),
            "value_less_than": sorted(data["value_less_than"]),
            "examples": data["examples"],
        }

    return result


def write_text_report(
    files_count: int,
    total_products: int,
    total_invalid_lines: int,
    field_presence: dict[str, int],
    nutrients: dict[str, dict[str, Any]],
    unique_units: list[str],
    unique_sizes: list[str],
) -> None:
    """Write the human-readable nutrition inventory."""
    with REPORT_TEXT_FILE.open("w", encoding="utf-8") as file:
        file.write("=" * 72 + "\n")
        file.write("NUTRITION NORMALIZATION INVENTORY\n")
        file.write("=" * 72 + "\n\n")

        file.write(f"Files scanned:        {files_count:,}\n")
        file.write(f"Products scanned:     {total_products:,}\n")
        file.write(f"Invalid JSONL lines:  {total_invalid_lines:,}\n\n")

        file.write("NON-NULL NUTRITION FIELDS\n")
        file.write("-" * 72 + "\n")

        for field, count in sorted(field_presence.items()):
            file.write(f"  {field:<25} {count:,}\n")

        file.write("\n")
        file.write("SUMMARY\n")
        file.write("-" * 72 + "\n")
        file.write(f"  Unique nutrient types: {len(nutrients):,}\n")
        file.write(f"  Unique units:          {len(unique_units):,}\n")
        file.write(f"  Unique sizes:          {len(unique_sizes):,}\n\n")

        file.write("NUTRIENT TYPES\n")
        file.write("-" * 72 + "\n")

        for name in sorted(nutrients):
            data = nutrients[name]

            file.write(f"\n  {name}\n")
            file.write(f"    count:   {data['count']:,}\n")
            file.write(
                f"    units:   "
                f"{', '.join(data['units']) or '-'}\n"
            )
            file.write(
                f"    sizes:   "
                f"{', '.join(data['sizes']) or '-'}\n"
            )
            file.write(
                f"    sources: "
                f"{', '.join(data['sources']) or '-'}\n"
            )

            if data["value_less_than"]:
                file.write(
                    f"    < value: "
                    f"{', '.join(data['value_less_than'])}\n"
                )

            if data["value_types"]:
                file.write(
                    f"    types:   "
                    f"{', '.join(data['value_types'])}\n"
                )

            if data["examples"]:
                examples = []

                for example in data["examples"][:3]:
                    value = example["value"]

                    if example.get("units"):
                        value = (
                            f"{value} "
                            f"{', '.join(example['units'])}"
                        )

                    examples.append(str(value))

                file.write(
                    f"    examples: {', '.join(examples)}\n"
                )

        file.write("\n")
        file.write("=" * 72 + "\n")
        file.write(f"Report: {REPORT_TEXT_FILE}\n")
        file.write("=" * 72 + "\n")


def main() -> None:
    """Scan all parsed JSONL files and create nutrition reports."""
    if not PARSED_DIR.exists():
        raise FileNotFoundError(
            f"Parsed directory does not exist: {PARSED_DIR}"
        )

    files = sorted(PARSED_DIR.glob("*/*.jsonl"))

    if not files:
        print(f"No JSONL files found under {PARSED_DIR}")
        return

    stats: dict[str, dict[str, Any]] = {}
    field_presence: dict[str, int] = defaultdict(int)

    total_products = 0
    total_invalid_lines = 0

    for path in files:
        products, invalid_lines = scan_file(
            path,
            stats,
            field_presence,
        )

        total_products += products
        total_invalid_lines += invalid_lines

    nutrients = make_serializable(stats)

    nutrients = dict(
        sorted(
            nutrients.items(),
            key=lambda item: (-item[1]["count"], item[0]),
        )
    )

    unique_units = sorted(
        {
            unit
            for nutrient in nutrients.values()
            for unit in nutrient["units"]
        }
    )

    unique_sizes = sorted(
        {
            size
            for nutrient in nutrients.values()
            for size in nutrient["sizes"]
        }
    )

    report = {
        "description": (
            "Complete discovery inventory of nutritional data found in "
            "parsed product JSONL files. Rare fields are intentionally "
            "preserved. This report is intended as the source of truth "
            "for designing the normalized nutrition schema."
        ),
        "files_scanned": len(files),
        "products_scanned": total_products,
        "invalid_jsonl_lines": total_invalid_lines,
        "field_presence": dict(field_presence),
        "summary": {
            "unique_nutrient_types": len(nutrients),
            "unique_units": len(unique_units),
            "unique_sizes": len(unique_sizes),
        },
        "unique_units": unique_units,
        "unique_sizes": unique_sizes,
        "nutrients": nutrients,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    with REPORT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
        )

    write_text_report(
        files_count=len(files),
        total_products=total_products,
        total_invalid_lines=total_invalid_lines,
        field_presence=field_presence,
        nutrients=nutrients,
        unique_units=unique_units,
        unique_sizes=unique_sizes,
    )

    print("=" * 72)
    print("NUTRITION NORMALIZATION INVENTORY")
    print("=" * 72)
    print()
    print(f"Files scanned:        {len(files):,}")
    print(f"Products scanned:     {total_products:,}")
    print(f"Invalid JSONL lines:  {total_invalid_lines:,}")
    print()

    print("NON-NULL NUTRITION FIELDS")
    print("-" * 72)

    for field, count in sorted(field_presence.items()):
        print(f"  {field:<25} {count:,}")

    print()
    print("SUMMARY")
    print("-" * 72)
    print(f"  Unique nutrient types: {len(nutrients):,}")
    print(f"  Unique units:          {len(unique_units):,}")
    print(f"  Unique sizes:          {len(unique_sizes):,}")

    print()
    print("NUTRIENT TYPES")
    print("-" * 72)

    for name in sorted(nutrients):
        data = nutrients[name]

        print()
        print(f"  {name}")
        print(f"    count:   {data['count']:,}")
        print(
            f"    units:   "
            f"{', '.join(data['units']) or '-'}"
        )
        print(
            f"    sizes:   "
            f"{', '.join(data['sizes']) or '-'}"
        )
        print(
            f"    sources: "
            f"{', '.join(data['sources']) or '-'}"
        )

        if data["value_less_than"]:
            print(
                f"    < value: "
                f"{', '.join(data['value_less_than'])}"
            )

        if data["value_types"]:
            print(
                f"    types:   "
                f"{', '.join(data['value_types'])}"
            )

        if data["examples"]:
            examples = []

            for example in data["examples"][:3]:
                value = example["value"]

                if example.get("units"):
                    value = (
                        f"{value} "
                        f"{', '.join(example['units'])}"
                    )

                examples.append(str(value))

            print(f"    examples: {', '.join(examples)}")

    print()
    print("=" * 72)
    print(f"JSON report: {REPORT_FILE}")
    print(f"TXT report:  {REPORT_TEXT_FILE}")
    print("=" * 72)


if __name__ == "__main__":
    main()