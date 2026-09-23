# downloaders/common.py
"""
Generic, protocol-agnostic helpers shared by every downloader module
(pricesfull.py, promosfull.py, prices.py, promos.py, stores.py).

Nothing in here knows about "PriceFull" vs "Stores" vs any other file
type — that logic lives in full_family.py / delta_family.py / stores.py.
This module only knows about: where things get saved on disk, and how
to talk to each of the seven source protocols to get a raw file listing.
"""

import asyncio
import logging
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
import shutil
from clients.publishedprices import PublishedPricesClient
from clients.html_client import Candidate
import json



logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "feeds"
TEST_DATA_DIR = BASE_DIR / "data" / "test_feeds"

IGNORED_BINA_STORES = {
    ("7290058156016", "017", "396"),
}

def normalize_store_id(store_id) -> str:
    try:
        return str(int(store_id))
    except (TypeError, ValueError):
        return str(store_id).strip()



def get_data_dir(test: bool) -> Path:
    return TEST_DATA_DIR if test else DATA_DIR


def _load_html_cache(source_name: str) -> list[Candidate]:
    cache_path = (
        BASE_DIR
        / "data"
        / "cache"
        / f"{source_name}.json"
    )

    if not cache_path.is_file():
        logger.warning(
            "HTML cache not found for %s: %s",
            source_name,
            cache_path,
        )
        return []

    try:
        with cache_path.open("r", encoding="utf-8") as file:
            cache = json.load(file)
    except Exception:
        logger.exception(
            "Failed reading HTML cache for %s",
            source_name,
        )
        return []

    return [
        Candidate(
            text=item.get("text", ""),
            href=item["url"],
            filename=item.get("filename"),
            file_size=item.get("file_size"),
        )
        for item in cache.get("files", [])
        if item.get("url")
    ]


# --- saving to disk ------------------------------------------------------

def save_file(
    folder: Path,
    filename: str,
    test: bool,
    fetch_content,
    cleanup=None,
) -> Path | None:
    """
    Generic sync save: wipes the folder in test mode, skips the download
    if the file already exists, otherwise fetches and writes it.

    If `cleanup(folder, filename)` is given, it's called after a
    successful (non-test) write — e.g. to remove older same-day files
    now that the new one is safely on disk.
    """


    folder.mkdir(parents=True, exist_ok=True)

    destination = folder / filename

    if destination.exists():
        logger.debug("UP TO DATE: %s", filename)
        return destination

    logger.debug("DOWNLOADING: %s", filename)

    try:
        content = fetch_content()
        destination.write_bytes(content)
    except Exception:
        logger.exception("FAILED downloading %s", filename)
        return None

    if not test and cleanup is not None:
        cleanup(folder, filename)

    return destination


def clear_test_feeds() -> None:
    if not TEST_DATA_DIR.exists():
        return

    logger.warning("TEST MODE: clearing %s", TEST_DATA_DIR)

    for path in TEST_DATA_DIR.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


async def save_file_async(
    folder: Path,
    filename: str,
    test: bool,
    fetch_content,
    cleanup=None,
) -> Path | None:
    """Async counterpart to save_file."""


    folder.mkdir(parents=True, exist_ok=True)

    destination = folder / filename

    if destination.exists():
        logger.debug("UP TO DATE: %s", filename)
        return destination

    logger.debug("DOWNLOAD: %s", filename)

    try:
        content = await fetch_content()
        destination.write_bytes(content)
    except Exception:
        logger.exception("FAILED downloading %s", filename)
        return None

    if not test and cleanup is not None:
        cleanup(folder, filename)

    return destination


def get_test_stores():
    """
    Return the (chain_id, store_id) pairs represented by PriceFull
    files already downloaded under data/test_feeds.
    """
    test_feeds_dir = BASE_DIR / "data" / "test_feeds"
    pricesfull_dir = test_feeds_dir

    test_stores = set()

    for price_file in pricesfull_dir.glob("*/*/pricesfull/*"):
        if not price_file.is_file():
            continue

        chain_id = price_file.parent.parent.parent.name
        store_id = price_file.parent.parent.name.zfill(3)

        test_stores.add((chain_id, store_id))

    return test_stores


def filter_test_stores(latest_files):
    test_stores = get_test_stores()

    return {
        key: latest
        for key, latest in latest_files.items()
        if (latest["chain_id"], latest["store_id"]) in test_stores
    }

def filter_test_store_files(files):
    test_stores = get_test_stores()

    return [
        file
        for file in files
        if (file["chain_id"], file["store_id"]) in test_stores
    ]


