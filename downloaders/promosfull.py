import asyncio
import re

from pathlib import Path
from datetime import datetime

from clients.laibcatalog import LaibcatalogClient


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "feeds"

CHAIN_ID = "7290661400001"


FILENAME_PATTERN = re.compile(
    r"PromoFull"
    r"(?P<chain>\d+)-"
    r"(?P<subchain>\d+)-"
    r"(?P<store>\d+)-"
    r"(?P<date>\d{8})-"
    r"(?P<time>\d{6})\.gz"
)



def parse_filename(filename):

    match = FILENAME_PATTERN.match(filename)

    if not match:
        return None

    return match.groupdict()



def get_storage_path(meta):

    return (
        DATA_DIR
        / meta["chain"]
        / meta["subchain"]
        / meta["store"]
        / "promosfull"
    )



async def download_promofull():

    client = LaibcatalogClient(CHAIN_ID)

    print("Getting files from API...")

    files = await client.get_files()


    promofull_files = [
        f["fileName"]
        for f in files
        if f["fileName"].startswith("PromoFull")
    ]


    print(
        f"Found {len(promofull_files)} PromoFull files"
    )


    latest_files = {}


    for filename in promofull_files:

        meta = parse_filename(filename)

        if not meta:
            continue


        store_key = (
            meta["chain"],
            meta["subchain"],
            meta["store"],
            meta["date"],
        )


        file_datetime = datetime.strptime(
            meta["date"] + meta["time"],
            "%Y%m%d%H%M%S"
        )


        if (
            store_key not in latest_files
            or file_datetime > latest_files[store_key][0]
        ):

            latest_files[store_key] = (
                file_datetime,
                filename,
                meta
            )



    print(
        f"Keeping {len(latest_files)} latest PromoFull files"
    )


    downloaded = 0
    skipped = 0


    for _, filename, meta in latest_files.values():

        folder = get_storage_path(meta)

        folder.mkdir(
            parents=True,
            exist_ok=True
        )


        destination = folder / filename



        if destination.exists():

            print(
                "UP TO DATE:",
                filename
            )

            skipped += 1
            continue



        # remove same-day older PromoFull
        for old_file in folder.glob(
            "PromoFull*.gz"
        ):

            old_meta = parse_filename(
                old_file.name
            )


            if (
                old_meta
                and old_meta["date"] == meta["date"]
            ):

                print(
                    "REMOVE OLD SAME DAY:",
                    old_file.name
                )

                old_file.unlink()



        print(
            "DOWNLOAD:",
            filename
        )


        url = client.build_download_url(
            filename
        )


        content = await client.download_file(
            url
        )


        destination.write_bytes(
            content
        )


        downloaded += 1



    print("\nFinished")
    print(
        "Downloaded:",
        downloaded
    )
    print(
        "Skipped:",
        skipped
    )



if __name__ == "__main__":

    asyncio.run(
        download_promofull()
    )