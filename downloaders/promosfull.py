# downloaders/promosfull.py

import logging
from urllib.parse import urljoin

from logging_config import setup_general_logging
from clients.publishedprices import PublishedPricesClient
from clients.binaprojects import BinaProjectsClient
from clients.laibcatalog import LaibcatalogClient
from clients.carrefour import CarrefourClient
from clients.html_client import HtmlFileLinkClient
from clients.mishnatyosef import MishnatYosefClient
from clients.wolt import WoltClient

from utils.file_tracking.parser_file_tracking import parse_filename

from downloaders.runner import run_all_sources, run_cli

from downloaders.common import (
    get_data_dir,
    filter_test_stores,
    filter_ignored_bina_stores,
    trim_for_test,
    list_publishedprices_entries_recursive,
    normalize_carrefour_listing,
    normalize_wolt_file_urls,
    normalize_mishnatyosef_listing,
    _load_html_cache,
)

from downloaders.full_family import (
    find_latest_full_files_per_store,
    save_full_file,
    save_full_file_async,
)


setup_general_logging()

logger = logging.getLogger(__name__)

FILE_TYPE = "PromoFull"
SUBFOLDER = "promosfull"


def download_promofull_publishedprices(
    name: str,
    username: str,
    password: str = "",
    test: bool = False,
) -> list:

    data_dir = get_data_dir(test)
    client = PublishedPricesClient(username, password)

    logger.info(
        "Logging in and listing files for %s (%s)...", name, username,
    )

    try:
        client.login()
    except Exception:
        logger.exception("Failed logging in for %s", username)
        return []

    entries = list_publishedprices_entries_recursive(client)

    latest_files = find_latest_full_files_per_store(
        entries,
        FILE_TYPE,
        filename_key="fname",
    )

    if not latest_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    latest_files = filter_test_stores(latest_files) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        def fetch_content(latest=latest) -> bytes:
            download_url = (
                f"{PublishedPricesClient.BASE_URL}/file/d/{latest['path']}"
            )
            return client.download_file(download_url)

        result = save_full_file(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=latest["filename"],
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            file_type=FILE_TYPE,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


def download_promofull_binaprojects(
    name: str,
    url: str,
    test: bool = False,
) -> list:

    data_dir = get_data_dir(test)
    client = BinaProjectsClient(url)

    logger.info("Listing files for %s (BinaProjects)...", name)

    try:
        # file_type=5 -> PromoFull, per the documented WFileType mapping.
        files = client.get_hok_files(file_type=5)
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return []

    files = filter_ignored_bina_stores(files, "FileNm", parse_filename)

    latest_files = find_latest_full_files_per_store(
        files,
        FILE_TYPE,
        filename_key="FileNm",
        date_key="DateFile",
        date_format="%H:%M %d/%m/%Y",
    )

    if not latest_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    latest_files = filter_test_stores(latest_files) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        def fetch_content(latest=latest) -> bytes:
            return client.download_file(latest["filename"])

        result = save_full_file(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=latest["filename"],
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            file_type=FILE_TYPE,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files

async def download_promofull_laibcatalog(
    name: str,
    url: str,
    chain_id: str,
    test: bool = False,
) -> list:

    data_dir = get_data_dir(test)
    client = LaibcatalogClient(chain_id)

    logger.info("Listing files for %s (Laibcatalog)...", name)

    try:
        files = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return []

    latest_files = find_latest_full_files_per_store(
        files,
        FILE_TYPE,
        filename_key="fileName",
    )

    if not latest_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    latest_files = filter_test_stores(latest_files) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        resolved_chain_id = latest.get("chain_id") or chain_id

        async def fetch_content(latest=latest) -> bytes:
            download_url = client.build_download_url(latest["filename"])
            return await client.download_file(download_url)

        result = await save_full_file_async(
            chain_id=resolved_chain_id,
            store_id=latest["store_id"],
            filename=latest["filename"],
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            file_type=FILE_TYPE,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promofull_carrefour(test: bool = False) -> list:

    data_dir = get_data_dir(test)
    client = CarrefourClient()

    logger.info("Listing files for Carrefour...")

    try:
        listing = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list for Carrefour")
        return []

    path = listing["path"]
    normalized = normalize_carrefour_listing(listing["files"])

    latest_files = find_latest_full_files_per_store(
        normalized,
        FILE_TYPE,
        filename_key="filename",
    )

    if not latest_files:
        logger.warning("No %s files found for Carrefour", FILE_TYPE)
        return []

    latest_files = (
        trim_for_test(latest_files, "Carrefour") if test else latest_files
    )

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]

        download_url = urljoin(
            f"{client.base_url}/",
            f"{path.strip('/')}/{filename}",
        )

        async def fetch_content(download_url=download_url) -> bytes:
            return await client.download_file(download_url)

        result = await save_full_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            file_type=FILE_TYPE,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promofull_html(
    source: dict,
    test: bool = False,
) -> list:

    data_dir = get_data_dir(test)
    name = source["name"]

    client = HtmlFileLinkClient(
        name=name,
        base_url=source["listing"]["base_url"],
        extraction_mode=source["extraction_mode"],
        filename_column=source.get("filename_column"),
        filename_source=source["filename_source"],
        filename_param=source.get("filename_param"),
    )

    logger.info(
        "Loading HTML cache for %s...",
        name,
    )

    candidates = _load_html_cache(name)

    href_by_filename = {}

    for candidate in candidates:
        filename = candidate.filename

        if not filename:
            continue

        try:
            record = parse_filename(filename)
        except ValueError:
            continue

        if record["file_type"] != FILE_TYPE:
            continue

        href_by_filename[filename] = candidate.href

    latest_files = find_latest_full_files_per_store(
        [
            {"filename": filename}
            for filename in href_by_filename
        ],
        FILE_TYPE,
        filename_key="filename",
    )

    if not latest_files:
        logger.warning(
            "No %s files found for %s",
            FILE_TYPE,
            name,
        )
        return []

    latest_files = filter_test_stores(latest_files) if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            response = await client._get_with_retry(href)
            return response.content

        result = await save_full_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            file_type=FILE_TYPE,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promofull_mishnatyosef(
    test: bool = False,
) -> list:

    data_dir = get_data_dir(test)
    client = MishnatYosefClient()

    logger.info("Listing files for Mishnat Yosef...")

    try:
        files = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list for Mishnat Yosef")
        return []

    normalized, href_by_filename = normalize_mishnatyosef_listing(
        files,
        FILE_TYPE,
    )

    latest_files = find_latest_full_files_per_store(
        normalized,
        FILE_TYPE,
        filename_key="filename",
    )

    if not latest_files:
        logger.warning(
            "No %s files found for Mishnat Yosef",
            FILE_TYPE,
        )
        return []

    latest_files = (
        trim_for_test(latest_files, "Mishnat Yosef") if test else latest_files
    )

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_full_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            file_type=FILE_TYPE,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promofull_wolt(test: bool = False) -> list:

    data_dir = get_data_dir(test)
    client = WoltClient()

    logger.info("Listing date pages for Wolt...")

    try:
        date_pages = await client.get_date_pages()
    except Exception:
        logger.exception("Failed getting date pages for Wolt")
        return []

    if not date_pages:
        logger.warning("No date pages found for Wolt")
        return []

    try:
        file_urls = await client.get_files(date_pages[0])
    except Exception:
        logger.exception("Failed getting file list for Wolt")
        return []

    normalized, href_by_filename = normalize_wolt_file_urls(file_urls)

    latest_files = find_latest_full_files_per_store(
        normalized,
        FILE_TYPE,
        filename_key="filename",
    )

    if not latest_files:
        logger.warning("No %s files found for Wolt", FILE_TYPE)
        return []

    latest_files = trim_for_test(latest_files, "Wolt") if test else latest_files

    downloaded_files = []

    for latest in latest_files.values():

        filename = latest["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_full_file_async(
            chain_id=latest["chain_id"],
            store_id=latest["store_id"],
            filename=filename,
            file_date=latest["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            file_type=FILE_TYPE,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promofull(test: bool = False) -> list:
    """Awaitable entry point for the scheduler (no argparse/sys.argv)."""
    return await run_all_sources(
        FILE_TYPE,
        download_promofull_publishedprices,
        download_promofull_binaprojects,
        download_promofull_laibcatalog,
        download_promofull_html,
        download_promofull_carrefour,
        download_promofull_mishnatyosef,
        download_promofull_wolt,
        test=test,
    )


if __name__ == "__main__":
    run_cli(
        FILE_TYPE,
        download_promofull_publishedprices,
        download_promofull_binaprojects,
        download_promofull_laibcatalog,
        download_promofull_html,
        download_promofull_carrefour,
        download_promofull_mishnatyosef,
        download_promofull_wolt,
    )