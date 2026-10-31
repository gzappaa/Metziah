"""
utils/file_tracking/load_file_tracking.py

Discovers today's published feed files across all Metziah source protocols
and updates the file_tracking database table.

Handles:
- Source-specific file discovery and normalization
- Optional remote file-size retrieval
- Local downloaded-state detection
- CSV report generation
- Deduplication and database insertion
- Advisory locking to prevent concurrent file-tracking runs
- CLI options for report generation and quick/slow size collection
"""

import argparse
import asyncio
import csv
import logging
import re
from datetime import date
from pathlib import Path

from config import settings
from database.repository import get_publishing_sources, insert_file_tracking
from db import get_connection
from logging_config import setup_general_logging

from clients.publishedprices import PublishedPricesClient
from clients.binaprojects import BinaProjectsClient
from clients.laibcatalog import LaibcatalogClient
from clients.carrefour import CarrefourClient
from clients.mishnatyosef import MishnatYosefClient
from clients.wolt import WoltClient

from downloaders.common import (
    list_publishedprices_entries_recursive,
    normalize_store_id,
)

from .parser_file_tracking import parse_filename, normalize_file
from .add_sizes_file_tracking import (
    get_file_size,
    get_file_size_get,
    parse_file_size,
)
from .cache import refresh_html_caches

setup_general_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]

FEEDS_DIR = (
    BASE_DIR / "data" / "test_feeds"
    if settings.ENV == "test"
    else BASE_DIR / "data" / "feeds"
)

REPORTS_DIR = BASE_DIR / "data" / "reference"

SIZE_CONCURRENCY = 20

# Set by update_file_tracking when --report is used. In report mode,
# filenames the strict parser rejects fall back to a loose parser so
# they still appear in the CSV. The DB path always stays strict.
_REPORT_MODE = False

_EXT_RE = re.compile(r"(\.(xml|gz|zip))+$", re.I)
_TYPE_RE = re.compile(
    r"promos?full|prices?full|storesfull|stores?|promos?|prices?",
    re.I,
)

# TYPE + 13-digit chain, then optional -3digit and -3digit.
# Two groups: sub_chain, store. One group: it is the store.
_ID_RE = re.compile(
    r"(?<!\d)(\d{13})(?!\d)"
    r"(?:[-_](\d{3})(?!\d))?"
    r"(?:[-_](\d{3})(?!\d))?"
)

# Date only (time ignored). Each pattern is tried, results validated.
_DATE_PATTERNS = [
    # YYYYMMDD / YYYY-MM-DD / YYYY_MM_DD / YYYY.MM.DD (time may follow)
    (re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})"), "ymd"),
    # DDMMYYYY / DD-MM-YYYY / DD_MM_YYYY / DD.MM.YYYY
    (re.compile(r"(?<!\d)(\d{2})[-_.]?(\d{2})[-_.]?(20\d{2})(?!\d)"), "dmy"),
]

_FILE_TYPES = {
    "price": "Price", "prices": "Price",
    "pricefull": "PriceFull", "pricesfull": "PriceFull",
    "promo": "Promo", "promos": "Promo",
    "promofull": "PromoFull", "promosfull": "PromoFull",
    "store": "Stores", "stores": "Stores",
    "storesfull": "StoresFull",
}


def _parse_loose_date(text: str) -> str | None:
    """Return YYYY-MM-DD or None. Invalid dates are skipped."""
    for rx, order in _DATE_PATTERNS:
        for m in rx.finditer(text):
            a, b, c = (int(x) for x in m.groups())
            y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                continue
    return None


def _loose_normalize(filename: str, size=None) -> dict:
    stem = _EXT_RE.sub("", filename)

    m = _TYPE_RE.search(stem)
    file_type = _FILE_TYPES.get(m.group(0).lower()) if m else None

    chain_id = sub_chain_id = store_id = None
    id_m = _ID_RE.search(stem)

    if id_m:
        chain_id, a, b = id_m.groups()
        if a and b:
            sub_chain_id, store_id = a, b
        elif a:
            store_id = a
        # date is searched after the IDs so chain digits can't match
        date_text = stem[id_m.end():]
    else:
        date_text = stem

    file_date = _parse_loose_date(date_text)

    return {
        "filename": filename,
        "file_type": file_type or "Unknown",
        "chain_id": chain_id,
        "sub_chain_id": sub_chain_id,
        "store_id": store_id,
        "file_date": file_date,
        "file_size": size,
        "parse_status": "loose" if (file_type or chain_id) else "unparsed",
    }


