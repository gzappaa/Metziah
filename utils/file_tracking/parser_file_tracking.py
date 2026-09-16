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
    r"^(?P<file_type>PriceFull|Price|PromoFull|Promo|StoresFull|Stores)"
    r"(?P<chain_id>\d{13})"
    r"(?P<ids>(?:-\d+)*)"
    r"-(?P<date>20\d{6})"
    r"(?P<suffix>.*)$",
    re.IGNORECASE,
)


def parse_filename(filename: str) -> dict:
    match = FILE_TYPE_PATTERN.match(filename)

    if not match:
        raise ValueError(
            f"Unrecognized filename structure: {filename}"
        )

    file_type = match.group("file_type").lower()

    if file_type == "storesfull":
        file_type = "stores"

    file_type = {
        "pricefull": "PriceFull",
        "price": "Price",
        "promofull": "PromoFull",
        "promo": "Promo",
        "stores": "Stores",
    }[file_type]

    chain_id = match.group("chain_id")
    ids_text = match.group("ids")
    date_text = match.group("date")

    try:
        file_date = datetime.strptime(
            date_text,
            "%Y%m%d",
        ).date()
    except ValueError:
        raise ValueError(
            f"Invalid YYYYMMDD date in filename: {filename}"
        )

    # Remove the leading "-" and split numeric components.
    ids = ids_text.lstrip("-").split("-") if ids_text else []

    sub_chain_id = None
    store_id = None

    if file_type != "Stores":

        if not ids:
            raise ValueError(
                f"Missing store/sub-chain ID in filename: {filename}"
            )

        if len(ids) == 1:
            store_id = ids[0]
        else:
            sub_chain_id = ids[-2]
            store_id = ids[-1]

    return {
        "chain_id": chain_id,
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


def extract_time_suffix(filename: str) -> str:
    """
    Extract the time component from a feed filename.

    Supports filenames with either HHMMSS or shorter HHMM-style
    suffixes and normalizes the result to six digits for chronological
    comparison.
    """
    match = re.search(
        r"-(\d{8})(?:-?(\d+))?(?:\.[^.]+)?$",
        filename,
    )

    if not match:
        return "000000"

    value = match.group(2) or ""

    if len(value) == 1:
        return value + "00000"
    if len(value) == 2:
        return value + "0000"
    if len(value) == 3:
        return value + "000"
    if len(value) == 4:
        return value + "00"
    if len(value) == 5:
        return value + "0"
    if len(value) == 6:
        return value

    return "000000"