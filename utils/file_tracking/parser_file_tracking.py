# utils/file_tracking/filename_parser.py

import logging
import re
from datetime import date, datetime
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

FEEDS_DIR = (
    BASE_DIR / "data" / "test_feeds"
    if settings.ENV == "test"
    else BASE_DIR / "data" / "feeds"
)


FILE_TYPE_PATTERN = re.compile(
    r"^(?P<file_type>PriceFull|Price|PromoFull|Promo|StoresFull|Stores)",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<date>\d{8})"
)

CHAIN_ID_PATTERN = re.compile(
    r"^(?:PriceFull|Price|PromoFull|Promo|StoresFull|Stores)"
    r"(?P<chain_id>\d{13})",
    re.IGNORECASE,
)

STORE_IDS_PATTERN = re.compile(
    r"(?P<ids>\d+(?:-\d+)*)-(?=\d{8})"
)

GENERIC_STORES_FILE_RE = re.compile(
    r"^Stores(?:Full)?"
    r"(?P<chain_id>\d{13})"
    r"(?:-\d+)*-"
    r"(?P<date>\d{8})"
    r"-?(?P<time>\d{3,6})"
    r"(?:-\d{3,6})?"
    r"(?:\.(?:gz|xml(?:\.gz)?))?$",
    re.IGNORECASE,
)


def parse_filename(filename: str) -> dict:
    file_type_match = FILE_TYPE_PATTERN.match(filename)

    if not file_type_match:
        raise ValueError(
            f"Unrecognized file type: {filename}"
        )

    file_date = None

    for match in DATE_PATTERN.finditer(filename):
        value = match.group("date")

        try:
            file_date = datetime.strptime(
                value,
                "%Y%m%d",
            ).date()
            break
        except ValueError:
            continue

    if file_date is None:
        raise ValueError(
            f"No valid YYYYMMDD date found in filename: {filename}"
        )

    chain_match = CHAIN_ID_PATTERN.match(filename)

    if not chain_match:
        raise ValueError(
            f"No chain ID found in filename: {filename}"
        )

    file_type = file_type_match.group("file_type").lower()

    if file_type == "storesfull":
        file_type = "stores"

    file_type = {
        "pricefull": "PriceFull",
        "price": "Price",
        "promofull": "PromoFull",
        "promo": "Promo",
        "stores": "Stores",
    }[file_type]

    sub_chain_id = None
    store_id = None

    if file_type == "Stores":
        if not GENERIC_STORES_FILE_RE.match(filename):
            raise ValueError(
                f"Invalid Stores filename format: {filename}"
            )

    else:
        store_match = STORE_IDS_PATTERN.search(filename)

        if not store_match:
            raise ValueError(
                f"Could not extract sub-chain/store ID: {filename}"
            )

        ids = store_match.group("ids").split("-")

        # One numeric component before the date is ALWAYS the store ID.
        if len(ids) == 1:
            store_id = ids[0]

        # With multiple components, the final component is the store ID
        # and the component immediately before it is the sub-chain ID.
        else:
            sub_chain_id = ids[-2]
            store_id = ids[-1]

    return {
        "chain_id": chain_match.group("chain_id"),
        "sub_chain_id": sub_chain_id,
        "store_id": store_id,
        "file_type": file_type,
        "filename": filename,
        "file_date": file_date,
    }


def get_local_path(record: dict) -> Path:
    file_type_dirs = {
        "Price": "prices",
        "PriceFull": "pricesfull",
        "Promo": "promos",
        "PromoFull": "promosfull",
    }

    if record["file_type"] == "Stores":
        return (
            FEEDS_DIR
            / record["chain_id"]
            / "stores"
            / record["filename"]
        )

    return (
        FEEDS_DIR
        / record["chain_id"]
        / record["sub_chain_id"]
        / record["store_id"]
        / file_type_dirs[record["file_type"]]
        / record["filename"]
    )


def normalize_file(
    filename: str,
    file_size: int | None = None,
) -> dict | None:
    try:
        record = parse_filename(filename)
    except ValueError as exc:
        logger.warning("%s", exc)
        return None

    if record["file_date"] != date.today():
        return None

    record["file_size"] = file_size
    record["downloaded"] = get_local_path(record).exists()

    return record