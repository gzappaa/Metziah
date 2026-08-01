import asyncio
from pathlib import Path

from clients.laibcatalog import LaibcatalogClient


BASE_DIR = Path(__file__).resolve().parent.parent

DOWNLOAD_DIR = BASE_DIR / "data" / "xml_samples"

CHAIN_ID = "7290661400001"



async def download_files():

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    client = LaibcatalogClient(CHAIN_ID)


    print("Fetching file list...")

    files = await client.get_files()


    print(
        f"Found {len(files)} files"
    )


    downloaded = 0
    skipped = 0
    failed = 0


    for item in files:

        filename = (
            item.get("fileName")
            or
            item.get("FileName")
        )


        if not filename:
            continue


        if not filename.endswith(".gz"):
            continue


        path = DOWNLOAD_DIR / filename


        if path.exists():

            skipped += 1

            continue



        print(
            "Downloading:",
            filename
        )


        try:

            url = client.build_download_url(
                filename
            )


            data = await client.download_file(
                url
            )


            path.write_bytes(data)


            downloaded += 1


        except Exception as e:

            failed += 1

            print(
                "FAILED:",
                filename,
                e
            )



    print("\nFinished")
    print("Downloaded:", downloaded)
    print("Skipped:", skipped)
    print("Failed:", failed)



async def main():

    await download_files()



if __name__ == "__main__":

    asyncio.run(main())