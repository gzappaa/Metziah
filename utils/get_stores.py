import asyncio
import gzip
import json

from clients.laibcatalog import LaibcatalogClient
from lxml import etree
from pathlib import Path


Path(__file__).resolve().parent.parent
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORES_FILE = DATA_DIR / "stores.json"

CHAIN_ID = "7290661400001"


async def get_stores():

    client = LaibcatalogClient(CHAIN_ID)


    # get available files
    files = await client.get_files()


    # find stores XML
    store_file = next(
        file for file in files
        if "Stores" in file["fileName"]
    )


    print("Downloading:")
    print(store_file["fileName"])


    # download
    url = client.build_download_url(
        store_file["fileName"]
    )

    content = await client.download_file(url)


    # gzip -> xml
    xml_content = gzip.decompress(content)


    root = etree.fromstring(xml_content)


    stores = []


    for subchain in root.findall(".//SubChain"):

        sub_chain_id = subchain.findtext(
            "SubChainId"
        )


        for store in subchain.findall(
            ".//Store"
        ):

            stores.append(
                {
                    "sub_chain_id": sub_chain_id,
                    "store_id": store.findtext("StoreID"),
                    "store_name": store.findtext("StoreName"),
                    "address": store.findtext("Address"),
                    "city": store.findtext("City"),
                    "zip_code": store.findtext("ZipCode"),
                }
            )


    return stores



async def main():

    stores = await get_stores()


    with open(
        STORES_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            stores,
            f,
            ensure_ascii=False,
            indent=4
        )


    print(
        f"Saved {len(stores)} stores"
    )



if __name__ == "__main__":
    asyncio.run(main())