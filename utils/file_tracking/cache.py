"""
Cache refresh for HTML-based file-listing sources.

This module owns everything related to fetching candidate file listings
for the HTML sources (clients.html_config.SOURCES) and persisting them to
the on-disk JSON cache under data/cache/.

It can be run standalone to just refresh the cache:

    python -m utils.file_tracking.cache

or imported by load_file_tracking.py, which calls `refresh_html_caches()`
to both refresh the cache AND get the candidates back in-memory so it can
build file_tracking records from the same run (no re-fetching).
"""

import asyncio
import json
import logging
from pathlib import Path

from logging_config import setup_general_logging

from clients.html_client import Candidate, HtmlFileLinkClient
from clients.html_config import SOURCES as HTML_SOURCES

from downloaders.common import get_all_html_candidates

setup_general_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]

CACHE_DIR = BASE_DIR / "data" / "cache"
SHUFERSAL_CACHE = CACHE_DIR / "shufersal.json"


def _html_cache_path(source_name: str) -> Path:
    return CACHE_DIR / f"{source_name}.json"


def _save_html_cache(
    source_name: str,
    candidates: list,
) -> None:
    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    cache = {
        "files": [
            {
                "text": candidate.text,
                "url": candidate.href,
                "filename": candidate.filename,
                "file_size": candidate.file_size,
            }
            for candidate in candidates
            if candidate.filename and candidate.href
        ],
    }

    cache_path = _html_cache_path(source_name)
    temp_path = cache_path.with_suffix(".tmp")

    try:
        with temp_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                cache,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temp_path.replace(cache_path)

        logger.info(
            "%s cache saved: %d file(s)",
            source_name,
            len(cache["files"]),
        )

    except Exception:
        logger.exception(
            "Failed saving %s cache",
            source_name,
        )

        if temp_path.exists():
            temp_path.unlink()


def load_html_cache(source_name: str) -> list[dict]:
    """
    Read back a previously-saved cache file for one HTML source.

    Returns an empty list if no cache exists yet or it can't be read.
    """
    cache_path = _html_cache_path(source_name)

    if not cache_path.is_file():
        return []

    try:
        with cache_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            cache = json.load(file)

        return cache.get("files", [])

    except Exception:
        logger.exception(
            "Failed reading %s cache",
            source_name,
        )
        return []


async def _fetch_and_cache_source(
    source: dict,
) -> tuple[str, list[Candidate]]:
    source_name = source["name"]
    listing = source["listing"]

    logger.info(
        "HTML source: %s",
        source_name,
    )

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

    _save_html_cache(
        source_name,
        candidates,
    )

    return source_name, candidates


async def refresh_html_caches(
    sources: list[dict] = HTML_SOURCES,
) -> dict[str, list[Candidate]]:
    """
    Fetch fresh candidate listings for every configured HTML source and
    write each one to its on-disk cache file.

    Returns {source_name: candidates} so a caller (e.g.
    load_file_tracking.get_html_files) can build records from the same
    fetch instead of hitting the sources again.
    """
    results: dict[str, list[Candidate]] = {}

    for source in sources:
        source_name = source["name"]

        try:
            name, candidates = await _fetch_and_cache_source(
                source
            )
            results[name] = candidates

        except Exception:
            logger.exception(
                "Failed refreshing HTML cache for %s",
                source_name,
            )
            results[source_name] = []

    return results


async def main():
    results = await refresh_html_caches()

    total = sum(
        len(candidates) for candidates in results.values()
    )

    logger.info(
        "Cache refresh done: %d source(s), %d candidate(s) total",
        len(results),
        total,
    )


if __name__ == "__main__":
    asyncio.run(main())