def _normalize(filename: str, size=None) -> dict | None:
    record = normalize_file(filename, size)

    if record is None and _REPORT_MODE:
        record = _loose_normalize(filename, size)

    return record


def _add_record(
    records: list[dict],
    filename: str,
    source: str,
    size=None,
    **extra,
) -> None:
    record = _normalize(
        filename,
        size,
    )

    if record:
        record["source"] = source

        if record.get("store_id") is not None:
            record["store_id"] = normalize_store_id(
                record["store_id"]
            )

        record.update(extra)
        records.append(record)


async def get_publishedprices_files(
    slow: bool = False,
) -> list[dict]:
    records = []

    sources = get_publishing_sources(
        "PublishedPricesClient"
    )

    for source in sources:
        chain_id = source["chain_id"]
        credentials = source.get("credentials", {})

        username = credentials.get("username")
        password = credentials.get("password")

        if not username:
            logger.error(
                "PublishedPrices: missing credentials for %s",
                chain_id,
            )
            continue

        source_label = source["name_normalized"]

        logger.info(
            "PublishedPrices: %s",
            source_label,
        )

        client = PublishedPricesClient(
            username,
            password,
        )

        try:
            client.login()

            files = list_publishedprices_entries_recursive(
                client
            )

            source_records = []

            for file in files:
                _add_record(
                    source_records,
                    file["fname"],
                    source_label,
                    file.get("size"),
                )

            logger.info(
                "%s: found %d today's file(s)",
                source_label,
                len(source_records),
            )

            records.extend(source_records)

        except Exception:
            logger.exception(
                "PublishedPrices: failed processing %s",
                source_label,
            )

    return records


async def get_binaprojects_files(
    slow: bool = False,
) -> list[dict]:
    records = []

    sources = get_publishing_sources(
        "BinaProjectsClient"
    )

    semaphore = asyncio.Semaphore(
        SIZE_CONCURRENCY
    )

    async def get_size(
        url: str,
    ) -> int | None:
        async with semaphore:
            return await asyncio.to_thread(
                get_file_size,
                url,
                True,
            )

    for source in sources:
        try:
            chain_id = source["chain_id"]
            url = source["url"]
            source_label = source["name_normalized"]

            logger.info(
                "BinaProjects: %s",
                source_label,
            )

            client = BinaProjectsClient(url)

            files = client.get_hok_files()

            source_records = []

            for file in files:
                filename = file.get("FileNm")

                if not filename:
                    continue

                record = _normalize(
                    filename,
                    None,
                )

                if record:
                    record["source"] = source_label

                    if record.get("store_id") is not None:
                        record["store_id"] = normalize_store_id(
                            record["store_id"]
                        )

                    if slow:
                        record["_download_url"] = (
                            client.get_download_url(
                                filename
                            )
                        )

                    source_records.append(record)

            if slow:
                size_tasks = [
                    get_size(record["_download_url"])
                    for record in source_records
                ]

                sizes = await asyncio.gather(
                    *size_tasks
                )

                for record, size in zip(
                    source_records,
                    sizes,
                ):
                    record["file_size"] = size
                    del record["_download_url"]

            logger.info(
                "%s: found %d today's file(s)",
                source_label,
                len(source_records),
            )

            records.extend(source_records)

        except Exception:
            logger.exception(
                "BinaProjects: failed processing %s",
                source.get("name_normalized", source),
            )

    return records


async def get_laibcatalog_files(
    slow: bool = False,
) -> list[dict]:
    records = []

    sources = get_publishing_sources(
        "LaibcatalogClient"
    )

    for source in sources:
        try:
            chain_id = source["chain_id"]
            source_label = source["name_normalized"]

            logger.info(
                "Laibcatalog: %s",
                source_label,
            )

            client = LaibcatalogClient(chain_id)

            files = await client.get_files()

            source_records = []

            for file in files:
                filename = file["fileName"]

                size = parse_file_size(
                    file.get("fileSize") or file.get("גודל")
                )

                _add_record(
                    source_records,
                    filename,
                    source_label,
                    size,
                )

            logger.info(
                "%s: found %d today's file(s)",
                source_label,
                len(source_records),
            )

            records.extend(source_records)

        except Exception:
            logger.exception(
                "Laibcatalog: failed processing %s",
                source.get("name_normalized", source),
            )

    return records


