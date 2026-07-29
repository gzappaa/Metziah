import asyncio

from chains.mahsanei_ashuk import MahsaneiAshukScraper


async def main():

    scraper = MahsaneiAshukScraper()

    products = await scraper.scrape()

    print(products[:5])


asyncio.run(main())