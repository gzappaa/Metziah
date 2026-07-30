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


    async def scrape(self):

        files = await self.client.get_files()

        urls = []

        for file in files:

            url = self.client.build_download_url(
                file["fileName"]
            )

            urls.append(url)


        # choose one price file
        price_url = next(
            url for url in urls
            if "/Price" in url
        )

        print("Downloading:")
        print(price_url)


        # download gzip file
        content = await self.client.download_file(
            price_url
        )


        # decompress gzip -> XML bytes
        xml_content = gzip.decompress(content)


        # inspect XML
        products = self.parser.parse_price_file(
    xml_content
)

        return products

    def load_stores(self):

        with open(
            "data/stores.json",
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)




    async def find_price_file(self, store):

        files = await self.client.get_files()

        price_files = []

        for file in files:

            filename = file["fileName"]

            if (
                "PriceFull" in filename
                and f"-{store['sub_chain_id']}-{store['store_id']}-" in filename
            ):
                price_files.append(filename)


        if not price_files:
            return None


        latest = max(
            price_files,
            key=lambda x: self.extract_timestamp(x)
        )

        return latest


    def extract_timestamp(self, filename):

        # PriceFull7290661400001-003-263-20260730-191226.gz

        parts = filename.replace(".gz", "").split("-")

        date = parts[-2]
        time = parts[-1]

        return datetime.strptime(
            date + time,
            "%Y%m%d%H%M%S"
        )


    async def get_store_prices(self, store):

        filename = await self.find_price_file(store)

        url = self.client.build_download_url(
            filename
        )

        content = await self.client.download_file(
            url
        )

        xml_content = gzip.decompress(content)

        products = self.parser.parse_price_file(
            xml_content
        )

        return products