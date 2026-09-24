# utils/stores/normalize_store_cities.py

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
STORES_DIR = PROJECT_ROOT / "data" / "stores"
LOCALITIES_FILE = PROJECT_ROOT / "data" / "reference" / "cbs_localities.json"


def load_localities() -> dict[str, str]:
    """Load CBS locality codes and Hebrew names from the local reference file."""
    with LOCALITIES_FILE.open("r", encoding="utf-8") as f:
        localities = json.load(f)

    mapping = {}

    for locality in localities:
        locality_id = locality.get("ID", {}).get("id")
        name_heb = locality.get("name_heb")

        if locality_id is None or not name_heb:
            continue

        mapping[str(locality_id)] = name_heb

    return mapping


def normalize_stores(city_mapping: dict[str, str]) -> None:
    """Replace CBS city codes in store JSON files with Hebrew city names."""
    total = 0
    changed = 0
    skipped = 0

    for path in sorted(STORES_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            stores = json.load(f)

        file_changed = False

        for store in stores:
            total += 1

            city = store.get("city")

            if city is None:
                skipped += 1
                continue

            city_code = str(city)

            if city_code not in city_mapping:
                skipped += 1
                continue

            city_name = city_mapping[city_code]

            if city == city_name:
                continue

            print(
                f'{path.name}: '
                f'store={store.get("store_id")} '
                f'"{city}" -> "{city_name}"'
            )

            store["city"] = city_name

            changed += 1
            file_changed = True

        if file_changed:
            with path.open("w", encoding="utf-8") as f:
                json.dump(
                    stores,
                    f,
                    ensure_ascii=False,
                    indent=4,
                )
                f.write("\n")

    print()
    print("=" * 60)
    print("CITY NORMALIZATION COMPLETE")
    print("=" * 60)
    print(f"Stores processed: {total}")
    print(f"Cities changed:   {changed}")
    print(f"Skipped:          {skipped}")
    print("=" * 60)


def main():
    print(f"Loading CBS localities from {LOCALITIES_FILE}...")

    city_mapping = load_localities()

    print(f"CBS localities loaded: {len(city_mapping)}")
    print()

    normalize_stores(city_mapping)


if __name__ == "__main__":
    main()