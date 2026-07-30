import asyncio

from chains.machsenei_hashuk import MachseneiHashukScraper


async def main():

    scraper = MachseneiHashukScraper()

    stores = scraper.load_stores()

    store = next(
        s for s in stores
        if s["store_id"] == "263"
    )

    products = await scraper.get_store_prices(store)

    print(products[:5])

asyncio.run(main())