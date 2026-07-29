from clients.laibcatalog import LaibcatalogClient
import gzip


class MahsaneiAshukScraper:

    def __init__(self):

        self.client = LaibcatalogClient(
            "7290661400001"
        )


    async def scrape(self):

        files = await self.client.get_files(
            "7290661400001"
        )

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
        print(xml_content[:1000])


        return xml_content