def trim_for_test(
    latest_files: dict,
    name: str,
    limit: int = 5,
) -> dict:
    """Caps a {key: file} mapping to `limit` entries in test mode."""

    if len(latest_files) <= limit:
        return latest_files

    logger.info("TEST MODE: keeping first %d stores for %s", limit, name)

    return dict(list(latest_files.items())[:limit])


# --- PublishedPrices ------------------------------------------------------

def list_publishedprices_entries_recursive(
    client: PublishedPricesClient,
    cd: str = "/",
    depth: int = 0,
    max_depth: int = 2,
) -> list[dict]:
    """
    Recursively lists raw file entries (not filtered to any file_type),
    each tagged with its full 'path' for URL construction.
    """

    try:
        response_json = client.get_files(cd=cd)
    except Exception:
        logger.exception("Failed listing '%s' for %s", cd, client.username)
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

        path = f"{cd.strip('/')}/{fname}" if cd != "/" else fname

        entries.append({"fname": fname, "path": path})

    return entries


# --- BinaProjects ----------------------------------------------------------

def filter_ignored_bina_stores(
    files: list[dict],
    filename_key: str,
    parse_filename,
) -> list[dict]:
    """
    Drops BinaProjects files belonging to IGNORED_BINA_STORES.
    `parse_filename` is injected so this module has no hard dependency
    on the file_tracking parser.
    """

    filtered = []

    for file in files:
        filename = (file.get(filename_key) or "").strip()

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
            logger.info("IGNORING BinaProjects file: %s", filename)
            continue

        filtered.append(file)

    return filtered


# --- Carrefour ---------------------------------------------------------

def normalize_carrefour_listing(files: list) -> list[dict]:
    normalized = []

    for entry in files:

        if isinstance(entry, str):
            normalized.append({"filename": entry})
            continue

        filename = (
            entry.get("name")
            or entry.get("fileName")
            or entry.get("Name")
        )

        if filename:
            normalized.append({"filename": filename})

    return normalized


# --- Wolt ----------------------------------------------------------------

def normalize_wolt_file_urls(
    file_urls: list[str],
) -> tuple[list[dict], dict[str, str]]:
    """Returns (normalized_entries, href_by_filename)."""

    normalized = []
    href_by_filename = {}

    for url in file_urls:
        filename = urlparse(url).path.rsplit("/", 1)[-1]

        if not filename:
            continue

        normalized.append({"filename": filename})
        href_by_filename[filename] = url

    return normalized, href_by_filename


# --- Mishnat Yosef ----------------------------------------------------

def normalize_mishnatyosef_listing(
    files: list[dict],
    file_type: str,
) -> tuple[list[dict], dict[str, str]]:
    """Returns (normalized_entries, href_by_filename) filtered to file_type."""

    normalized = []
    href_by_filename = {}

    for entry in files:

        if entry.get("type") != file_type:
            continue

        filename = entry.get("name")
        url = entry.get("url")

        if not filename or not url:
            continue

        normalized.append({"filename": filename})
        href_by_filename[filename] = url

    return normalized, href_by_filename


# --- HTML pagination crawler --------------------------------------------

async def _get_html_page(
    client,
    page,
    page_param,
):
    return await client.get_candidates(
        params={
            page_param: page,
        }
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
    client,
    listing_config: dict,
) -> list:
    """
    Crawl an HTML file-link listing and return all candidates
    reported by the publisher.
    """

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

    seen_pages = {}

    max_consecutive_repeated_pages = 5
    consecutive_repeated_pages = 0

    page = 1

    while True:
        pages = list(
            range(
                page,
                page + page_batch_size,
            )
        )

        logger.debug(
            "%s: requesting pages %d-%d",
            client.name,
            pages[0],
            pages[-1],
        )

        results = await asyncio.gather(
            *(
                _get_html_page(
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
                previous_page = seen_pages[fingerprint]

                logger.debug(
                    "%s: page %d repeats page %d",
                    client.name,
                    current_page,
                    previous_page,
                )

                consecutive_repeated_pages += 1

                if (
                    consecutive_repeated_pages
                    >= max_consecutive_repeated_pages
                ):
                    logger.info(
                        "%s: stopping pagination after %d consecutive "
                        "repeated pages",
                        client.name,
                        consecutive_repeated_pages,
                    )
                    stop_after_batch = True

                continue

            consecutive_repeated_pages = 0
            seen_pages[fingerprint] = current_page

            all_candidates.extend(candidates)

            logger.debug(
                "%s: page %d -> %d candidates",
                client.name,
                current_page,
                len(candidates),
            )

        if stop_after_batch:
            break

        page += page_batch_size

    return all_candidates