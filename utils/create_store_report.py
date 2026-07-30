import json
import asyncio
from pathlib import Path

from chains.machsenei_hashuk import MachseneiHashukScraper


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR  / "data"
REPORT_DIR = DATA_DIR / "reports"
REPORT_FILE = REPORT_DIR / "report.json"




async def main():

    scraper = MachseneiHashukScraper()
    stores = scraper.load_stores()


    # test one store first
    store = next(
        s for s in stores
        if s["store_id"] == "263"
    )


    products = await scraper.get_store_prices(
        store
    )


    report = {
        "store": {
            "id": store["store_id"],
            "name": store["store_name"],
            "address": store["address"],
            "city": store["city"]
        },

        "products": [
            {
                "item_code": product.item_code,
                "name": product.name,
                "price": product.price,
                "unit": product.unit
            }

            for product in products
        ]
    }


    with open(
        REPORT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=4
        )


    print("Report created")


if __name__ == "__main__":
    asyncio.run(main())