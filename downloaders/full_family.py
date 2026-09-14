# downloaders/full_family.py
"""
Shared logic for "full" feed types (PriceFull, PromoFull): the latest
file per chain+store+day wins, and older same-day files for that store
are cleaned up after a successful new download.
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path

from downloaders.common import save_file, save_file_async
from utils.file_tracking.parser_file_tracking import parse_filename

logger = logging.getLogger(__name__)


def extract_time_suffix(filename: str) -> str:
    """
    Extract the time component from a full-file filename.

    Supports:
      YYYYMMDD-HHMMSS
      YYYYMMDD-HHMM
      YYYYMMDDHHMM
    """

    match = re.search(
        r"-(\d{8})-(\d+)(?:\.[^.]+)?$",
        filename,
    )

    if match:
        value = match.group(2)

    else:
        match = re.search(
            r"-(\d{8})(\d{4,6})(?:\.[^.]+)?$",
            filename,
        )

        if not match:
            return "000000"

        value = match.group(2)

    if len(value) == 3:
        return value + "000"

    if len(value) == 4:
        return value + "00"

    if len(value) == 6:
        return value

    return "000000"


def find_latest_full_files_per_store(
    files: list[dict],
    file_type: str,
    filename_key: str,
    date_key: str | None = None,
    date_format: str | None = None,
) -> dict[tuple, dict]:
    """
    Find the latest full-file (PriceFull/PromoFull) per chain, store and
    day. For sources where multiple such files exist for the same store
    on the same day, the latest timestamp wins.
    """

    latest: dict[tuple, dict] = {}
    today = date.today()

    for file in files:

        filename = (file.get(filename_key) or "").strip()

        if not filename:
            continue

        try:
            record = parse_filename(filename)
        except ValueError:
            continue

        if record["file_type"] != file_type:
            continue

        if record["store_id"] is None:
            continue

        if record["file_date"] != today:
            continue

        key = (record["chain_id"], record["store_id"])

        if date_key is not None:

            date_text = (file.get(date_key) or "").strip()

            if not date_text:
                continue

            try:
                sort_key = datetime.strptime(date_text, date_format)
            except ValueError:
                continue

        else:
            sort_key = (record["file_date"], extract_time_suffix(filename))

        if key not in latest or sort_key > latest[key]["sort_key"]:
            latest[key] = {
                **file,
                "filename": filename,
                "chain_id": record["chain_id"],
                "store_id": record["store_id"],
                "file_date": record["file_date"],
                "sort_key": sort_key,
            }

    return latest


def get_storage_path(
    chain_id: str,
    store_id: str,
    data_dir: Path,
    subfolder: str,
) -> Path:
    return data_dir / chain_id / store_id / subfolder


def _cleanup_old_same_day_files(
    folder: Path,
    keep_filename: str,
    file_date: date,
    file_type: str,
) -> None:
    """
    Remove older same-day full-files for this store, now that
    keep_filename has been written successfully.
    """

    for old_file in folder.glob(f"{file_type}*.gz"):

        if old_file.name == keep_filename:
            continue

        try:
            old_record = parse_filename(old_file.name)
        except ValueError:
            continue

        if old_record["file_date"] == file_date:
            logger.info("REMOVE OLD SAME DAY: %s", old_file.name)
            old_file.unlink()


def save_full_file(
    chain_id: str,
    store_id: str,
    filename: str,
    file_date: date,
    data_dir: Path,
    test: bool,
    fetch_content,
    file_type: str,
    subfolder: str,
) -> Path | None:

    folder = get_storage_path(chain_id, store_id, data_dir, subfolder)

    def cleanup(folder, filename):
        _cleanup_old_same_day_files(folder, filename, file_date, file_type)

    return save_file(folder, filename, test, fetch_content, cleanup=cleanup)


async def save_full_file_async(
    chain_id: str,
    store_id: str,
    filename: str,
    file_date: date,
    data_dir: Path,
    test: bool,
    fetch_content,
    file_type: str,
    subfolder: str,
) -> Path | None:

    folder = get_storage_path(chain_id, store_id, data_dir, subfolder)

    def cleanup(folder, filename):
        _cleanup_old_same_day_files(folder, filename, file_date, file_type)

    return await save_file_async(
        folder, filename, test, fetch_content, cleanup=cleanup,
    )