
"""
Generate parsed product JSONL files from raw product JSON dumps.
"""

import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from parsers.product_page_type1 import iter_products as iter_type1_products
from parsers.product_json import iter_products
from parsers.product_page_type2 import iter_products as iter_type2_products

logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_PARSED_DIR = Path("data/parsed")
DEFAULT_TYPE1_RAW_DIR = Path("data/raw_product_pages/type_1")
OUTPUT_FILENAME = "products_parsed.jsonl"
TYPE1_OUTPUT_FILENAME = "products_parsed_type_1.jsonl"
DEFAULT_TYPE2_RAW_DIR = Path("data/raw_product_pages/type_2")
TYPE2_OUTPUT_FILENAME = "products_parsed_type_2.jsonl"


def _source_dir(source: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", source.strip().lower())
    return name.strip("_") or "unknown"


def generate(raw_dir: Path, parsed_dir: Path) -> None:
    company_dirs = sorted(path for path in raw_dir.iterdir() if path.is_dir())
    if not company_dirs:
        raise SystemExit(f"No sub-folders found in {raw_dir}")

    for company_dir in company_dirs:
        out_dir = parsed_dir / company_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / OUTPUT_FILENAME

        products = 0
        stats = {"barcodes_recovered": 0}

        with out_path.open("w", encoding="utf-8") as out_f:
            for path in sorted(company_dir.glob("*.json")):
                try:
                    for product in iter_products(path, stats=stats):
                        record = {
                            "company": company_dir.name,
                            "source_file": path.name,
                            **product,
                        }
                        out_f.write(
                            json.dumps(record, ensure_ascii=False) + "\n"
                        )
                        products += 1

                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    logger.warning("%s: failed to parse: %s", path, exc)

        logger.info(
            "%s: %d products | %d barcodes recovered -> %s",
            company_dir.name,
            products,
            stats["barcodes_recovered"],
            out_path,
        )


def generate_type1(raw_dir: Path, parsed_dir: Path) -> None:

    if not raw_dir.is_dir():
        raise SystemExit(f"Input directory not found: {raw_dir}")

    files = sorted(raw_dir.rglob("*.json"))
    if not files:
        raise SystemExit(f"No JSON files found in {raw_dir}")

    outputs = {}
    counts = defaultdict(int)
    errors = 0

    try:
        for path in files:
            try:
                for product in iter_type1_products(path):
                    source = _source_dir(product.get("source") or "unknown")
                    out_path = parsed_dir / source / TYPE1_OUTPUT_FILENAME

                    if out_path not in outputs:
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        outputs[out_path] = out_path.open("w", encoding="utf-8")

                    outputs[out_path].write(
                        json.dumps(product, ensure_ascii=False) + "\n"
                    )
                    counts[out_path] += 1

            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                errors += 1
                logger.warning("%s: failed to parse: %s", path, exc)

    finally:
        for file in outputs.values():
            file.close()

    for out_path, count in counts.items():
        print(f"{count} products -> {out_path}")

    print(f"Processed files: {len(files)} | errors: {errors}")

    if errors:
        raise SystemExit(1)


def generate_type2(raw_dir: Path, parsed_dir: Path) -> None:
    if not raw_dir.is_dir():
        raise SystemExit(f"Input directory not found: {raw_dir}")

    files = sorted(raw_dir.rglob("*.json"))
    if not files:
        raise SystemExit(f"No JSON files found in {raw_dir}")

    outputs = {}
    counts = defaultdict(int)
    errors = 0

    try:
        for path in files:
            try:
                for product in iter_type2_products(path):
                    # Expected layout: type_2/<company>/*.json
                    company = _source_dir(path.parent.name)

                    out_path = parsed_dir / company / TYPE2_OUTPUT_FILENAME

                    if out_path not in outputs:
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        outputs[out_path] = out_path.open(
                            "w", encoding="utf-8"
                        )

                    record = {
                        "company": company,
                        "source": company,
                        "source_file": path.name,
                        **product,
                    }

                    outputs[out_path].write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )
                    counts[out_path] += 1

            except (
                OSError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                errors += 1
                logger.warning("%s: failed to parse: %s", path, exc)

    finally:
        for file in outputs.values():
            file.close()

    for out_path, count in counts.items():
        logger.info("%d products -> %s", count, out_path)

    logger.info(
        "Processed files: %d | errors: %d",
        len(files),
        errors,
    )

    if errors:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate parsed product JSONL files"
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--parsed-dir", type=Path, default=DEFAULT_PARSED_DIR)
    parser.add_argument(
        "--type1",
        action="store_true",
        help="Process type_1 product-page JSON files only",
    )
    parser.add_argument(
    "--type2",
    action="store_true",
    help="Process type_2 product-page JSON files only",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process regular, type_1, and type_2 product JSON files",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if sum((args.type1, args.type2, args.all)) > 1:
        parser.error("--type1, --type2, and --all cannot be used together")

    if args.all:
        generate(args.raw_dir, args.parsed_dir)
        generate_type1(DEFAULT_TYPE1_RAW_DIR, args.parsed_dir)
        generate_type2(DEFAULT_TYPE2_RAW_DIR, args.parsed_dir)
    elif args.type1:
        generate_type1(DEFAULT_TYPE1_RAW_DIR, args.parsed_dir)
    elif args.type2:
        generate_type2(DEFAULT_TYPE2_RAW_DIR, args.parsed_dir)
    else:
        generate(args.raw_dir, args.parsed_dir)


if __name__ == "__main__":
    main()
