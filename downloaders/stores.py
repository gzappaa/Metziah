import argparse
import asyncio
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

from logging_config import setup_general_logging
from clients.publishedprices import PublishedPricesClient
from clients.binaprojects import BinaProjectsClient
from clients.laibcatalog import LaibcatalogClient
from clients.carrefour import CarrefourClient
from clients.html_client import HtmlFileLinkClient
from clients.html_config import SOURCES as HTML_SOURCES
from clients.mishnatyosef import MishnatYosefClient
from clients.wolt import WoltClient


setup_general_logging()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "feeds"
TEST_DATA_DIR = BASE_DIR / "data" / "test_feeds"

SOURCES_FILE = (
    BASE_DIR
    / "monitoring"
    / "data"
    / "supermarket_sources.json"
)


# Merged regex covering PublishedPrices, BinaProjects, and Laibcatalog
# Stores filenames. Handles both hyphen-separated (date-time) and
# concatenated (12-digit YYYYMMDDHHMM) timestamp formats, optional
# subchain/store segments, optional "Full" suffix, and gz/xml/xml.gz
# extensions.
#
# NOTE: not yet verified against real filenames from the HTML-based
# sources (Hazi Hinam, Super-Pharm, Shufersal, City Market, Netiv
# Hesed) or Carrefour/Mishnat Yosef/Wolt. Check real data before
# relying on this in prod for those chains.
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

                timestamp = datetime.strptime(
                    date_text,
                    date_format,
                )

            except ValueError:

                continue

        else:

            date_part = match.group("date")

            try:

                timestamp = datetime.strptime(
                    date_part,
                    "%Y%m%d",
                )

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
            logger.info(
                "PublishedPrices Stores candidate: %s",
                fname,
            )

    latest = find_latest_matching_file(
        response_json.get("aaData", []),
        filename_key="fname",
    )

    if latest is None:
        return None

    path = (
        f"{cd.strip('/')}/{latest['filename']}"
        if cd != "/"
        else latest["filename"]
    )

    latest["url"] = (
        f"{PublishedPricesClient.BASE_URL}"
        f"/file/d/{path}"
    )

    return latest


def find_stores_file_recursive(
    client: PublishedPricesClient,
    cd: str = "/",
    depth: int = 0,
    max_depth: int = 2,
) -> dict | None:

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

        return None

    latest = find_latest_stores_file(
        response_json,
        cd=cd,
    )

    if latest is not None:
        return latest

    if depth >= max_depth:
        return None

    for entry in response_json.get(
        "aaData",
        [],
    ):

        fname = entry.get("fname")

        if not fname:
            continue

        # Heuristic: folders have no file extension
        if "." in fname:
            continue

        logger.info(
            "'%s' looks like a folder for %s — recursing",
            fname,
            client.username,
        )

        sub_cd = (
            f"{cd.rstrip('/')}/{fname}"
        )

        found = find_stores_file_recursive(
            client,
            cd=sub_cd,
            depth=depth + 1,
            max_depth=max_depth,
        )

        if found is not None:
            return found

    return None


def find_latest_stores_file_binaprojects(
    files: list[dict],
) -> dict | None:

    return find_latest_matching_file(
        files,
        filename_key="FileNm",
        date_key="DateFile",
        date_format="%H:%M %d/%m/%Y",
    )


def find_latest_stores_file_laibcatalog(
    files: list[dict],
) -> dict | None:

    return find_latest_matching_file(
        files,
        filename_key="fileName",
    )


def load_sources(
    source_type: str,
) -> list[dict]:

    with open(
        SOURCES_FILE,
        encoding="utf-8",
    ) as f:

        entries = json.load(f)

    results = []

    for entry in entries:

        for source in entry.get(
            "sources",
            [],
        ):

            if source.get(
                "type"
            ) != source_type:
                continue

            results.append(
                {
                    "name": entry["name"],
                    "url": source.get("url"),
                    "credentials": source.get(
                        "credentials",
                        [],
                    ),
                    "chain_id": source.get("chain_id"),
                }
            )

    return results


