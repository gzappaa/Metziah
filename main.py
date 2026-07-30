import asyncio
import pandas as pd

from chains.machsenei_hashuk import MachseneiHashukScraper


async def main():

    scraper = MachseneiHashukScraper()

    products = await scraper.scrape()

    df = pd.DataFrame(
        [product.__dict__ for product in products]
    )

    df.to_csv(
        "machsenei_hashuk_prices.csv",
        index=False,
        encoding="utf-8-sig"
    )


if __name__ == "__main__":
    asyncio.run(main())