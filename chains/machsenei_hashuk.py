from clients.laibcatalog import LaibcatalogClient
import gzip
from parsers.xml import MachseneiXmlParser
import json
from datetime import datetime


class MachseneiHashukScraper:

    def __init__(self):

        self.client = LaibcatalogClient(
            "7290661400001"
        )

        self.parser = MachseneiXmlParser()



    def load_stores(self):

        with open(
            "data/stores.json",
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)



    def extract_timestamp(self, filename):

        # PriceFull7290661400001-003-263-20260730-191226.gz

        parts = filename.replace(".gz", "").split("-")

        date = parts[-2]
        time = parts[-1]

        return datetime.strptime(
            date + time,
            "%Y%m%d%H%M%S"
        )


 
    async def find_price_file(self, store):

        files = await self.client.get_files()


        price_files = [
            file["fileName"]
            for file in files
            if (
                "PriceFull" in file["fileName"]
                and f"-{store['store_id']}-" in file["fileName"]
            )
        ]


        if not price_files:
            return None


        price_files.sort(
            key=self.extract_timestamp,
            reverse=True
        )


        return price_files[0]


    async def get_store_prices(self, store):

        filename = await self.find_price_file(store)

        if filename is None:
            raise Exception(
                f"No PriceFull found for {store['store_id']}"
            )

        url = self.client.build_download_url(
            filename
        )

        content = await self.client.download_file(
            url
        )

        xml_content = gzip.decompress(
            content
        )

        return self.parser.parse_price_file(
            xml_content
        )