def load_publishedprices_credentials(
    source_type: str,
) -> list[dict]:

    with open(
        SOURCES_FILE,
        encoding="utf-8",
    ) as f:

        entries = json.load(f)

    results = []

    for entry in entries:

        for source in entry.get(
            "sources",
            [],
        ):

            if source.get(
                "type"
            ) != source_type:
                continue

            for credential in source.get(
                "credentials",
                [],
            ):

                username = credential.get(
                    "username"
                )

                if not username:
                    continue

                results.append(
                    {
                        "name": entry["name"],
                        "username": username,
                        "password": credential.get(
                            "password",
                            "",
                        ),
                    }
                )

    return results


def get_storage_path(
    chain_id: str,
    data_dir: Path,
) -> Path:

    return (
        data_dir
        / chain_id
        / "stores"
    )


def save_stores_file(
    chain_id: str,
    filename: str,
    data_dir: Path,
    test: bool,
    fetch_content: Callable[[], bytes],
) -> Path | None:
    """
    Shared save path for sync downloaders: prepares the per-chain
    folder (wiping it in test mode), skips the network call if the
    file is already on disk, otherwise calls fetch_content() to get
    the bytes, writes them, and removes stale Stores* files.

    fetch_content is only invoked when a download is actually needed,
    and any exception it raises is treated as a failed download.
    """

    folder = get_storage_path(
        chain_id,
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

    for old_file in folder.glob("Stores*"):

        if old_file.name != filename:

            logger.info(
                "REMOVE OLD: %s",
                old_file.name,
            )

            old_file.unlink()

    return destination


async def save_stores_file_async(
    chain_id: str,
    filename: str,
    data_dir: Path,
    test: bool,
    fetch_content,
) -> Path | None:
    """
    Async counterpart to save_stores_file — same behavior, but
    awaits fetch_content() instead of calling it directly.
    """

    folder = get_storage_path(
        chain_id,
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

    for old_file in folder.glob("Stores*"):

        if old_file.name != filename:

            logger.info(
                "REMOVE OLD: %s",
                old_file.name,
            )

            old_file.unlink()

    return destination


def download_stores_publishedprices(
    name: str,
    username: str,
    password: str = "",
    test: bool = False,
) -> Path | None:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = PublishedPricesClient(
        username
    )

    client.username = username
    client.password = password

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

        return None

    latest = find_stores_file_recursive(
        client
    )

    if latest is None:

        logger.warning(
            "No Stores file found for %s",
            username,
        )

        return None

    def fetch_content() -> bytes:

        response = client._get_with_retry(
            latest["url"]
        )

        return response.content

    return save_stores_file(
        chain_id=latest["chain_id"],
        filename=latest["filename"],
        data_dir=data_dir,
        test=test,
        fetch_content=fetch_content,
    )


def download_stores_binaprojects(
    name: str,
    url: str,
    test: bool = False,
) -> Path | None:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = BinaProjectsClient(
        name
    )

    client.source_url = url

    parsed = urlparse(url)

    client.base_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "",
            "",
            "",
            "",
        )
    )

    logger.info(
        "Listing files for %s (BinaProjects)...",
        name,
    )

    try:

        client.get_main_page()

        files = client.get_hok_files(
            file_type=1
        )

    except Exception:

        logger.exception(
            "Failed getting file list for %s",
            name,
        )

        return None

    latest = find_latest_stores_file_binaprojects(
        files
    )

    if latest is None:

        logger.warning(
            "No Stores file found for %s",
            name,
        )

        return None

    def fetch_content() -> bytes:

        download_response = client._get_with_retry(
            f"{client.base_url}/Download.aspx",
            params={
                "FileNm": latest["filename"],
            },
        )

        download_json = download_response.json()

        if (
            not download_json
            or not download_json[0].get("SPath")
        ):

            raise RuntimeError(
                f"No SPath returned for {latest['filename']}"
            )

        file_url = download_json[0]["SPath"]

        response = client._get_with_retry(file_url)

        return response.content

    return save_stores_file(
        chain_id=latest["chain_id"],
        filename=latest["filename"],
        data_dir=data_dir,
        test=test,
        fetch_content=fetch_content,
    )