async def get_carrefour_files(
    slow: bool = False,
) -> list[dict]:
    records = []

    client = CarrefourClient()

    listing = await client.get_files()

    files = listing["files"]

    source_label = "carrefour"

    for entry in files:
        if isinstance(entry, str):
            filename = entry
            size = None
        else:
            filename = (
                entry.get("name")
                or entry.get("fileName")
                or entry.get("Name")
            )
            size = parse_file_size(
                entry.get("size")
            )

        if not filename:
            continue

        _add_record(
            records,
            filename,
            source_label,
            size,
        )

    logger.info(
        "%s: found %d file(s)",
        source_label,
        len(records),
    )

    return records


HEAD_SIZE_SOURCES = {
    "super pharm",
    "hazi hinam",
}

GET_SIZE_SOURCES = {
    "city market",
}


async def get_html_files(
    slow: bool = False,
) -> list[dict]:
    records = []

    # Cache logic (fetching + persisting the HTML source listings) lives
    # in cache_file_tracking.py so it can be run on its own. We still
    # call it here so file_tracking is built from the same run, and the
    # cache files on disk stay up to date either way.
    html_candidates = await refresh_html_caches()

    for source_name, candidates in html_candidates.items():
        source_records = []

        for candidate in candidates:
            filename = candidate.filename

            if not filename:
                continue

            size = None

            if slow:
                if candidate.file_size is not None:
                    size = parse_file_size(
                        candidate.file_size
                    )
                elif source_name in GET_SIZE_SOURCES:
                    size = get_file_size_get(
                        candidate.href
                    )
                elif source_name in HEAD_SIZE_SOURCES:
                    size = get_file_size(
                        candidate.href,
                        slow=True,
                    )

            _add_record(
                source_records,
                filename,
                source_name,
                size,
                url=candidate.href,
            )

        logger.info(
            "%s: found %d file(s)",
            source_name,
            len(source_records),
        )

        records.extend(source_records)

    return records


async def get_mishnatyosef_files(
    slow: bool = False,
) -> list[dict]:
    records = []

    client = MishnatYosefClient()

    files = await client.get_files()

    source_label = "mishnat yosef"

    for file in files:
        if isinstance(file, dict):
            filename = (
                file.get("name")
                or file.get("filename")
            )

            size = parse_file_size(
                file.get("size")
            )

            if slow and size is None:
                url = (
                    file.get("url")
                    or file.get("download_url")
                )

                if url:
                    size = get_file_size(
                        url,
                        slow=True,
                    )

        else:
            filename = file
            size = None

        if not filename:
            continue

        _add_record(
            records,
            filename,
            source_label,
            size,
        )

    logger.info(
        "%s: found %d today's file(s)",
        source_label,
        len(records),
    )

    return records


async def get_wolt_files(
    slow: bool = False,
) -> list[dict]:
    records = []

    client = WoltClient()

    source_label = "wolt"

    date_pages = await client.get_date_pages()

    for date_page in date_pages:
        if date.today().isoformat() not in date_page:
            continue

        logger.info(
            "Wolt: processing today's page %s",
            date_page,
        )

        files = await client.get_files(date_page)

        logger.info(
            "Wolt: found %d files on %s",
            len(files),
            date_page,
        )

        for url in files:
            filename = (
                url.rstrip("/")
                .split("/")[-1]
            )

            _add_record(
                records,
                filename,
                source_label,
                url=url,
            )

    logger.info(
        "%s: found %d today's file(s)",
        source_label,
        len(records),
    )

    return records


def _local_feed_directory(file_type: str) -> str | None:
    """
    Map database file_type to the local feed directory.
    """

    return {
        "Price": "prices",
        "PriceFull": "pricesfull",
        "Promo": "promos",
        "PromoFull": "promosfull",
    }.get(file_type)


