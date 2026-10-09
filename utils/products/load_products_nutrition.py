"""
Load normalized product nutrition from parsed product JSONL files.

Reads:
    data/parsed/*/products_parsed.jsonl

Source nutrition:
    product["nutrition_values"]

Normalizes rows using:
    utils.processing.normalize_nutritional.normalize_rows

Nutrition from multiple sources for the same barcode is reconciled
before loading. Missing values are filled from other sources, while
existing non-NULL values are never overwritten.

Writes:
    product_nutrition
"""

import json
from pathlib import Path

import db
from utils.processing.normalize_nutritional import normalize_rows, validate


PARSED_DIR = Path("data/parsed")


def iter_products():
    """Yield parsed products from all supermarket JSONL files."""
    for path in sorted(PARSED_DIR.glob("*/products_parsed.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if not line:
                    continue

                yield path, json.loads(line)


def nutrition_rows(product):
    """
    Convert the parsed nutrition_values structure into rows accepted
    by normalize_rows().
    """
    nutrition = product.get("nutrition_values")

    if not isinstance(nutrition, dict):
        return []

    sizes = {}

    for size in nutrition.get("sizes", []):
        size_id = size.get("id")
        names = size.get("names") or {}
        size_name = names.get("1")

        if size_id is not None and size_name is not None:
            sizes[size_id] = size_name

    rows = []

    for nutrient in nutrition.get("values", []):
        names = nutrient.get("names") or {}
        label = names.get("1")

        if not label:
            continue

        for size_value in nutrient.get("sizeValues", []):
            size_id = size_value.get("sizeId")

            rows.append(
                {
                    "label": label,
                    "value": size_value.get("value"),
                    "unit": (
                        (size_value.get("unitOfMeasure") or {}).get("names", {})
                    ).get("1"),
                    "size": sizes.get(size_id, ""),
                    "lt": size_value.get("valueLessThan", False),
                }
            )

    return rows


def _nutrition_key(row):
    """
    Return the identity used when reconciling nutrition rows.

    Mapped nutrients are identified by nutrient + basis.

    Unmapped rows cannot use nutrient, so their cleaned raw label +
    basis_raw is used instead.
    """
    if row.nutrient is not None:
        return (
            "canonical",
            row.nutrient,
            row.basis,
        )

    return (
        "unmapped",
        row.raw_label,
        row.basis_raw,
    )


def _merge_value(existing, incoming):
    """
    Fill an existing value only when it is currently missing.

    Existing non-NULL values always win.
    """
    if existing is None and incoming is not None:
        return incoming

    return existing


def reconcile_rows(existing, incoming):
    """
    Reconcile two normalized nutrition rows.

    Existing non-NULL values are never overwritten. Missing values
    are filled from incoming. Flags are combined.
    """
    existing.amount = _merge_value(existing.amount, incoming.amount)
    existing.unit = _merge_value(existing.unit, incoming.unit)
    existing.bound = _merge_value(existing.bound, incoming.bound)

    if not existing.raw_label and incoming.raw_label:
        existing.raw_label = incoming.raw_label

    if not existing.basis_raw and incoming.basis_raw:
        existing.basis_raw = incoming.basis_raw

    existing.flags = sorted(
        set(existing.flags or []) | set(incoming.flags or [])
    )

    return existing


def load_product_nutrition():
    """
    Rebuild product_nutrition from all parsed product files.

    Multiple sources for the same barcode are reconciled into one
    nutrition dataset. Missing values are filled from other sources;
    existing non-NULL values are preserved.
    """
    products = {}

    for path, product in iter_products():
        item_code = product.get("barcode")

        if not item_code:
            continue

        rows = nutrition_rows(product)

        if not rows:
            continue

        normalized = normalize_rows(rows)

        if not normalized:
            continue

        source = product.get("company") or path.parent.name

        if item_code not in products:
            products[item_code] = {
                "source": source,
                "rows": {},
            }

        product_data = products[item_code]

        for row in normalized:
            key = _nutrition_key(row)

            if key not in product_data["rows"]:
                product_data["rows"][key] = row
                continue

            reconcile_rows(product_data["rows"][key], row)

    for product_data in products.values():
        validate(list(product_data["rows"].values()))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE product_nutrition")

            inserted = 0

            for item_code, product_data in products.items():
                source = product_data["source"]

                for row in product_data["rows"].values():
                    cur.execute(
                        """
                        INSERT INTO product_nutrition (
                            item_code,
                            source,
                            raw_label,
                            nutrient,
                            amount,
                            unit,
                            bound,
                            basis,
                            basis_raw,
                            flags,
                            is_canonical
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        """,
                        (
                            item_code,
                            source,
                            row.raw_label,
                            row.nutrient,
                            row.amount,
                            row.unit,
                            row.bound,
                            row.basis,
                            row.basis_raw,
                            row.flags,
                            True,
                        ),
                    )

                    inserted += 1

        conn.commit()

    print(f"Products with nutrition: {len(products)}")
    print(f"Inserted nutrition rows: {inserted}")


if __name__ == "__main__":
    load_product_nutrition()