async def download_stores_laibcatalog(
    name: str,
    url: str,
    chain_id: str,
    test: bool = False,
) -> Path | None:

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    client = LaibcatalogClient(name)

    # Bypass the DB-backed _configure()/_get_source() lookup — we
    # already have url/chain_id from supermarket_sources.json,
    # same pattern used for PublishedPricesClient above.
    client.source_url = url
    client.chain_id = chain_id

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

        return None

    latest = find_latest_stores_file_laibcatalog(
        files
    )

    if latest is None:

        logger.warning(
            "No Stores file found for %s",
            name,
        )

        return None

    resolved_chain_id = (
        latest.get("chain_id") or chain_id
    )

    async def fetch_content() -> bytes:

        download_url = client.build_download_url(
            latest["filename"]
        )

        return await client.download_file(download_url)

    return await save_stores_file_async(
        chain_id=resolved_chain_id,
        filename=latest["filename"],
        data_dir=data_dir,
        test=test,
        fetch_content=fetch_content,
    )


async def download_stores_carrefour(
    test: bool = False,
) -> Path | None:


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

        return None

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

    latest = find_latest_matching_file(
        normalized,
        filename_key="filename",
    )

    if latest is None:

        logger.warning(
            "No Stores file found for Carrefour"
        )

        return None

    filename = latest["filename"]

    download_url = urljoin(
        f"{client.base_url}/",
        f"{path.strip('/')}/{filename}",
    )

    async def fetch_content() -> bytes:

        return await client.download_file(
            download_url
        )

    return await save_stores_file_async(
        chain_id=latest["chain_id"],
        filename=filename,
        data_dir=data_dir,
        test=test,
        fetch_content=fetch_content,
    )


async def download_stores_html(
    source: dict,
    test: bool = False,
) -> Path | None:
    """
    Generic Stores downloader for every publisher configured in
    clients/html_config.py (Hazi Hinam, Super-Pharm, Shufersal,
    City Market, Netiv Hesed) — one function instead of five.

    NOTE: only fetches the configured listing/category page as-is,
    with the 'Stores' file_type params. Doesn't yet handle
    pagination, sort params, or Shufersal's separate category
    endpoint's own quirks — add if a Stores file turns out not to
    be on page 1 for some chain. Also unverified: whether these
    chains' Stores filenames match GENERIC_STORES_FILE_RE.
    """

    data_dir = (
        TEST_DATA_DIR
        if test
        else DATA_DIR
    )

    name = source["name"]
    listing = source["listing"]
    categories = source["categories"]

    stores_params = categories.get(
        "file_types", {}
    ).get("Stores")

    if stores_params is None:

        logger.warning(
            "No 'Stores' file_type configured for %s",
            name,
        )

        return None

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

        candidates = await client.get_candidates(
            params=stores_params
        )

    except Exception:

        logger.exception(
            "Failed getting file list for %s",
            name,
        )

        return None

    href_by_filename = {
        candidate.filename: candidate.href
        for candidate in candidates
        if candidate.filename
    }

    latest = find_latest_matching_file(
        [
            {"filename": filename}
            for filename in href_by_filename
        ],
        filename_key="filename",
    )

    if latest is None:

        logger.warning(
            "No Stores file found for %s",
            name,
        )

        return None

    filename = latest["filename"]
    href = href_by_filename[filename]

    async def fetch_content() -> bytes:

        response = await client._get_with_retry(href)

        return response.content

    return await save_stores_file_async(
        chain_id=latest["chain_id"],
        filename=filename,
        data_dir=data_dir,
        test=test,
        fetch_content=fetch_content,
    )


