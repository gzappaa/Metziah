"""
inspection/scrapers/check_product_categories.py

Inspect category hierarchies from parsed product JSONL files.

Scans:
    data/parsed/*/products_parsed.jsonl

Generates:
    inspection/reports/product_categories.txt

The report contains:
    1. Level 1 categories
    2. Level 2 categories
    3. Level 1 / Level 2 combinations
"""

import json
import logging
from collections import Counter
from pathlib import Path

from logging_config import setup_general_logging


logger = logging.getLogger(__name__)


PARSED_ROOT = Path("data/parsed")
REPORT_PATH = Path("inspection/reports/product_categories.txt")


def load_categories(path):
    """Yield category paths from a parsed JSONL file."""
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

            category_path = product.get("category_path_he")

            if not isinstance(category_path, list):
                continue

            yield category_path


def collect_categories():
    """Collect category statistics from all parsed product files."""
    level_1 = Counter()
    level_2 = Counter()
    combinations = Counter()

    files = sorted(PARSED_ROOT.glob("*/products_parsed.jsonl"))

    total_products = 0

    for path in files:
        logger.info("Processing %s", path)

        for category_path in load_categories(path):
            total_products += 1

            if len(category_path) >= 1 and category_path[0]:
                category_1 = category_path[0]
                level_1[category_1] += 1

            if len(category_path) >= 2 and category_path[1]:
                category_2 = category_path[1]
                level_2[category_2] += 1

            if len(category_path) >= 2:
                category_1 = category_path[0]
                category_2 = category_path[1]

                if category_1 and category_2:
                    combinations[(category_1, category_2)] += 1

    return level_1, level_2, combinations, total_products, len(files)


def build_report(
    level_1,
    level_2,
    combinations,
    total_products,
    file_count,
):
    """Build the category inspection report."""
    lines = []

    lines.append("PRODUCT CATEGORY INSPECTION")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Parsed files: {file_count}")
    lines.append(f"Products inspected: {total_products}")
    lines.append("")

    lines.append("LEVEL 1 CATEGORIES")
    lines.append("-" * 80)
    lines.append(f"Unique categories: {len(level_1)}")
    lines.append("")

    for category, count in sorted(
        level_1.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"{category}: {count}")

    lines.append("")
    lines.append("LEVEL 2 CATEGORIES")
    lines.append("-" * 80)
    lines.append(f"Unique categories: {len(level_2)}")
    lines.append("")

    for category, count in sorted(
        level_2.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"{category}: {count}")

    lines.append("")
    lines.append("LEVEL 1 / LEVEL 2 COMBINATIONS")
    lines.append("-" * 80)
    lines.append(f"Unique combinations: {len(combinations)}")
    lines.append("")

    for (category_1, category_2), count in sorted(
        combinations.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"{category_1} / {category_2}: {count}")

    lines.append("")

    return "\n".join(lines)


def main():
    """Run the category inspection."""
    setup_general_logging()

    if not PARSED_ROOT.is_dir():
        raise SystemExit(
            f"Parsed directory not found: {PARSED_ROOT}"
        )

    (
        level_1,
        level_2,
        combinations,
        total_products,
        file_count,
    ) = collect_categories()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    report = build_report(
        level_1,
        level_2,
        combinations,
        total_products,
        file_count,
    )

    REPORT_PATH.write_text(report, encoding="utf-8")

    logger.info(
        "Category inspection completed: "
        "%s level 1, %s level 2, %s combinations",
        len(level_1),
        len(level_2),
        len(combinations),
    )
    logger.info("Report written to %s", REPORT_PATH)


if __name__ == "__main__":
    main()