# downloaders/delta_family.py
"""
Shared logic for "delta" feed types (Price, Promo): every matching file
published today is downloaded, with no per-store dedup and no cleanup
of older files — each delta file is its own distinct, timestamped
snapshot rather than a "latest wins" full replacement.
"""

import logging
from datetime import date
from pathlib import Path

from downloaders.common import save_file, save_file_async
from utils.file_tracking.parser_file_tracking import parse_filename

logger = logging.getLogger(__name__)


def find_delta_files(
    files: list[dict],
    file_type: str,
    filename_key: str,
) -> list[dict]:
    """Find all delta files (Price/Promo) published today."""

    delta_files = []
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

        delta_files.append(
            {
                **file,
                "filename": filename,
                "chain_id": record["chain_id"],
                "store_id": record["store_id"],
                "file_date": record["file_date"],
            }
        )

    return delta_files


def get_storage_path(
    chain_id: str,
    store_id: str,
    data_dir: Path,
    subfolder: str,
) -> Path:
    return data_dir / chain_id / store_id / subfolder


def save_delta_file(
    chain_id: str,
    store_id: str,
    filename: str,
    file_date: date,
    data_dir: Path,
    test: bool,
    fetch_content,
    subfolder: str,
) -> Path | None:

    folder = get_storage_path(chain_id, store_id, data_dir, subfolder)
    return save_file(folder, filename, test, fetch_content)


async def save_delta_file_async(
    chain_id: str,
    store_id: str,
    filename: str,
    file_date: date,
    data_dir: Path,
    test: bool,
    fetch_content,
    subfolder: str,
) -> Path | None:

    folder = get_storage_path(chain_id, store_id, data_dir, subfolder)
    return await save_file_async(folder, filename, test, fetch_content)