async def download_stores_mishnatyosef(
    test: bool = False,
) -> Path | None:
    """
    NOTE: key names in Mishnat Yosef's listing JSON haven't been
    verified — assuming common 'name'/'fileName' + 'url'/'href'
    style keys. Adjust once we've inspected a real response.
    """

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

        return None

    normalized = []
    href_by_filename = {}

    for entry in files:

        if entry.get("type") != "Stores":
            continue

        filename = entry.get("name")
        url = entry.get("url")

        if not filename or not url:
            continue

        normalized.append(
            {"filename": filename}
        )

        href_by_filename[filename] = url

    latest = find_latest_matching_file(
        normalized,
        filename_key="filename",
    )

    if latest is None:

        logger.warning(
            "No Stores file found for Mishnat Yosef"
        )

        return None

    filename = latest["filename"]
    href = href_by_filename[filename]

    async def fetch_content() -> bytes:

        return await client.download_file(href)

    return await save_stores_file_async(
        chain_id=latest["chain_id"],
        filename=filename,
        data_dir=data_dir,
        test=test,
        fetch_content=fetch_content,
    )


async def download_stores_wolt(
    test: bool = False,
) -> Path | None:
    """
    Only checks the most recent date page (mirrors WoltClient.check()).
    If Wolt doesn't republish Stores on every date page, this will
    need to walk back through older pages until one is found.
    """

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

        return None

    if not date_pages:

        logger.warning(
            "No date pages found for Wolt"
        )

        return None

    try:

        file_urls = await client.get_files(
            date_pages[0]
        )

    except Exception:

        logger.exception(
            "Failed getting file list for Wolt"
        )

        return None

    normalized = []
    href_by_filename = {}

    for url in file_urls:

        filename = urlparse(url).path.rsplit("/", 1)[-1]

        if not filename:
            continue

        normalized.append(
            {"filename": filename}
        )

        href_by_filename[filename] = url

    latest = find_latest_matching_file(
        normalized,
        filename_key="filename",
    )

    if latest is None:

        logger.warning(
            "No Stores file found for Wolt"
        )

        return None

    filename = latest["filename"]
    href = href_by_filename[filename]

    async def fetch_content() -> bytes:

        return await client.download_file(href)

    return await save_stores_file_async(
        chain_id=latest["chain_id"],
        filename=filename,
        data_dir=data_dir,
        test=test,
        fetch_content=fetch_content,
    )


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Use test_feeds directory",
    )

    args = parser.parse_args()

    pp_sources = load_publishedprices_credentials(
        "publishedprices"
    )

    logger.info(
        "Found %d publishedprices sources",
        len(pp_sources),
    )

    for source in pp_sources:

        try:

            download_stores_publishedprices(
                source["name"],
                source["username"],
                source["password"],
                test=args.test,
            )

        except Exception:

            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    bina_sources = load_sources(
        "binaprojects"
    )

    logger.info(
        "Found %d binaprojects sources",
        len(bina_sources),
    )

    for source in bina_sources:

        try:

            download_stores_binaprojects(
                source["name"],
                source["url"],
                test=args.test,
            )

        except Exception:

            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    laib_sources = load_sources(
        "laibcatalog"
    )

    logger.info(
        "Found %d laibcatalog sources",
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

            asyncio.run(
                download_stores_laibcatalog(
                    source["name"],
                    source["url"],
                    source["chain_id"],
                    test=args.test,
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

            asyncio.run(
                download_stores_html(
                    source,
                    test=args.test,
                )
            )

        except Exception:

            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    try:

        asyncio.run(
            download_stores_carrefour(
                test=args.test
            )
        )

    except Exception:

        logger.exception(
            "Failed processing Carrefour"
        )

    try:

        asyncio.run(
            download_stores_mishnatyosef(
                test=args.test
            )
        )

    except Exception:

        logger.exception(
            "Failed processing Mishnat Yosef"
        )

    try:

        asyncio.run(
            download_stores_wolt(
                test=args.test
            )
        )

    except Exception:

        logger.exception(
            "Failed processing Wolt"
        )