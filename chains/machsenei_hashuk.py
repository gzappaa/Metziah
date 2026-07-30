from clients.laibcatalog import LaibcatalogClient
import gzip
from parsers.xml import MachseneiXmlParser


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