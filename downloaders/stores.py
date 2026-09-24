# downloaders/stores.py
"""
Stores files are published once per chain (not once per store, unlike
PriceFull/PromoFull/Price/Promo), so this module keeps its own
find-latest logic (GENERIC_STORES_FILE_RE / find_latest_matching_file)
rather than sharing full_family.py or delta_family.py. It does reuse the
protocol-level helpers from common.py.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from logging_config import setup_general_logging
from clients.publishedprices import PublishedPricesClient
from clients.binaprojects import BinaProjectsClient
from clients.laibcatalog import LaibcatalogClient
from clients.carrefour import CarrefourClient
from clients.html_client import HtmlFileLinkClient
from clients.mishnatyosef import MishnatYosefClient
from clients.wolt import WoltClient

from downloaders.common import (
    get_data_dir,
    save_file,
    save_file_async,
    list_publishedprices_entries_recursive,
    normalize_carrefour_listing,
    normalize_wolt_file_urls,
    normalize_mishnatyosef_listing,
)
from downloaders.runner import run


setup_general_logging()

logger = logging.getLogger(__name__)

FILE_TYPE = "Stores"
SUBFOLDER = "stores"


# Merged regex covering PublishedPrices, BinaProjects, and Laibcatalog
# Stores filenames. Handles both hyphen-separated (date-time) and
# concatenated (12-digit YYYYMMDDHHMM) timestamp formats, optional
# subchain/store segments, optional "Full" suffix, and gz/xml/xml.gz
# extensions.
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


def find_latest_matching_file(
    files: list[dict],
    filename_key: str,
    date_key: str | None = None,
    date_format: str | None = None,
) -> dict | None:
    """
    Generic latest-file finder for GENERIC_STORES_FILE_RE-matching sources.

    date_key/date_format: for sources where the timestamp lives in a
    separate metadata field rather than being embedded in the filename
    (e.g. BinaProjects' 'DateFile'). If omitted, the date is parsed from
    the filename's own YYYYMMDD date group. The time portion of the
    filename is intentionally ignored because Stores files are normally
    published once per day.
    """

    latest = None

    for file in files:

        filename = (file.get(filename_key) or "").strip()

        if not filename:
            continue

        match = GENERIC_STORES_FILE_RE.match(filename)

        if not match:
            continue

        if date_key is not None:

            date_text = (file.get(date_key) or "").strip()

            if not date_text:
                continue

            try:
                timestamp = datetime.strptime(date_text, date_format)
            except ValueError:
                continue

        else:

            date_part = match.group("date")

            try:
                timestamp = datetime.strptime(date_part, "%Y%m%d")
            except ValueError:
                continue

        if latest is None or timestamp > latest["timestamp"]:
            latest = {
                "filename": filename,
                "chain_id": match.group("chain_id"),
                "timestamp": timestamp,
            }

    return latest


def find_latest_stores_file(
    response_json: dict,
    cd: str = "/",
) -> dict | None:

    logger.info(
        "PublishedPrices: received %d entries in %s",
        len(response_json.get("aaData", [])),
        cd,
    )

    for entry in response_json.get("aaData", []):

        fname = entry.get("fname", "")

        if "Stores" in fname:
            logger.info("PublishedPrices Stores candidate: %s", fname)

    latest = find_latest_matching_file(
        response_json.get("aaData", []), filename_key="fname",
    )

    if latest is None:
        return None

    path = (
        f"{cd.strip('/')}/{latest['filename']}" if cd != "/" else latest["filename"]
    )

    latest["url"] = f"{PublishedPricesClient.BASE_URL}/file/d/{path}"

    return latest


def find_stores_file_recursive(
    client: PublishedPricesClient,
    cd: str = "/",
    depth: int = 0,
    max_depth: int = 2,
) -> dict | None:

    try:
        response_json = client.get_files(cd=cd)
    except Exception:
        logger.exception("Failed listing '%s' for %s", cd, client.username)
        return None

    latest = find_latest_stores_file(response_json, cd=cd)

    if latest is not None:
        return latest

    if depth >= max_depth:
        return None

    for entry in response_json.get("aaData", []):

        fname = entry.get("fname")

        if not fname:
            continue

        if "." in fname:
            continue

        logger.info(
            "'%s' looks like a folder for %s — recursing",
            fname, client.username,
        )

        sub_cd = f"{cd.rstrip('/')}/{fname}"

        found = find_stores_file_recursive(
            client, cd=sub_cd, depth=depth + 1, max_depth=max_depth,
        )

        if found is not None:
            return found

    return None


def find_latest_stores_file_binaprojects(files: list[dict]) -> dict | None:
    return find_latest_matching_file(
        files, filename_key="FileNm", date_key="DateFile",
        date_format="%H:%M %d/%m/%Y",
    )


def find_latest_stores_file_laibcatalog(files: list[dict]) -> dict | None:
    return find_latest_matching_file(files, filename_key="fileName")


def get_storage_path(chain_id: str, data_dir: Path) -> Path:
    return data_dir / chain_id / SUBFOLDER


def download_stores_publishedprices(
    name: str,
    username: str,
    password: str = "",
    test: bool = False,
) -> Path | None:

    data_dir = get_data_dir(test)
    client = PublishedPricesClient(username, password)

    logger.info(
        "Logging in and listing files for %s (%s)...", name, username,
    )

    try:
        client.login()
    except Exception:
        logger.exception("Failed logging in for %s", username)
        return None

    latest = find_stores_file_recursive(client)

    if latest is None:
        logger.warning("No Stores file found for %s", username)
        return None

    def fetch_content() -> bytes:
        return client.download_file(latest["url"])

    return save_file(
        get_storage_path(latest["chain_id"], data_dir),
        latest["filename"],
        test,
        fetch_content,
    )


def download_stores_binaprojects(
    name: str,
    url: str,
    test: bool = False,
) -> Path | None:

    data_dir = get_data_dir(test)
    client = BinaProjectsClient(url)

    logger.info("Listing files for %s (BinaProjects)...", name)

    try:
        files = client.get_hok_files(file_type=1)
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return None

    latest = find_latest_stores_file_binaprojects(files)

    if latest is None:
        logger.warning("No Stores file found for %s", name)
        return None

    def fetch_content() -> bytes:
        return client.download_file(latest["filename"])

    return save_file(
        get_storage_path(latest["chain_id"], data_dir),
        latest["filename"],
        test,
        fetch_content,
    )


async def download_stores_laibcatalog(
    name: str,
    url: str,
    chain_id: str,
    test: bool = False,
) -> Path | None:

    data_dir = get_data_dir(test)
    client = LaibcatalogClient(chain_id)

    logger.info("Listing files for %s (Laibcatalog)...", name)

    try:
        files = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return None

    latest = find_latest_stores_file_laibcatalog(files)

    if latest is None:
        logger.warning("No Stores file found for %s", name)
        return None

    resolved_chain_id = latest.get("chain_id") or chain_id

    async def fetch_content() -> bytes:
        download_url = client.build_download_url(latest["filename"])
        return await client.download_file(download_url)

    return await save_file_async(
        get_storage_path(resolved_chain_id, data_dir),
        latest["filename"],
        test,
        fetch_content,
    )


async def download_stores_carrefour(test: bool = False) -> Path | None:

    data_dir = get_data_dir(test)
    client = CarrefourClient()

    logger.info("Listing files for Carrefour...")

    try:
        listing = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list for Carrefour")
        return None

    path = listing["path"]
    normalized = normalize_carrefour_listing(listing["files"])

    latest = find_latest_matching_file(normalized, filename_key="filename")

    if latest is None:
        logger.warning("No Stores file found for Carrefour")
        return None

    filename = latest["filename"]

    download_url = urljoin(
        f"{client.base_url}/", f"{path.strip('/')}/{filename}",
    )

    async def fetch_content() -> bytes:
        return await client.download_file(download_url)

    return await save_file_async(
        get_storage_path(latest["chain_id"], data_dir), filename, test, fetch_content,
    )


async def download_stores_html(source: dict, test: bool = False) -> Path | None:

    data_dir = get_data_dir(test)

    name = source["name"]
    listing = source["listing"]
    categories = source["categories"]

    stores_params = categories.get("file_types", {}).get(FILE_TYPE)

    if stores_params is None:
        logger.warning("No 'Stores' file_type configured for %s", name)
        return None

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
        # NOTE: unlike PriceFull/PromoFull/Price/Promo, Stores files are
        # published once per day, so this is a single request rather
        # than the paginated crawl in common.get_all_html_candidates.
        candidates = await client.get_candidates(params=stores_params)
    except Exception:
        logger.exception("Failed getting file list for %s", name)
        return None

    href_by_filename = {
        candidate.filename: candidate.href
        for candidate in candidates
        if candidate.filename
    }

    latest = find_latest_matching_file(
        [{"filename": filename} for filename in href_by_filename],
        filename_key="filename",
    )

    if latest is None:
        logger.warning("No Stores file found for %s", name)
        return None

    filename = latest["filename"]
    href = href_by_filename[filename]

    async def fetch_content() -> bytes:
        response = await client._get_with_retry(href)
        return response.content

    return await save_file_async(
        get_storage_path(latest["chain_id"], data_dir), filename, test, fetch_content,
    )


async def download_stores_mishnatyosef(test: bool = False) -> Path | None:

    data_dir = get_data_dir(test)
    client = MishnatYosefClient()

    logger.info("Listing files for Mishnat Yosef...")

    try:
        files = await client.get_files()
    except Exception:
        logger.exception("Failed getting file list for Mishnat Yosef")
        return None

    normalized, href_by_filename = normalize_mishnatyosef_listing(
        files, FILE_TYPE,
    )

    latest = find_latest_matching_file(normalized, filename_key="filename")

    if latest is None:
        logger.warning("No Stores file found for Mishnat Yosef")
        return None

    filename = latest["filename"]
    href = href_by_filename[filename]

    async def fetch_content() -> bytes:
        return await client.download_file(href)

    return await save_file_async(
        get_storage_path(latest["chain_id"], data_dir), filename, test, fetch_content,
    )


async def download_stores_wolt(test: bool = False) -> Path | None:

    data_dir = get_data_dir(test)
    client = WoltClient()

    logger.info("Listing date pages for Wolt...")

    try:
        date_pages = await client.get_date_pages()
    except Exception:
        logger.exception("Failed getting date pages for Wolt")
        return None

    if not date_pages:
        logger.warning("No date pages found for Wolt")
        return None

    try:
        file_urls = await client.get_files(date_pages[0])
    except Exception:
        logger.exception("Failed getting file list for Wolt")
        return None

    normalized, href_by_filename = normalize_wolt_file_urls(file_urls)

    latest = find_latest_matching_file(normalized, filename_key="filename")

    if latest is None:
        logger.warning("No Stores file found for Wolt")
        return None

    filename = latest["filename"]
    href = href_by_filename[filename]

    async def fetch_content() -> bytes:
        return await client.download_file(href)

    return await save_file_async(
        get_storage_path(latest["chain_id"], data_dir), filename, test, fetch_content,
    )


if __name__ == "__main__":
    run(
        FILE_TYPE,
        download_stores_publishedprices,
        download_stores_binaprojects,
        download_stores_laibcatalog,
        download_stores_html,
        download_stores_carrefour,
        download_stores_mishnatyosef,
        download_stores_wolt,
        test_help="Use test_feeds directory",
    )