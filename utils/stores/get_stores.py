# utils/stores/get_stores.py

import gzip
import json
import logging
import re
import io
import zipfile
from dataclasses import asdict
from pathlib import Path

from lxml import etree

from models.store import Store
from logging_config import setup_general_logging, setup_isolated_logging


# Project root
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

FEEDS_DIR = DATA_DIR / "feeds"
STORES_DIR = DATA_DIR / "stores"

STORES_DIR.mkdir(parents=True, exist_ok=True)


setup_general_logging()

logger = logging.getLogger(__name__)
store_changes_logger = setup_isolated_logging("store_changes")


# Some feeds use "ChainID"/"StoreID", others use "ChainId"/"StoreId".
CHAIN_ID_TAGS = ("ChainID", "ChainId")
CHAIN_NAME_TAGS = ("ChainName",)
STORE_ID_TAGS = ("StoreID", "StoreId")
STORE_NAME_TAGS = ("StoreName",)
ADDRESS_TAGS = ("Address",)
CITY_TAGS = ("City",)
ZIP_TAGS = ("ZipCode",)

# Actual per-store records show up under either tag depending on feed.
STORE_ELEMENT_TAGS = ("Store", "SubChainStoreXMLObject")


def findtext_any(elem, tags) -> str | None:
    for tag in tags:
        val = elem.findtext(tag)
        if val is not None:
            return val
    return None


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


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def find_stores_file(chain_dir: Path) -> Path | None:

    stores_subdir = chain_dir / "stores"

    if not stores_subdir.exists():
        return None

    candidates = [
        p for p in stores_subdir.iterdir()
        if p.is_file()
        and p.name.lower().startswith("stores")
        and ":" not in p.name
    ]

    if not candidates:
        return None

    if len(candidates) > 1:
        logger.warning(
            "Multiple stores files found in %s, using most recent",
            stores_subdir,
        )
        candidates.sort(
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    return candidates[0]


def read_xml_content(path: Path) -> bytes:

    with open(path, "rb") as f:
        raw = f.read()

    # UTF-16 BOM -- lxml can parse this encoding natively as long as
    # we hand it the raw bytes untouched (including the BOM).
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw

    # Strip UTF-8 BOM if present -- some feeds are BOM-prefixed,
    # which would otherwise defeat the "<" sniff check below.
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    # Sniff real format from magic bytes.
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)

    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [
                n for n in zf.namelist()
                if n.lower().endswith(".xml")
            ]

            if not names:
                raise ValueError(
                    f"ZIP file {path.name} contains no .xml member"
                )

            if len(names) > 1:
                logger.warning(
                    "ZIP file %s has multiple .xml members, using %s",
                    path.name,
                    names[0],
                )

            return zf.read(names[0])

    if raw.lstrip()[:1] == b"<":
        return raw

    raise ValueError(
        f"Unrecognized file format for {path.name}"
    )


def find_store_elements(root):
    """
    Locate leaf-level store records regardless of feed shape.

    Some feeds:
        <Store><StoreID>...</StoreID>...</Store>

    Others:
        <Store>
            <SubChainStoreXMLObject>...</SubChainStoreXMLObject>
        </Store>

    Only elements containing a direct StoreID are returned.
    """

    seen = []

    for tag in STORE_ELEMENT_TAGS:
        for el in root.iter(tag):

            has_store_id = any(
                el.find(id_tag) is not None
                for id_tag in STORE_ID_TAGS
            )

            if has_store_id:
                seen.append(el)

    return seen


def parse_stores_xml(
    xml_content: bytes,
    fallback_chain_id: str,
):
    root = etree.fromstring(xml_content)

    chain_info = {
        "chain_id": (
            findtext_any(root, CHAIN_ID_TAGS)
            or fallback_chain_id
        ),
        "chain_name": findtext_any(
            root,
            CHAIN_NAME_TAGS,
        ),
        "last_update_date": root.findtext(
            "LastUpdateDate"
        ),
        "last_update_time": root.findtext(
            "LastUpdateTime"
        ),
    }

    store_elements = find_store_elements(root)

    stores: list[Store] = []

    for store in store_elements:
        stores.append(
            Store(
                chain_id=chain_info["chain_id"],
                store_id=findtext_any(
                    store,
                    STORE_ID_TAGS,
                ),
                name=findtext_any(
                    store,
                    STORE_NAME_TAGS,
                ),
                address=clean_address(
                    findtext_any(
                        store,
                        ADDRESS_TAGS,
                    )
                ),
                city=findtext_any(
                    store,
                    CITY_TAGS,
                ),
                zip_code=findtext_any(
                    store,
                    ZIP_TAGS,
                ),
            )
        )

    return chain_info, stores


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

            current_value = getattr(
                store,
                field,
            )

            previous_value = previous.get(
                field
            )

            if previous_value != current_value:
                changes.append(
                    f"CHANGED {store.store_id} "
                    f"{field}: "
                    f"{previous_value} -> "
                    f"{current_value}"
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


def main():

    for chain_dir in sorted(FEEDS_DIR.iterdir()):

        if not chain_dir.is_dir():
            continue

        chain_id_from_path = chain_dir.name

        stores_file = find_stores_file(chain_dir)

        if stores_file is None:
            logger.warning(
                "No stores file found for %s",
                chain_id_from_path,
            )
            continue

        logger.info(
            "Parsing %s",
            stores_file.name,
        )

        try:
            xml_content = read_xml_content(stores_file)

            chain_info, stores = parse_stores_xml(
                xml_content,
                chain_id_from_path,
            )

        except Exception:
            logger.exception(
                "Failed to parse %s",
                stores_file,
            )
            continue

        if not stores:
            logger.warning(
                "Parsed 0 stores for %s -- check schema variant",
                chain_id_from_path,
            )

        chain_name = (
            chain_info["chain_name"]
            or chain_id_from_path
        )

        safe_name = sanitize_filename(chain_name)

        output_file = STORES_DIR / f"{safe_name}.json"

        old_stores = load_existing(output_file)

        changes = compare_stores(
            old_stores,
            stores,
        )

        save_changes_log(
            safe_name,
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
            "Saved %d stores to %s",
            len(stores),
            output_file.name,
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
        main()

    except Exception:
        logger.exception(
            "Store update crashed"
        )
        raise