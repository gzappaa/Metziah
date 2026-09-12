# downloaders/pricesfull.py

import argparse
import asyncio
import logging
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from logging_config import setup_general_logging
from clients.publishedprices import PublishedPricesClient
from clients.binaprojects import BinaProjectsClient
from clients.laibcatalog import LaibcatalogClient
from clients.carrefour import CarrefourClient
from clients.html_client import HtmlFileLinkClient
from clients.html_config import SOURCES as HTML_SOURCES
from clients.mishnatyosef import MishnatYosefClient
from clients.wolt import WoltClient
from database.repository import get_publishing_sources

from utils.file_tracking.parser_file_tracking import parse_filename


setup_general_logging()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "feeds"
TEST_DATA_DIR = BASE_DIR / "data" / "test_feeds"

IGNORED_BINA_STORES = {
    ("7290058156016", "017", "396"),
}

# Extracts the time component from PriceFull filenames.
# Used to determine which same-day PriceFull is the latest for each store.
def _extract_time_suffix(filename: str) -> str:
    date_match = re.search(
        r"-(\d{8})-(\d+)(?:\.[^.]+)?$",
        filename,
    )

    if not date_match:
        return "000000"

    value = date_match.group(2)

    if len(value) == 3:
        return value + "000"

    if len(value) == 4:
        return value + "00"

    if len(value) == 6:
        return value

    return "000000"


