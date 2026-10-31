from pathlib import Path
import json
import re


BASE_DIR = Path(__file__).resolve().parents[2]

CHAINS_FILE = BASE_DIR / "data" / "reference" / "chains.json"
STORES_DIR = BASE_DIR / "data" / "stores"
REPORT_FILE = (
    BASE_DIR
    / "inspection"
    / "reports"
    / "store_brands_coverage.txt"
)


def normalize_for_search(value: str) -> str:
    value = value.casefold()

    # AMPM / AM-PM / AM PM / AmPm → ampm
    value = re.sub(r"am[\s-]*pm", "ampm", value)

    # General whitespace normalization.
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def main() -> None:
    with CHAINS_FILE.open(encoding="utf-8") as f:
        chains = json.load(f)

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with REPORT_FILE.open("w", encoding="utf-8") as report:
        for chain_id, chain in chains.items():
            brands = chain.get("brands", [])

            if not brands:
                continue

            chain_name = chain.get("name_en_normalized", "")
            stores_file = STORES_DIR / f"{chain_name}.json"

            if not stores_file.exists():
                report.write(
                    f"{chain_id} | {chain_name}\n"
                    f"  ERROR: {stores_file.name} not found\n\n"
                )
                continue

            with stores_file.open(encoding="utf-8") as f:
                stores = json.load(f)

            report.write(f"{chain_id} | {chain_name}\n")

            for brand in brands:
                normalized_brand = normalize_for_search(brand)

                matches = [
                    store
                    for store in stores
                    if normalized_brand
                    in normalize_for_search(store.get("name") or "")
                ]

                report.write(f"  {brand}: {len(matches)}\n")

                for store in matches:
                    report.write(
                        f"    {store.get('name', '')}"
                        f" | {store.get('city', '')}"
                        f" | {store.get('address', '')}"
                        f" | store_id={store.get('store_id', '')}\n"
                    )

            report.write("\n")

    print(f"Written: {REPORT_FILE}")


if __name__ == "__main__":
    main()