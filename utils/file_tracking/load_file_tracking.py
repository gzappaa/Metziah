# utils/file_tracking/load_file_tracking.py

import argparse
import asyncio
import csv
import logging
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
from clients.html_client import HtmlFileLinkClient
from clients.html_config import SOURCES as HTML_SOURCES
from clients.mishnatyosef import MishnatYosefClient
from clients.wolt import WoltClient

from .parser_file_tracking import parse_filename, normalize_file
from .add_sizes_file_tracking import get_file_size, get_file_size_get, parse_file_size


setup_general_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE_DIR / "data" / "reference"

SIZE_CONCURRENCY = 20

def _publishedprices_is_folder(entry: dict) -> bool:
    filename = entry.get("fname")

    if not filename:
        return False

    return "." not in filename


def get_publishedprices_files_recursive(
    client: PublishedPricesClient,
    cd: str = "/",
    depth: int = 0,
    max_depth: int = 2,
) -> list[dict]:
    try:
        response = client.get_files(
            cd=cd
        )
    except Exception:
        logger.exception(
            "PublishedPrices: failed listing %s",
            cd,
        )
        return []

    records = []

    logger.info(
        "PublishedPrices: received %d entries in %s",
        len(response.get("aaData", [])),
        cd,
    )

    for entry in response.get("aaData", []):
        filename = entry.get("fname")

        if not filename:
            continue

        # Entries without an extension are folders.
        if _publishedprices_is_folder(entry):
            if depth >= max_depth:
                logger.warning(
                    "PublishedPrices: max recursion depth reached at %s/%s",
                    cd.rstrip("/"),
                    filename,
                )
                continue

            sub_cd = f"{cd.rstrip('/')}/{filename}"

            logger.info(
                "PublishedPrices: '%s' looks like a folder — recursing",
                filename,
            )

            records.extend(
                get_publishedprices_files_recursive(
                    client,
                    cd=sub_cd,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

            continue

        size = entry.get("size")

        record = normalize_file(
            filename,
            size,
        )

        if record:
            records.append(record)

    return records


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

            files = get_publishedprices_files_recursive(
                client
            )

            for file in files:
                file["source"] = source_label

            logger.info(
                "%s: found %d today's file(s)",
                source_label,
                len(files),
            )

            records.extend(files)

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

                download_url = client.get_download_url(
                    filename
                )

                record = normalize_file(
                    filename,
                    None,
                )

                if record:
                    record["_download_url"] = download_url
                    record["source"] = source_label
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

            else:
                for record in source_records:
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

                record = normalize_file(
                    filename,
                    size,
                )

                if record:
                    record["source"] = source_label
                    source_records.append(record)

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

        record = normalize_file(
            filename,
            size,
        )

        if record:
            record["source"] = source_label
            records.append(record)

    logger.info(
        "%s: found %d today's file(s)",
        source_label,
        len(records),
    )

    return records


def _candidate_filename(candidate) -> str | None:
    filename = getattr(candidate, "filename", None)

    if filename:
        return filename

    return None


async def get_html_page(
    client: HtmlFileLinkClient,
    page: int,
    page_param: str,
):
    return await client.get_candidates(
        params={
            page_param: page,
        }
    )


def _page_fingerprint(candidates) -> tuple:
    """
    Create a stable fingerprint for an HTML page.

    Some sites return the same final page for arbitrary
    page numbers beyond the real last page.
    """
    return tuple(
        (
            getattr(candidate, "filename", None),
            getattr(candidate, "href", None),
            getattr(candidate, "text", None),
        )
        for candidate in candidates
    )


async def get_all_html_candidates(
    client: HtmlFileLinkClient,
    listing_config: dict,
) -> list:
    pagination = listing_config.get("pagination")

    if pagination is None:
        return await client.get_candidates()

    if pagination != "numeric":
        raise ValueError(
            f"Unsupported pagination type for "
            f"{client.name}: {pagination!r}"
        )

    page_param = listing_config["page_param"]

    # Number of pages requested concurrently.
    # Can be overridden per source in html_config.py.
    page_batch_size = listing_config.get(
        "concurrency",
        10,
    )

    all_candidates = []

    seen_pages = set()

    page = 1

    while True:
        pages = list(
            range(
                page,
                page + page_batch_size,
            )
        )

        logger.info(
            "%s: requesting pages %d-%d",
            client.name,
            pages[0],
            pages[-1],
        )

        results = await asyncio.gather(
            *(
                get_html_page(
                    client,
                    current_page,
                    page_param,
                )
                for current_page in pages
            ),
            return_exceptions=True,
        )

        stop_after_batch = False

        for current_page, candidates in zip(
            pages,
            results,
        ):
            if isinstance(candidates, Exception):
                logger.error(
                    "%s: page %d failed: %s",
                    client.name,
                    current_page,
                    candidates,
                )
                continue

            if not candidates:
                logger.info(
                    "%s: page %d is empty",
                    client.name,
                    current_page,
                )

                stop_after_batch = True
                continue

            fingerprint = _page_fingerprint(
                candidates
            )

            if fingerprint in seen_pages:
                logger.info(
                    "%s: page %d repeats a previous page",
                    client.name,
                    current_page,
                )

                stop_after_batch = True
                continue

            seen_pages.add(fingerprint)

            today_count = 0
            recognized_count = 0
            older_count = 0

            for candidate in candidates:
                filename = _candidate_filename(
                    candidate
                )

                if not filename:
                    continue

                try:
                    record = parse_filename(filename)
                except ValueError:
                    continue

                recognized_count += 1

                if record["file_date"] == date.today():
                    today_count += 1
                    all_candidates.append(candidate)

                elif record["file_date"] < date.today():
                    older_count += 1

            logger.info(
                "%s: page %d -> %d candidates, "
                "%d recognized, %d today, %d older",
                client.name,
                current_page,
                len(candidates),
                recognized_count,
                today_count,
                older_count,
            )

        if stop_after_batch:
            break

        page += page_batch_size

    return all_candidates




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

    for source in HTML_SOURCES:
        source_name = source["name"]

        logger.info(
            "HTML source: %s",
            source_name,
        )

        listing = source["listing"]

        client = HtmlFileLinkClient(
            name=source_name,
            base_url=listing["base_url"],
            extraction_mode=source["extraction_mode"],
            filename_column=source.get(
                "filename_column"
            ),
            filename_source=source["filename_source"],
            filename_param=source.get(
                "filename_param"
            ),
            file_size_column=source.get(
                "file_size_column"
            ),
        )

        candidates = await get_all_html_candidates(
            client,
            listing,
        )

        source_label = source_name
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

            record = normalize_file(
                filename,
                size,
            )

            if record:
                record["source"] = source_label
                record["url"] = candidate.href
                source_records.append(record)

        logger.info(
            "%s: found %d today's file(s)",
            source_label,
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

        record = normalize_file(
            filename,
            size,
        )

        if record:
            record["source"] = source_label
            records.append(record)

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

    today = date.today()
    today_str = today.isoformat()

    date_pages = await client.get_date_pages()

    for date_page in date_pages:
        # Wolt exposes a separate HTML page for each date.
        # Only fetch today's page — historical pages are irrelevant
        # for file_tracking.
        if today_str not in date_page:
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

            record = normalize_file(filename)

            if record:
                record["source"] = source_label
                record["url"] = url
                records.append(record)

    logger.info(
        "%s: found %d today's file(s)",
        source_label,
        len(records),
    )

    return records


async def collect_all_files(
    slow: bool = False,
) -> list[dict]:
    all_records = []

    collectors = [
        (
            "PublishedPrices",
            get_publishedprices_files,
        ),
        (
            "BinaProjects",
            get_binaprojects_files,
        ),
        (
            "Laibcatalog",
            get_laibcatalog_files,
        ),
        (
            "Carrefour",
            get_carrefour_files,
        ),
        (
            "HTML",
            get_html_files,
        ),
        (
            "MishnatYosef",
            get_mishnatyosef_files,
        ),
        (
            "Wolt",
            get_wolt_files,
        ),
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
            writer.writerow(
                {
                    field: record.get(field)
                    for field in fields
                }
            )

    logger.info(
        "Report written to %s",
        report_path,
    )

    return report_path


async def update_file_tracking(
    generate_report_file: bool = False,
    slow: bool = False,
) -> int:
    records = await collect_all_files(
        slow=slow,
    )

    if not records:
        logger.info(
            "No files found for today"
        )
        return 0

    # filename is globally unique according to the
    # file_tracking database constraint.
    unique_records = {}

    for record in records:
        unique_records[record["filename"]] = record

    records = list(
        unique_records.values()
    )

    if generate_report_file:
        generate_report(records)
        return len(records)

    with get_connection() as conn:
        inserted = insert_file_tracking(
            conn,
            records,
        )
        conn.commit()

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