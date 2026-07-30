import asyncio
import json

from clients.laibcatalog import LaibcatalogClient


async def main():

    client = LaibcatalogClient(
        "7290661400001"
    )

    branches = await client.get_branches()

    stores = {
        str(branch["number"]): branch["name"]
        for branch in branches
    }

    print(json.dumps(
        stores,
        ensure_ascii=False,
        indent=2
    ))

    with open(
        "machsenei_hashuk_stores.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            stores,
            f,
            ensure_ascii=False,
            indent=2
        )


if __name__ == "__main__":
    asyncio.run(main())