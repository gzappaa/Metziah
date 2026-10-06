"""Analyze store product coverage using the reference vocabulary."""

import json
import re
from pathlib import Path

from db import get_connection


REFERENCE_PATH = Path("data/reference/store_products.json")
REPORT_DIR = Path(__file__).resolve().parent / "reports"
REPORT_PATH = REPORT_DIR / "store_products_coverage.txt"


def load_vocabulary() -> list[dict]:
    with REFERENCE_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    vocabulary = []

    for category, names in data.items():
        for name in names:
            name = name.strip()

            if name:
                vocabulary.append(
                    {
                        "category": category,
                        "name": name,
                    }
                )

    return vocabulary


def get_words(name: str) -> list[str]:
    name = name.replace("/", " ")
    name = re.sub(r"[(),.'\"־–—-]", " ", name)

    return [
        word
        for word in name.split()
        if word
    ]


def analyze(
    vocabulary: list[dict],
) -> tuple[list[dict], set[tuple[str, str, str]]]:
    results = []
    covered_store_products = set()

    with get_connection() as conn:
        with conn.cursor() as cur:
            for entry in vocabulary:
                category = entry["category"]
                name = entry["name"]
                words = get_words(name)

                conditions = " AND ".join(
                    "name ILIKE %s"
                    for _ in words
                )

                params = [f"%{word}%" for word in words]

                cur.execute(
                    f"""
                    SELECT
                        chain_id,
                        store_id,
                        item_code
                    FROM store_products
                    WHERE {conditions}
                    """,
                    params,
                )

                rows = cur.fetchall()

                for chain_id, store_id, item_code in rows:
                    covered_store_products.add(
                        (chain_id, store_id, item_code)
                    )

                results.append(
                    {
                        "category": category,
                        "name": name,
                        "store_products": len(rows),
                        "chains": len({row[0] for row in rows}),
                        "stores": len(
                            {(row[0], row[1]) for row in rows}
                        ),
                    }
                )

    return results, covered_store_products


def write_report(
    vocabulary: list[dict],
    results: list[dict],
    covered_store_products: set[tuple[str, str, str]],
) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    total_store_products = sum(
        result["store_products"]
        for result in results
    )

    total_chains = len(
        {
            chain_id
            for chain_id, _, _ in covered_store_products
        }
    )

    total_stores = len(
        {
            (chain_id, store_id)
            for chain_id, store_id, _ in covered_store_products
        }
    )

    categories = sorted(
        {entry["category"] for entry in vocabulary}
    )

    with REPORT_PATH.open("w", encoding="utf-8") as f:
        f.write("Store Product Reference Vocabulary Coverage\n")
        f.write("=" * 90 + "\n\n")

        f.write(f"Categories: {len(categories):,}\n")
        f.write(f"Vocabulary entries: {len(vocabulary):,}\n")
        f.write(
            f"Sum of store_product matches: "
            f"{total_store_products:,}\n"
        )
        f.write(
            f"Distinct covered store_products: "
            f"{len(covered_store_products):,}\n"
        )
        f.write(f"Distinct covered chains: {total_chains:,}\n")
        f.write(f"Distinct covered stores: {total_stores:,}\n\n")

        f.write("=" * 90 + "\n")
        f.write("Coverage by category\n")
        f.write("=" * 90 + "\n\n")

        for category in categories:
            category_results = [
                result
                for result in results
                if result["category"] == category
            ]

            category_matches = sum(
                result["store_products"]
                for result in category_results
            )

            f.write(f"{category}\n")
            f.write("-" * 90 + "\n")
            f.write(
                f"Vocabulary entries: "
                f"{len(category_results):,}\n"
            )
            f.write(
                f"Sum of store_product matches: "
                f"{category_matches:,}\n\n"
            )

            f.write(
                f"{'Store Products':>15} "
                f"{'Chains':>8} "
                f"{'Stores':>8} "
                f"Name\n"
            )
            f.write("-" * 90 + "\n")

            for result in category_results:
                f.write(
                    f"{result['store_products']:>15,} "
                    f"{result['chains']:>8,} "
                    f"{result['stores']:>8,} "
                    f"{result['name']}\n"
                )

            f.write("\n")

        f.write("=" * 90 + "\n")
        f.write("All vocabulary entries\n")
        f.write("=" * 90 + "\n\n")

        f.write(
            f"{'Store Products':>15} "
            f"{'Chains':>8} "
            f"{'Stores':>8} "
            f"Category  Name\n"
        )
        f.write("-" * 90 + "\n")

        for result in results:
            f.write(
                f"{result['store_products']:>15,} "
                f"{result['chains']:>8,} "
                f"{result['stores']:>8,} "
                f"{result['category']}  "
                f"{result['name']}\n"
            )


def main() -> None:
    vocabulary = load_vocabulary()

    results, covered_store_products = analyze(vocabulary)

    write_report(
        vocabulary,
        results,
        covered_store_products,
    )

    print(
        f"Categories: "
        f"{len(set(e['category'] for e in vocabulary)):,}"
    )
    print(f"Vocabulary entries: {len(vocabulary):,}")
    print(f"Report written to: {REPORT_PATH}")


if __name__ == "__main__":
    main()