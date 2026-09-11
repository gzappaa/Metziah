import csv
import json
from pathlib import Path


CHAIN_ID = "7290000000003"

CSV_FILE = Path("data/reference/city_market_claude_addresses.csv")
STORES_FILE = Path("data/stores/city market 2.json")


def main():
    updates = {}

    with CSV_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            if row["chain_id"].strip() != CHAIN_ID:
                continue

            if row["status"].strip() != "OK":
                continue

            store_id = row["store_id"].strip()
            address = row["address"].strip()
            city = row["city"].strip()

            if not address or not city:
                continue

            updates[store_id] = {
                "address": address,
                "city": city,
            }

    print(f"Found {len(updates)} OK City Market stores.")

    with STORES_FILE.open("r", encoding="utf-8") as f:
        stores = json.load(f)

    updated = 0
    not_found = []

    json_store_ids = {
        str(store["store_id"]).strip()
        for store in stores
    }

    for store in stores:
        store_id = str(store["store_id"]).strip()

        if store_id not in updates:
            continue

        store["address"] = updates[store_id]["address"]
        store["city"] = updates[store_id]["city"]
        updated += 1

    for store_id in updates:
        if store_id not in json_store_ids:
            not_found.append(store_id)

    with STORES_FILE.open("w", encoding="utf-8") as f:
        json.dump(stores, f, ensure_ascii=False, indent=4)
        f.write("\n")

    print(f"Updated: {updated}")

    if not_found:
        print("CSV store IDs not found in citymarket.json:")
        for store_id in not_found:
            print(f"  {store_id}")


if __name__ == "__main__":
    main()