def _is_downloaded_locally(record: dict) -> bool:
    """
    Check whether the discovered file exists locally.

    Normal feed files:
        data/{feeds_dir}/{chain_id}/{normalized_store_id}/{feed_type}/{filename}

    Stores registry files:
        data/{feeds_dir}/{chain_id}/stores/{filename}

    Loose (report-only) records may lack chain_id / store_id / a known
    file_type; those are treated as not downloaded.
    """

    if record.get("chain_id") is None or record.get("file_type") not in (
        "Stores",
        "Price",
        "PriceFull",
        "Promo",
        "PromoFull",
    ):
        return False

    if record["file_type"] != "Stores" and record.get("store_id") is None:
        return False

    directory = _local_feed_directory(
        record["file_type"]
    )

    chain_id = str(record["chain_id"])
    filename = record["filename"]

    if record["file_type"] == "Stores":
        stores_path = (
            FEEDS_DIR
            / chain_id
            / "stores"
            / filename
        )

        return stores_path.is_file()

    if directory is None:
        return False

    store_id = normalize_store_id(
        record["store_id"]
    )

    feed_path = (
        FEEDS_DIR
        / chain_id
        / store_id
        / directory
        / filename
    )

    return feed_path.is_file()


def _set_downloaded_status(
    records: list[dict],
) -> None:
    """
    Set downloaded=True when the corresponding file exists
    in the configured feed directory.
    """

    for record in records:
        record["downloaded"] = _is_downloaded_locally(
            record
        )


def generate_report(
    records: list[dict],
) -> Path:
    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        REPORTS_DIR
        / "file_tracking.csv"
    )

    fields = [
        "filename",
        "source",
        "file_type",
        "chain_id",
        "sub_chain_id",
        "store_id",
        "file_date",
        "file_size",
        "downloaded",
        "parse_status",
    ]

    with report_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )

        writer.writeheader()

        for record in records:
            row = {f: record.get(f) for f in fields}
            row["parse_status"] = record.get("parse_status", "strict")
            writer.writerow(row)

    logger.info(
        "Report written to %s",
        report_path,
    )

    return report_path


async def collect_all_files(
    slow: bool = False,
) -> list[dict]:
    all_records = []

    collectors = [
        ("PublishedPrices", get_publishedprices_files),
        ("BinaProjects", get_binaprojects_files),
        ("Laibcatalog", get_laibcatalog_files),
        ("Carrefour", get_carrefour_files),
        ("HTML", get_html_files),
        ("MishnatYosef", get_mishnatyosef_files),
        ("Wolt", get_wolt_files),
    ]

    for name, collector in collectors:
        try:
            records = await collector(
                slow=slow,
            )

            logger.info(
                "%s: %d today's file(s) total",
                name,
                len(records),
            )

            all_records.extend(records)

        except Exception:
            logger.exception(
                "Failed collecting files from %s",
                name,
            )

    return all_records


FILE_TRACKING_LOCK_ID = 847291


async def update_file_tracking(
    generate_report_file: bool = False,
    slow: bool = False,
) -> int:
    global _REPORT_MODE
    _REPORT_MODE = generate_report_file

    try:
        records = await collect_all_files(
            slow=slow,
        )
    finally:
        _REPORT_MODE = False

    if not records:
        logger.info(
            "No files found for today"
        )
        return 0

    unique_records = {}

    for record in records:
        unique_records[record["filename"]] = record

    records = list(
        unique_records.values()
    )

    _set_downloaded_status(records)

    downloaded_count = sum(
        record["downloaded"]
        for record in records
    )

    logger.info(
        "Local filesystem: %d/%d discovered file(s) "
        "are already downloaded",
        downloaded_count,
        len(records),
    )

    if generate_report_file:
        generate_report(records)
        return len(records)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (FILE_TRACKING_LOCK_ID,),
            )

            if not cur.fetchone()[0]:
                logger.info(
                    "File tracking is already running; skipping"
                )
                return 0

            try:
                inserted = insert_file_tracking(
                    conn,
                    records,
                )
                conn.commit()

            finally:
                cur.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (FILE_TRACKING_LOCK_ID,),
                )

    logger.info(
        "Inserted %d new file(s) out of %d discovered",
        inserted,
        len(records),
    )

    return inserted


async def main():
    parser = argparse.ArgumentParser(
        description=(
            "Discover today's feed filenames "
            "and update file_tracking."
        )
    )

    parser.add_argument(
        "--report",
        action="store_true",
        help=(
            "Also generate a CSV report "
            "of discovered files."
        ),
    )

    size_group = parser.add_mutually_exclusive_group()

    size_group.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Discover files without fetching "
            "file sizes."
        ),
    )

    size_group.add_argument(
        "--slow",
        action="store_true",
        help=(
            "Discover files and include "
            "file sizes when available."
        ),
    )

    args = parser.parse_args()

    await update_file_tracking(
        generate_report_file=args.report,
        slow=args.slow,
    )


if __name__ == "__main__":
    asyncio.run(main())