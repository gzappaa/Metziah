import asyncio
import gzip
import json
import logging
import re

from dataclasses import asdict
from pathlib import Path

from lxml import etree

from chains.registry import CHAINS
from clients.laibcatalog import LaibcatalogClient
from models.store import Store
from logging_config import setup_general_logging, setup_isolated_logging


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

STORES_DIR = DATA_DIR / "stores"

STORES_DIR.mkdir(parents=True, exist_ok=True)


setup_general_logging()

logger = logging.getLogger(__name__)
store_changes_logger = setup_isolated_logging("store_changes")


def clean_address(address: str | None) -> str | None:
    if not address:
        return None

    address = re.sub(
        r"https?://\S*",
        "",
        address,
        flags=re.IGNORECASE,
    )

    address = re.sub(
        r"\bhttps?\b",
        "",
        address,
        flags=re.IGNORECASE,
    )

    address = re.sub(
        r"\s+",
        " ",
        address,
    )

    return address.strip()


async def get_stores(chain_id: str):

    client = LaibcatalogClient(chain_id)

    files = await client.get_files()

    store_file = next(
        file
        for file in files
        if "Stores" in file["fileName"]
    )

    logger.info(
        "Downloading %s",
        store_file["fileName"],
    )

    url = client.build_download_url(
        store_file["fileName"]
    )

    content = await client.download_file(url)

    xml_content = gzip.decompress(content)

    root = etree.fromstring(xml_content)

    stores: list[Store] = []

    for subchain in root.findall(".//SubChain"):

        for store in subchain.findall(".//Store"):

            stores.append(
                Store(
                    chain_id=chain_id,
                    store_id=store.findtext("StoreID"),
                    name=store.findtext("StoreName"),
                    address=clean_address(
                        store.findtext("Address")
                    ),
                    city=store.findtext("City"),
                    zip_code=store.findtext("ZipCode"),
                )
            )

    return stores


def load_existing(path: Path):

    if not path.exists():
        return {}

    with open(path, encoding="utf-8") as f:
        stores = json.load(f)

    return {
        store["store_id"]: store
        for store in stores
    }


def compare_stores(old, new):

    changes = []

    old_ids = set(old.keys())

    new_ids = {
        store.store_id
        for store in new
    }

    for store_id in new_ids - old_ids:

        changes.append(
            f"NEW STORE: {store_id}"
        )

    for store_id in old_ids - new_ids:

        changes.append(
            f"REMOVED STORE: {store_id}"
        )

    for store in new:

        if store.store_id not in old:
            continue

        previous = old[store.store_id]

        fields = [
            "name",
            "address",
            "city",
            "zip_code",
        ]

        for field in fields:

            if previous.get(field) != getattr(store, field):

                changes.append(
                    f"CHANGED {store.store_id} "
                    f"{field}: "
                    f"{previous.get(field)} -> "
                    f"{getattr(store, field)}"
                )

    return changes


def save_changes_log(chain_key, changes):

    if not changes:
        return

    store_changes_logger.info(
        "CHAIN: %s | %d change(s)",
        chain_key,
        len(changes),
    )

    for change in changes:
        store_changes_logger.info(change)


async def main():

    for chain_key, config in CHAINS.items():

        logger.info(
            "Processing %s",
            config.name,
        )

        output_file = STORES_DIR / f"{chain_key}.json"

        old_stores = load_existing(
            output_file
        )

        stores = await get_stores(
            config.chain_id
        )

        changes = compare_stores(
            old_stores,
            stores,
        )

        save_changes_log(
            chain_key,
            changes,
        )

        with open(
            output_file,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                [asdict(store) for store in stores],
                f,
                ensure_ascii=False,
                indent=4,
            )

        logger.info(
            "Saved %d stores",
            len(stores),
        )

        if changes:
            logger.info(
                "Found %d changes",
                len(changes),
            )
        else:
            logger.info("No changes")


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except Exception:
        logger.exception(
            "Store update crashed"
        )
        raise