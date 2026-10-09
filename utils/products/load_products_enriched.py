"""
utils/products/load_products_enriched.py

Load enriched products from parsed JSONL files.

The selected source is processed first and acts as the source of truth.
Fallback sources only:
    - add products that do not exist yet
    - fill metadata fields that are still empty

Existing non-empty metadata is never overwritten.

Category normalization:
    - category_path_he is stored exactly as scraped.
    - category_he and subcategory_he are derived from
      data/reference/categories.json.
    - Unmapped categories leave both canonical fields NULL.
"""

import argparse
import json
import logging
from pathlib import Path

from db import get_connection
from logging_config import setup_general_logging
from database.repository import (
    insert_product_enrichment,
    update_product_enrichment_missing,
)


logger = logging.getLogger(__name__)


PARSED_ROOT = Path("data/parsed")
CATEGORIES_PATH = Path("data/reference/categories.json")


def load_jsonl(path):
    """Yield products from a parsed JSONL file."""
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            line = line.strip()

            if not line:
                continue

            try:
                product = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid JSON: %s:%s",
                    path,
                    line_number,
                )
                continue

            yield product


def load_category_mapping():
    """Load raw category paths and map them to canonical categories."""
    with CATEGORIES_PATH.open("r", encoding="utf-8") as file:
        categories = json.load(file)

    mapping = {}

    for category_he, subcategories in categories.items():
        for subcategory_he, raw_paths in subcategories.items():
            for raw_path in raw_paths:
                if raw_path in mapping:
                    raise ValueError(
                        f"Duplicate category mapping: {raw_path}"
                    )

                mapping[raw_path] = (
                    category_he,
                    subcategory_he,
                )

    return mapping


def normalize_category_path(category_path, category_mapping):
    """
    Normalize a raw category path.

    Returns:
        (category_he, subcategory_he)

    Unmapped or invalid paths return:
        (None, None)
    """
    if not isinstance(category_path, list) or len(category_path) < 2:
        return None, None

    raw_path = f"{category_path[0]} / {category_path[1]}"

    return category_mapping.get(raw_path, (None, None))


def get_item_code(product):
    """Return the product barcode as a normalized item code."""
    barcode = product.get("barcode")

    if barcode is None:
        return None

    barcode = str(barcode).strip()
    return barcode or None


def get_enrichment_data(product, category_mapping):
    """Extract enrichment fields from a parsed product."""
    category_he, subcategory_he = normalize_category_path(
        product.get("category_path_he"),
        category_mapping,
    )

    return {
        "local_name": product.get("local_name"),
        "name_he": product.get("name_he"),
        "name_en": product.get("name_en"),
        "brand_he": product.get("brand_name_he"),
        "brand_en": product.get("brand_name_en"),
        "family_he": product.get("family_name_he"),
        "family_en": product.get("family_name_en"),
        "department_he": product.get("department_name"),
        "category_path_he": product.get("category_path_he"),
        "category_path_en": product.get("category_path_en"),
        "category_he": category_he,
        "subcategory_he": subcategory_he,
        "ingredients_he": product.get("ingredients_he"),
        "ingredients_en": product.get("ingredients_en"),
        "description_he": product.get("description_he"),
        "description_en": product.get("description_en"),
        "nutrition_raw": product.get("nutrition_facts"),
    }


def process_source(
    conn,
    source_name,
    source_file,
    is_source_of_truth,
    category_mapping,
):
    """Process one parsed product source."""
    logger.info(
        "Processing %s%s",
        source_name,
        " (source of truth)" if is_source_of_truth else "",
    )

    inserted = 0
    updated = 0
    skipped = 0
    invalid = 0

    for product in load_jsonl(source_file):
        item_code = get_item_code(product)

        if item_code is None:
            invalid += 1
            continue

        data = get_enrichment_data(
            product,
            category_mapping,
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM product_enrichment
                WHERE item_code = %s
                """,
                (item_code,),
            )
            exists = cur.fetchone() is not None

        if not exists:
            insert_product_enrichment(
                conn,
                item_code=item_code,
                source=source_name,
                source_file=str(source_file),
                **data,
            )
            inserted += 1

        else:
            update_product_enrichment_missing(
                conn,
                item_code=item_code,
                **data,
            )
            updated += 1

    conn.commit()

    logger.info(
        "%s completed: %s inserted, %s enriched, %s skipped, %s invalid",
        source_name,
        inserted,
        updated,
        skipped,
        invalid,
    )

    return inserted, updated, skipped, invalid


def main():
    parser = argparse.ArgumentParser(
        description="Load enriched products from parsed JSONL files."
    )

    parser.add_argument(
        "--source",
        required=True,
        help=(
            "Parsed folder to use as the source of truth, "
            "for example: --source 'tiv taam'"
        ),
    )

    args = parser.parse_args()

    setup_general_logging()

    if not CATEGORIES_PATH.is_file():
        raise SystemExit(
            f"Category mapping not found: {CATEGORIES_PATH}"
        )

    category_mapping = load_category_mapping()

    logger.info(
        "Loaded %s category mappings",
        len(category_mapping),
    )

    source_dir = PARSED_ROOT / args.source
    source_file = source_dir / "products_parsed.jsonl"

    if not source_file.is_file():
        raise SystemExit(
            f"Source file not found: {source_file}"
        )

    source_dirs = sorted(
        path
        for path in PARSED_ROOT.iterdir()
        if path.is_dir()
        and (path / "products_parsed.jsonl").is_file()
    )

    source_names = [path.name for path in source_dirs]

    if args.source not in source_names:
        raise SystemExit(
            f"Source folder not found under {PARSED_ROOT}: "
            f"{args.source}"
        )

    # Always process the selected source first.
    source_dirs.remove(source_dir)
    source_dirs.insert(0, source_dir)

    logger.info(
        "Starting enriched product load. Source of truth: %s",
        args.source,
    )

    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    total_invalid = 0

    with get_connection() as conn:
        for path in source_dirs:
            is_source_of_truth = path == source_dir

            inserted, updated, skipped, invalid = process_source(
                conn,
                path.name,
                path / "products_parsed.jsonl",
                is_source_of_truth,
                category_mapping,
            )

            total_inserted += inserted
            total_updated += updated
            total_skipped += skipped
            total_invalid += invalid

    logger.info(
        "Enriched product load completed: "
        "%s inserted, %s metadata updates, %s skipped, %s invalid",
        total_inserted,
        total_updated,
        total_skipped,
        total_invalid,
    )


if __name__ == "__main__":
    main()