def find_latest_pricefull_files_per_store(
    files: list[dict],
    filename_key: str,
    date_key: str | None = None,
    date_format: str | None = None,
) -> dict[tuple, dict]:
    """
    Find the latest PriceFull file per chain, store and day.

    For sources where multiple PriceFull files exist for the same
    store on the same day, the latest timestamp wins.
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

        if record["file_type"] != "PriceFull":
            continue

        if record["store_id"] is None:
            continue

        if record["file_date"] != today:
            continue

        key = (
            record["chain_id"],
            record["store_id"],
        )

        if date_key is not None:

            date_text = (file.get(date_key) or "").strip()

            if not date_text:
                continue

            try:
                sort_key = datetime.strptime(
                    date_text,
                    date_format,
                )
            except ValueError:
                continue

        else:
            sort_key = (
                record["file_date"],
                _extract_time_suffix(filename),
            )

        if (
            key not in latest
            or sort_key > latest[key]["sort_key"]
        ):
            latest[key] = {
                **file,
                "filename": filename,
                "chain_id": record["chain_id"],
                "store_id": record["store_id"],
                "file_date": record["file_date"],
                "sort_key": sort_key,
            }

    return latest


def _trim_for_test(
    latest_files: dict[tuple, dict],
    name: str,
    limit: int = 5,
) -> dict[tuple, dict]:
    if len(latest_files) <= limit:
        return latest_files

    logger.info(
        "TEST MODE: keeping first %d stores for %s",
        limit,
        name,
    )

    return dict(
        list(latest_files.items())[:limit]
    )


def get_storage_path(
    chain_id: str,
    store_id: str,
    data_dir: Path,
) -> Path:
    return (
        data_dir
        / chain_id
        / store_id
        / "pricesfull"
    )


def _cleanup_old_pricefull_files(
    folder: Path,
    keep_filename: str,
    file_date: date,
) -> None:
    """
    Remove older same-day PriceFull files for this store, now that
    keep_filename has been written successfully.
    """

    for old_file in folder.glob("PriceFull*.gz"):

        if old_file.name == keep_filename:
            continue

        try:
            old_record = parse_filename(old_file.name)
        except ValueError:
            continue

        if old_record["file_date"] == file_date:

            logger.info(
                "REMOVE OLD SAME DAY: %s",
                old_file.name,
            )

            old_file.unlink()


def save_pricefull_file(
    chain_id: str,
    store_id: str,
    filename: str,
    file_date: date,
    data_dir: Path,
    test: bool,
    fetch_content,
) -> Path | None:

    folder = get_storage_path(
        chain_id,
        store_id,
        data_dir,
    )

    if test and folder.exists():

        logger.warning(
            "TEST MODE: deleting existing %s",
            folder,
        )

        shutil.rmtree(folder)

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = folder / filename

    if destination.exists():

        logger.info(
            "UP TO DATE: %s",
            filename,
        )

        return destination

    logger.info(
        "DOWNLOAD: %s",
        filename,
    )

    try:
        content = fetch_content()
        destination.write_bytes(content)

    except Exception:

        logger.exception(
            "FAILED downloading %s",
            filename,
        )

        return None

    if not test:
        _cleanup_old_pricefull_files(
            folder,
            filename,
            file_date,
        )

    return destination


async def save_pricefull_file_async(
    chain_id: str,
    store_id: str,
    filename: str,
    file_date: date,
    data_dir: Path,
    test: bool,
    fetch_content,
) -> Path | None:

    folder = get_storage_path(
        chain_id,
        store_id,
        data_dir,
    )

    if test and folder.exists():

        logger.warning(
            "TEST MODE: deleting existing %s",
            folder,
        )

        shutil.rmtree(folder)

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = folder / filename

    if destination.exists():

        logger.info(
            "UP TO DATE: %s",
            filename,
        )

        return destination

    logger.info(
        "DOWNLOAD: %s",
        filename,
    )

    try:
        content = await fetch_content()
        destination.write_bytes(content)

    except Exception:

        logger.exception(
            "FAILED downloading %s",
            filename,
        )

        return None

    if not test:
        _cleanup_old_pricefull_files(
            folder,
            filename,
            file_date,
        )

    return destination


def list_publishedprices_entries_recursive(
    client: PublishedPricesClient,
    cd: str = "/",
    depth: int = 0,
    max_depth: int = 2,
) -> list[dict]:
    """
    Recursively lists raw file entries (not filtered to any file_type),
    each tagged with its full 'path' for URL construction — needed
    since PriceFull, unlike Stores, may have several live files at once
    across different stores/folders.
    """

    try:
        response_json = client.get_files(
            cd=cd
        )
    except Exception:
        logger.exception(
            "Failed listing '%s' for %s",
            cd,
            client.username,
        )
        return []

    entries = []

    for entry in response_json.get("aaData", []):

        fname = entry.get("fname")

        if not fname:
            continue

        if "." not in fname:

            if depth >= max_depth:

                logger.warning(
                    "Max recursion depth reached at %s/%s",
                    cd.rstrip("/"),
                    fname,
                )

                continue

            sub_cd = f"{cd.rstrip('/')}/{fname}"

            entries.extend(
                list_publishedprices_entries_recursive(
                    client,
                    cd=sub_cd,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

            continue

        path = (
            f"{cd.strip('/')}/{fname}"
            if cd != "/"
            else fname
        )

        entries.append(
            {
                "fname": fname,
                "path": path,
            }
        )

    return entries


def download_pricefull_publishedprices(
    name: str,
    username: str,
    password: str = "",
    test: bool = False,
) -> list[Path]:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = PublishedPricesClient(
        username,
        password,
    )

    logger.info(
        "Logging in and listing files for %s (%s)...",
        name,
        username,
    )

    try:
        client.login()

    except Exception:
        logger.exception(
            "Failed logging in for %s",
            username,
        )
        return []

    entries = list_publishedprices_entries_recursive(
        client
    )

    latest_files = find_latest_pricefull_files_per_store(
        entries,
        filename_key="fname",
    )

    if not latest_files:
        logger.warning(
            "No PriceFull files found for %s",
            name,
        )
        return []

    latest_files = _trim_for_test(
        latest_files,
        name,
    ) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        def fetch_content(latest=latest) -> bytes:
            download_url = (
                f"{PublishedPricesClient.BASE_URL}"
                f"/file/d/{latest['path']}"
            )
            return client.download_file(
                download_url
            )

        result = save_pricefull_file(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=latest["filename"],
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


def download_pricefull_binaprojects(
    name: str,
    url: str,
    test: bool = False,
) -> list[Path]:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = BinaProjectsClient(url)

    logger.info(
        "Listing files for %s (BinaProjects)...",
        name,
    )

    try:
        # file_type=4 -> PriceFull, per the documented WFileType mapping.
        files = client.get_hok_files(
            file_type=4
        )
    except Exception:
        logger.exception(
            "Failed getting file list for %s",
            name,
        )
        return []

    filtered_files = []

    for file in files:
        filename = (file.get("FileNm") or "").strip()

        if not filename:
            continue

        try:
            record = parse_filename(filename)
        except ValueError:
            continue

        key = (
            record["chain_id"],
            record["sub_chain_id"],
            record["store_id"],
        )

        if key in IGNORED_BINA_STORES:
            logger.info(
                "IGNORING BinaProjects file: %s",
                filename,
            )
            continue

        filtered_files.append(file)

    files = filtered_files

    latest_files = find_latest_pricefull_files_per_store(
        files,
        filename_key="FileNm",
        date_key="DateFile",
        date_format="%H:%M %d/%m/%Y",
    )

    if not latest_files:
        logger.warning(
            "No PriceFull files found for %s",
            name,
        )
        return []

    latest_files = _trim_for_test(
        latest_files,
        name,
    ) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        def fetch_content(latest=latest) -> bytes:
            download_url = client.get_download_url(
                latest["filename"]
            )
            return client.download_file(
                download_url
            )

        result = save_pricefull_file(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=latest["filename"],
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_pricefull_laibcatalog(
    name: str,
    url: str,
    chain_id: str,
    test: bool = False,
) -> list[Path]:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = LaibcatalogClient(
        chain_id
    )

    logger.info(
        "Listing files for %s (Laibcatalog)...",
        name,
    )

    try:
        files = await client.get_files()

    except Exception:
        logger.exception(
            "Failed getting file list for %s",
            name,
        )
        return []

    latest_files = find_latest_pricefull_files_per_store(
        files,
        filename_key="fileName",
    )

    if not latest_files:
        logger.warning(
            "No PriceFull files found for %s",
            name,
        )
        return []

    latest_files = _trim_for_test(
        latest_files,
        name,
    ) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        resolved_chain_id = (
            latest.get("chain_id") or chain_id
        )

        async def fetch_content(latest=latest) -> bytes:
            download_url = client.build_download_url(
                latest["filename"]
            )
            return await client.download_file(
                download_url
            )

        result = await save_pricefull_file_async(
            chain_id=resolved_chain_id,
            store_id=latest["store_id"],
            filename=latest["filename"],
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_pricefull_carrefour(
    test: bool = False,
) -> list[Path]:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = CarrefourClient()

    logger.info(
        "Listing files for Carrefour..."
    )

    try:
        listing = await client.get_files()

    except Exception:
        logger.exception(
            "Failed getting file list for Carrefour"
        )
        return []

    path = listing["path"]
    files = listing["files"]

    normalized = []

    for entry in files:

        if isinstance(entry, str):
            normalized.append(
                {"filename": entry}
            )
        else:
            filename = (
                entry.get("name")
                or entry.get("fileName")
                or entry.get("Name")
            )

            if filename:
                normalized.append(
                    {"filename": filename}
                )

    latest_files = find_latest_pricefull_files_per_store(
        normalized,
        filename_key="filename",
    )

    if not latest_files:
        logger.warning(
            "No PriceFull files found for Carrefour"
        )
        return []

    latest_files = _trim_for_test(
        latest_files,
        "Carrefour",
    ) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]

        download_url = urljoin(
            f"{client.base_url}/",
            f"{path.strip('/')}/{filename}",
        )

        async def fetch_content(download_url=download_url) -> bytes:
            return await client.download_file(
                download_url
            )

        result = await save_pricefull_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files

async def get_html_page(
    client: HtmlFileLinkClient,
    page: int,
    page_param: str,
    params: dict | None = None,
):
    request_params = dict(params or {})
    request_params[page_param] = page

    return await client.get_candidates(
        params=request_params
    )


def _page_fingerprint(candidates) -> tuple:
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
                    listing_config.get("pricefull_params"),
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

            fingerprint = _page_fingerprint(candidates)

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
                filename = getattr(
                    candidate,
                    "filename",
                    None,
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



async def download_pricefull_html(
    source: dict,
    test: bool = False,
) -> list[Path]:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    name = source["name"]
    listing = source["listing"]
    categories = source["categories"]

    # NOTE: assumes each HTML source's html_config.py entry defines a
    # "PriceFull" key under categories["file_types"], mirroring how
    # "Stores" is configured in stores.py. Verify against live config —
    # some sources may only ever publish Price/PriceFull under a
    # combined filter param rather than a distinct one.
    pricefull_params = categories.get(
        "file_types",
        {},
    ).get("PriceFull")

    if pricefull_params is None:
        logger.warning(
            "No 'PriceFull' file_type configured for %s",
            name,
        )
        return []

    base_url = categories.get(
        "endpoint",
        listing["base_url"],
    )

    client = HtmlFileLinkClient(
        name=name,
        base_url=base_url,
        extraction_mode=source["extraction_mode"],
        filename_column=source.get("filename_column"),
        filename_source=source["filename_source"],
        filename_param=source.get("filename_param"),
    )

    logger.info(
        "Listing files for %s (HTML)...",
        name,
    )

    try:
        candidates = await get_all_html_candidates(
            client,
            {
                **listing,
                "pricefull_params": pricefull_params,
            },
        )

    except Exception:
        logger.exception(
            "Failed getting file list for %s",
            name,
        )
        return []

    href_by_filename = {
        candidate.filename: candidate.href
        for candidate in candidates
        if candidate.filename
    }

    latest_files = find_latest_pricefull_files_per_store(
        [
            {"filename": filename}
            for filename in href_by_filename
        ],
        filename_key="filename",
    )

    if not latest_files:
        logger.warning(
            "No PriceFull files found for %s",
            name,
        )
        return []

    latest_files = _trim_for_test(
        latest_files,
        name,
    ) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            response = await client._get_with_retry(href)
            return response.content

        result = await save_pricefull_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_pricefull_mishnatyosef(
    test: bool = False,
) -> list[Path]:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = MishnatYosefClient()

    logger.info(
        "Listing files for Mishnat Yosef..."
    )

    try:
        files = await client.get_files()

    except Exception:
        logger.exception(
            "Failed getting file list for Mishnat Yosef"
        )
        return []

    normalized = []
    href_by_filename = {}

    for entry in files:

        if entry.get("type") != "PriceFull":
            continue

        filename = entry.get("name")
        url = entry.get("url")

        if not filename or not url:
            continue

        normalized.append(
            {"filename": filename}
        )

        href_by_filename[filename] = url

    latest_files = find_latest_pricefull_files_per_store(
        normalized,
        filename_key="filename",
    )

    if not latest_files:
        logger.warning(
            "No PriceFull files found for Mishnat Yosef"
        )
        return []

    latest_files = _trim_for_test(
        latest_files,
        "Mishnat Yosef",
    ) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_pricefull_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_pricefull_wolt(
    test: bool = False,
) -> list[Path]:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = WoltClient()

    logger.info(
        "Listing date pages for Wolt..."
    )

    try:
        date_pages = await client.get_date_pages()

    except Exception:
        logger.exception(
            "Failed getting date pages for Wolt"
        )
        return []

    if not date_pages:
        logger.warning(
            "No date pages found for Wolt"
        )
        return []

    try:
        file_urls = await client.get_files(
            date_pages[0]
        )

    except Exception:
        logger.exception(
            "Failed getting file list for Wolt"
        )
        return []

    normalized = []
    href_by_filename = {}

    for url in file_urls:

        filename = urlparse(url).path.rsplit(
            "/",
            1,
        )[-1]

        if not filename:
            continue

        normalized.append(
            {"filename": filename}
        )

        href_by_filename[filename] = url

    latest_files = find_latest_pricefull_files_per_store(
        normalized,
        filename_key="filename",
    )

    if not latest_files:
        logger.warning(
            "No PriceFull files found for Wolt"
        )
        return []

    latest_files = _trim_for_test(
        latest_files,
        "Wolt",
    ) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_pricefull_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Use test_feeds directory and cap each source at 5 stores",
    )

    args = parser.parse_args()

    all_downloaded: list[Path] = []

    pp_sources = get_publishing_sources(
        "PublishedPricesClient"
    )

    logger.info(
        "Found %d PublishedPrices sources",
        len(pp_sources),
    )

    for source in pp_sources:

        credentials = source.get(
            "credentials",
            {},
        )

        username = credentials.get(
            "username"
        )

        password = credentials.get(
            "password",
            "",
        )

        if not username:

            logger.warning(
                "Skipping %s: no username",
                source["name"],
            )

            continue

        try:

            all_downloaded.extend(
                download_pricefull_publishedprices(
                    source["name"],
                    username,
                    password,
                    test=args.test,
                )
            )

        except Exception:

            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    bina_sources = get_publishing_sources(
        "BinaProjectsClient"
    )

    logger.info(
        "Found %d BinaProjects sources",
        len(bina_sources),
    )

    for source in bina_sources:

        try:

            all_downloaded.extend(
                download_pricefull_binaprojects(
                    source["name"],
                    source["url"],
                    test=args.test,
                )
            )

        except Exception:

            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    laib_sources = get_publishing_sources(
        "LaibcatalogClient"
    )

    logger.info(
        "Found %d Laibcatalog sources",
        len(laib_sources),
    )

    for source in laib_sources:

        if not source.get("chain_id"):

            logger.warning(
                "Skipping %s: no chain_id in registry",
                source["name"],
            )

            continue

        try:

            all_downloaded.extend(
                asyncio.run(
                    download_pricefull_laibcatalog(
                        source["name"],
                        source["url"],
                        source["chain_id"],
                        test=args.test,
                    )
                )
            )

        except Exception:

            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    logger.info(
        "Found %d HTML-based sources",
        len(HTML_SOURCES),
    )

    for source in HTML_SOURCES:

        try:

            all_downloaded.extend(
                asyncio.run(
                    download_pricefull_html(
                        source,
                        test=args.test,
                    )
                )
            )

        except Exception:

            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    try:

        all_downloaded.extend(
            asyncio.run(
                download_pricefull_carrefour(
                    test=args.test
                )
            )
        )

    except Exception:

        logger.exception(
            "Failed processing Carrefour"
        )

    try:

        all_downloaded.extend(
            asyncio.run(
                download_pricefull_mishnatyosef(
                    test=args.test
                )
            )
        )

    except Exception:

        logger.exception(
            "Failed processing Mishnat Yosef"
        )

    try:

        all_downloaded.extend(
            asyncio.run(
                download_pricefull_wolt(
                    test=args.test
                )
            )
        )

    except Exception:

        logger.exception(
            "Failed processing Wolt"
        )

    logger.info(
        "Finished. Downloaded %d PriceFull file(s) total.",
        len(all_downloaded),
    )