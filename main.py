import asyncio

from chains.machsenei_hashuk import MachseneiHashukScraper


async def find_price_file(self, store):

    files = await self.client.get_files(
        branch_number=store["store_id"]
    )


    price_files = [
        file["fileName"]
        for file in files
        if "PriceFull" in file["fileName"]
    ]


    if not price_files:
        print("No PriceFull found:")
        print(store)
        return None


    # return newest file
    price_files.sort(
        reverse=True
    )

    return price_files[0]