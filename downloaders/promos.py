# downloaders/promos.py

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
    filter_test_store_files,
    list_publishedprices_entries_recursive,
    filter_ignored_bina_stores,
    normalize_carrefour_listing,
    normalize_wolt_file_urls,
    normalize_mishnatyosef_listing,
    get_all_html_candidates,
)
from downloaders.delta_family import (
    find_delta_files,
    save_delta_file,
    save_delta_file_async,
)
from downloaders.runner import run


setup_general_logging()

logger = logging.getLogger(__name__)

FILE_TYPE = "Promo"
SUBFOLDER = "promos"


def download_promo_publishedprices(
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

    promo_files = find_delta_files(entries, FILE_TYPE, filename_key="fname")

    if test:
        promo_files = filter_test_store_files(promo_files)

    if not promo_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    downloaded_files = []

    for promo_file in promo_files:

        def fetch_content(promo_file=promo_file) -> bytes:
            download_url = (
                f"{PublishedPricesClient.BASE_URL}/file/d/{promo_file['path']}"
            )
            return client.download_file(download_url)

        result = save_delta_file(
            chain_id=promo_file["chain_id"],
            store_id=promo_file["store_id"],
            filename=promo_file["filename"],
            file_date=promo_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


def download_promo_binaprojects(
    name: str,
    url: str,
    test: bool = False,
) -> list:

    data_dir = get_data_dir(test)
    client = BinaProjectsClient(url)

    logger.info("Listing files for %s (BinaProjects)...", name)

    try:
        # file_type=3 -> Promo, per the documented WFileType mapping.
        files = client.get_hok_files(file_type=3)
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return []

    files = filter_ignored_bina_stores(files, "FileNm", parse_filename)

    promo_files = find_delta_files(files, FILE_TYPE, filename_key="FileNm")

    if test:
       promo_files = filter_test_store_files(promo_files)

    if not promo_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    downloaded_files = []

    for promo_file in promo_files:

        def fetch_content(promo_file=promo_file) -> bytes:
            download_url = client.get_download_url(promo_file["filename"])
            return client.download_file(download_url)

        result = save_delta_file(
            chain_id=promo_file["chain_id"],
            store_id=promo_file["store_id"],
            filename=promo_file["filename"],
            file_date=promo_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promo_laibcatalog(
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

    promo_files = find_delta_files(files, FILE_TYPE, filename_key="fileName")

    if test:
       promo_files = filter_test_store_files(promo_files)

    if not promo_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    downloaded_files = []

    for promo_file in promo_files:

        resolved_chain_id = promo_file.get("chain_id") or chain_id

        async def fetch_content(promo_file=promo_file) -> bytes:
            download_url = client.build_download_url(promo_file["filename"])
            return await client.download_file(download_url)

        result = await save_delta_file_async(
            chain_id=resolved_chain_id,
            store_id=promo_file["store_id"],
            filename=promo_file["filename"],
            file_date=promo_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promo_carrefour(test: bool = False) -> list:

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

    promo_files = find_delta_files(normalized, FILE_TYPE, filename_key="filename")

    if test:
       promo_files = filter_test_store_files(promo_files)

    if not promo_files:
        logger.warning("No %s files found for Carrefour", FILE_TYPE)
        return []

    downloaded_files = []

    for promo_file in promo_files:

        filename = promo_file["filename"]

        download_url = urljoin(
            f"{client.base_url}/", f"{path.strip('/')}/{filename}",
        )

        async def fetch_content(download_url=download_url) -> bytes:
            return await client.download_file(download_url)

        result = await save_delta_file_async(
            chain_id=promo_file["chain_id"],
            store_id=promo_file["store_id"],
            filename=filename,
            file_date=promo_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promo_html(source: dict, test: bool = False) -> list:

    data_dir = get_data_dir(test)

    name = source["name"]
    listing = source["listing"]
    categories = source["categories"]

    promo_params = categories.get("file_types", {}).get(FILE_TYPE)

    if promo_params is None:
        logger.warning("No '%s' file_type configured for %s", FILE_TYPE, name)
        return []

    base_url = categories.get("endpoint", listing["base_url"])

    client = HtmlFileLinkClient(
        name=name,
        base_url=base_url,
        extraction_mode=source["extraction_mode"],
        filename_column=source.get("filename_column"),
        filename_source=source["filename_source"],
        filename_param=source.get("filename_param"),
    )

    logger.info("Listing files for %s (HTML)...", name)

    try:
        candidates = await get_all_html_candidates(
            client,
            {**listing, "file_type_params": promo_params},
            "file_type_params",
            parse_filename,
        )
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return []

    href_by_filename = {
        candidate.filename: candidate.href
        for candidate in candidates
        if candidate.filename
    }

    promo_files = find_delta_files(
        [{"filename": filename} for filename in href_by_filename],
        FILE_TYPE,
        filename_key="filename",
    )

    if test:
       promo_files = filter_test_store_files(promo_files)

    if not promo_files:
        logger.warning("No %s files found for %s", FILE_TYPE, name)
        return []

    downloaded_files = []

    for promo_file in promo_files:

        filename = promo_file["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            response = await client._get_with_retry(href)
            return response.content

        result = await save_delta_file_async(
            chain_id=promo_file["chain_id"],
            store_id=promo_file["store_id"],
            filename=filename,
            file_date=promo_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promo_mishnatyosef(test: bool = False) -> list:

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

    promo_files = find_delta_files(normalized, FILE_TYPE, filename_key="filename")

    if test:
       promo_files = filter_test_store_files(promo_files)

    if not promo_files:
        logger.warning("No %s files found for Mishnat Yosef", FILE_TYPE)
        return []

    downloaded_files = []

    for promo_file in promo_files:

        filename = promo_file["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_delta_file_async(
            chain_id=promo_file["chain_id"],
            store_id=promo_file["store_id"],
            filename=filename,
            file_date=promo_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


async def download_promo_wolt(test: bool = False) -> list:

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

    promo_files = find_delta_files(normalized, FILE_TYPE, filename_key="filename")

    if test:
       promo_files = filter_test_store_files(promo_files)

    if not promo_files:
        logger.warning("No %s files found for Wolt", FILE_TYPE)
        return []

    downloaded_files = []

    for promo_file in promo_files:

        filename = promo_file["filename"]
        href = href_by_filename[filename]

        async def fetch_content(href=href) -> bytes:
            return await client.download_file(href)

        result = await save_delta_file_async(
            chain_id=promo_file["chain_id"],
            store_id=promo_file["store_id"],
            filename=filename,
            file_date=promo_file["file_date"],
            data_dir=data_dir,
            test=test,
            fetch_content=fetch_content,
            subfolder=SUBFOLDER,
        )

        if result:
            downloaded_files.append(result)

    return downloaded_files


if __name__ == "__main__":
    run(
        FILE_TYPE,
        download_promo_publishedprices,
        download_promo_binaprojects,
        download_promo_laibcatalog,
        download_promo_html,
        download_promo_carrefour,
        download_promo_mishnatyosef,
        download_promo_wolt,
    )