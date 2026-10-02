"""

utils/processing/generate_product_jsonl.py

Generate parsed product JSON files from raw product JSON dumps.

"""

import argparse
import json
import logging
from pathlib import Path

from parsers.product_json import iter_products

logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_PARSED_DIR = Path("data/parsed")
OUTPUT_FILENAME = "products_parsed.jsonl"


def generate(raw_dir: Path, parsed_dir: Path) -> None:
    company_dirs = sorted(path for path in raw_dir.iterdir() if path.is_dir())
    if not company_dirs:
        raise SystemExit(f"No sub-folders found in {raw_dir}")

    for company_dir in company_dirs:
        out_dir = parsed_dir / company_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / OUTPUT_FILENAME

        products = 0

        with out_path.open("w", encoding="utf-8") as out_f:
            for path in sorted(company_dir.glob("*.json")):
                try:
                    for product in iter_products(path):
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

        print(f"{company_dir.name}: {products} products -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate parsed product JSONL files"
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
    )
    parser.add_argument(
        "--parsed-dir",
        type=Path,
        default=DEFAULT_PARSED_DIR,
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    generate(args.raw_dir, args.parsed_dir)


if __name__ == "__main__":
    main()