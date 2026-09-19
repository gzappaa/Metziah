# downloaders/prices.py

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

from downloaders.common import (
    get_data_dir,
    _load_html_cache,
    filter_test_store_files,
    list_publishedprices_entries_recursive,
    filter_ignored_bina_stores,
    normalize_carrefour_listing,
    normalize_wolt_file_urls,
    normalize_mishnatyosef_listing,
    get_all_html_candidates,
)
from downloaders.delta_family import (
    keep_latest_file_per_store,
    find_delta_files,
    save_delta_file,
    save_delta_file_async,
)
from downloaders.runner import run_all_sources, run_cli


setup_general_logging()

logger = logging.getLogger(__name__)

FILE_TYPE = "Price"
SUBFOLDER = "prices"


def download_price_publishedprices(
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

    price_files = find_delta_files(entries, FILE_TYPE, filename_key="fname")

    if test:
        price_files = filter_test_store_files(price_files)

    if not price_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    downloaded_files = []

    for price_file in price_files:

        def fetch_content(price_file=price_file) -> bytes:
            download_url = (
                f"{PublishedPricesClient.BASE_URL}/file/d/{price_file['path']}"
            )
            return client.download_file(download_url)

        result = save_delta_file(
            chain_id=price_file["chain_id"],
            store_id=price_file["store_id"],
            filename=price_file["filename"],
            file_date=price_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


def download_price_binaprojects(
    name: str,
    url: str,
    test: bool = False,
) -> list:

    data_dir = get_data_dir(test)
    client = BinaProjectsClient(url)

    logger.info("Listing files for %s (BinaProjects)...", name)

    try:
        # file_type=2 -> Price, per the documented WFileType mapping.
        files = client.get_hok_files(file_type=2)
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return []

    files = filter_ignored_bina_stores(files, "FileNm", parse_filename)

    price_files = find_delta_files(files, FILE_TYPE, filename_key="FileNm")

    if test:
        price_files = filter_test_store_files(price_files)

    if not price_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    downloaded_files = []

    for price_file in price_files:

        def fetch_content(price_file=price_file) -> bytes:
            return client.download_file(price_file["filename"])

        result = save_delta_file(
            chain_id=price_file["chain_id"],
            store_id=price_file["store_id"],
            filename=price_file["filename"],
            file_date=price_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_price_laibcatalog(
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

    price_files = find_delta_files(
    files,
    FILE_TYPE,
    filename_key="fileName",
)

    price_files = keep_latest_file_per_store(price_files)


    if test:
        price_files = filter_test_store_files(price_files)

    if not price_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    downloaded_files = []

    for price_file in price_files:

        resolved_chain_id = price_file.get("chain_id") or chain_id

        async def fetch_content(price_file=price_file) -> bytes:
            download_url = client.build_download_url(price_file["filename"])
            return await client.download_file(download_url)

        result = await save_delta_file_async(
            chain_id=resolved_chain_id,
            store_id=price_file["store_id"],
            filename=price_file["filename"],
            file_date=price_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_price_carrefour(test: bool = False) -> list:

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

    price_files = find_delta_files(normalized, FILE_TYPE, filename_key="filename")

    if test:
        price_files = filter_test_store_files(price_files)

    if not price_files:
        logger.warning("No %s files found for Carrefour", FILE_TYPE)
        return []

    downloaded_files = []

    for price_file in price_files:

        filename = price_file["filename"]

        download_url = urljoin(
            f"{client.base_url}/", f"{path.strip('/')}/{filename}",
        )

        async def fetch_content(download_url=download_url) -> bytes:
            return await client.download_file(download_url)

        result = await save_delta_file_async(
            chain_id=price_file["chain_id"],
            store_id=price_file["store_id"],
            filename=filename,
            file_date=price_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_price_html(
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

    price_files = find_delta_files(
        [
            {"filename": filename}
            for filename in href_by_filename
        ],
        FILE_TYPE,
        filename_key="filename",
    )

    if test:
        price_files = filter_test_store_files(
            price_files
        )

    if not price_files:
        logger.warning(
            "No %s files found for %s",
            FILE_TYPE,
            name,
        )
        return []

    downloaded_files = []

    for price_file in price_files:

        filename = price_file["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            response = await client._get_with_retry(href)
            return response.content

        result = await save_delta_file_async(
            chain_id=price_file["chain_id"],
            store_id=price_file["store_id"],
            filename=filename,
            file_date=price_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_price_mishnatyosef(test: bool = False) -> list:

    data_dir = get_data_dir(test)
    client = MishnatYosefClient()

    logger.info("Listing files for Mishnat Yosef...")

    try:
        files = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list for Mishnat Yosef")
        return []

    normalized, href_by_filename = normalize_mishnatyosef_listing(
        files, FILE_TYPE,
    )

    price_files = find_delta_files(normalized, FILE_TYPE, filename_key="filename")

    if test:
        price_files = filter_test_store_files(price_files)

    if not price_files:
        logger.warning("No %s files found for Mishnat Yosef", FILE_TYPE)
        return []

    downloaded_files = []

    for price_file in price_files:

        filename = price_file["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_delta_file_async(
            chain_id=price_file["chain_id"],
            store_id=price_file["store_id"],
            filename=filename,
            file_date=price_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_price_wolt(test: bool = False) -> list:

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

    price_files = find_delta_files(normalized, FILE_TYPE, filename_key="filename")

    if test:
        price_files = filter_test_store_files(price_files)

    if not price_files:
        logger.warning("No %s files found for Wolt", FILE_TYPE)
        return []

    downloaded_files = []

    for price_file in price_files:

        filename = price_file["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_delta_file_async(
            chain_id=price_file["chain_id"],
            store_id=price_file["store_id"],
            filename=filename,
            file_date=price_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_prices(test: bool = False) -> list:
    """Awaitable entry point for the scheduler (no argparse/sys.argv)."""
    return await run_all_sources(
        FILE_TYPE,
        download_price_publishedprices,
        download_price_binaprojects,
        download_price_laibcatalog,
        download_price_html,
        download_price_carrefour,
        download_price_mishnatyosef,
        download_price_wolt,
        test=test,
    )


if __name__ == "__main__":
    run_cli(
        FILE_TYPE,
        download_price_publishedprices,
        download_price_binaprojects,
        download_price_laibcatalog,
        download_price_html,
        download_price_carrefour,
        download_price_mishnatyosef,
        download_price_wolt,
    )