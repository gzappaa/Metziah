import argparse
import asyncio
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from logging_config import setup_general_logging
from clients.publishedprices import PublishedPricesClient
from clients.binaprojects import BinaProjectsClient
from clients.laibcatalog import LaibcatalogClient


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
GENERIC_STORES_FILE_RE = re.compile(
    r"^Stores(?:Full)?"
    r"(?P<chain_id>\d+)"
    r"(?:-\d+)*"
    r"-(?P<date>\d{8})"
    r"-?(?P<time>\d{4,6})"
    r"\.(?:gz|xml(?:\.gz)?)$",
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
    (e.g. BinaProjects' 'DateFile'). If omitted, the timestamp is parsed
    from the filename's own date+time groups.
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
            time_part = match.group("time")

            # time is either 4 digits (HHMM) or 6 digits (HHMMSS)
            fmt = (
                "%Y%m%d%H%M%S"
                if len(time_part) == 6
                else "%Y%m%d%H%M"
            )

            try:

                timestamp = datetime.strptime(
                    date_part + time_part,
                    fmt,
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

    chain_id = latest["chain_id"]

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

    destination = (
        folder
        / latest["filename"]
    )

    if destination.exists():

        logger.info(
            "UP TO DATE: %s",
            latest["filename"],
        )

        return destination

    logger.info(
        "DOWNLOAD: %s",
        latest["filename"],
    )

    try:

        response = client._get_with_retry(
            latest["url"]
        )

        destination.write_bytes(
            response.content
        )

    except Exception:

        logger.exception(
            "FAILED downloading %s",
            latest["filename"],
        )

        return None

    for old_file in folder.glob(
        "Stores*"
    ):

        if old_file.name != latest["filename"]:

            logger.info(
                "REMOVE OLD: %s",
                old_file.name,
            )

            old_file.unlink()

    return destination


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

    chain_id = latest["chain_id"]

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

    destination = (
        folder
        / latest["filename"]
    )

    if destination.exists():

        logger.info(
            "UP TO DATE: %s",
            latest["filename"],
        )

        return destination

    logger.info(
        "DOWNLOAD: %s",
        latest["filename"],
    )

    try:

        download_response = client._get_with_retry(
            f"{client.base_url}/Download.aspx",
            params={
                "FileNm": latest["filename"],
            },
        )

        download_json = (
            download_response.json()
        )

        if (
            not download_json
            or not download_json[0].get(
                "SPath"
            )
        ):

            logger.warning(
                "No SPath returned for %s",
                latest["filename"],
            )

            return None

        file_url = download_json[0]["SPath"]

        response = client._get_with_retry(
            file_url
        )

        destination.write_bytes(
            response.content
        )

    except Exception:

        logger.exception(
            "FAILED downloading %s",
            latest["filename"],
        )

        return None

    for old_file in folder.glob(
        "Stores*"
    ):

        if old_file.name != latest["filename"]:

            logger.info(
                "REMOVE OLD: %s",
                old_file.name,
            )

            old_file.unlink()

    return destination


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

    folder = get_storage_path(
        resolved_chain_id,
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

    destination = (
        folder
        / latest["filename"]
    )

    if destination.exists():

        logger.info(
            "UP TO DATE: %s",
            latest["filename"],
        )

        return destination

    logger.info(
        "DOWNLOAD: %s",
        latest["filename"],
    )

    try:

        download_url = client.build_download_url(
            latest["filename"]
        )

        content = await client.download_file(
            download_url
        )

        destination.write_bytes(content)

    except Exception:

        logger.exception(
            "FAILED downloading %s",
            latest["filename"],
        )

        return None

    for old_file in folder.glob(
        "Stores*"
    ):

        if old_file.name != latest["filename"]:

            logger.info(
                "REMOVE OLD: %s",
                old_file.name,
            )

            old_file.unlink()

    return destination


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