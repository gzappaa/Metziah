# downloaders/runner.py
"""
Generic CLI orchestration for downloader entry points. Each per-file-type
module (pricesfull.py, promosfull.py, prices.py, promos.py, stores.py)
builds its own set of per-source-type download callables and hands them
to `run`, which drives the standard 7-source loop:

    PublishedPrices -> BinaProjects -> Laibcatalog -> HTML sources
    -> Carrefour -> Mishnat Yosef -> Wolt

A download callable may return either a list[Path] (full/delta family)
or a single Path | None (stores family) — `run` handles both.
"""

import argparse
import asyncio
import logging
from downloaders.common import clear_test_feeds
from clients.html_config import SOURCES as HTML_SOURCES
from database.repository import get_publishing_sources

logger = logging.getLogger(__name__)


def _accumulate(all_downloaded: list, result) -> None:
    if isinstance(result, list):
        all_downloaded.extend(result)
    elif result is not None:
        all_downloaded.append(result)


def run(
    kind_name: str,
    download_publishedprices,
    download_binaprojects,
    download_laibcatalog,
    download_html,
    download_carrefour,
    download_mishnatyosef,
    download_wolt,
    test_help: str = "Use test_feeds directory and cap each source at 5 stores",
    clear_test_data: bool = False,
) -> list:
    """
    Runs the standard source-by-source download loop for one feed kind
    (PriceFull, PromoFull, Price, Promo, Stores, ...) and returns the
    combined list of downloaded paths.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help=test_help)
    args = parser.parse_args()

    if args.test and clear_test_data:
       clear_test_feeds()

    all_downloaded: list = []

    pp_sources = get_publishing_sources("PublishedPricesClient")
    logger.info("Found %d PublishedPrices sources", len(pp_sources))

    for source in pp_sources:

        credentials = source.get("credentials", {})
        username = credentials.get("username")
        password = credentials.get("password", "")

        if not username:
            logger.warning("Skipping %s: no username", source["name"])
            continue

        try:
            result = download_publishedprices(
                source["name"], username, password, test=args.test,
            )
            _accumulate(all_downloaded, result)
        except Exception:
            logger.exception("Failed processing %s", source["name"])

    bina_sources = get_publishing_sources("BinaProjectsClient")
    logger.info("Found %d BinaProjects sources", len(bina_sources))

    for source in bina_sources:

        try:
            result = download_binaprojects(
                source["name"], source["url"], test=args.test,
            )
            _accumulate(all_downloaded, result)
        except Exception:
            logger.exception("Failed processing %s", source["name"])

    laib_sources = get_publishing_sources("LaibcatalogClient")
    logger.info("Found %d Laibcatalog sources", len(laib_sources))

    for source in laib_sources:

        if not source.get("chain_id"):
            logger.warning(
                "Skipping %s: no chain_id in registry", source["name"],
            )
            continue

        try:
            result = asyncio.run(
                download_laibcatalog(
                    source["name"],
                    source["url"],
                    source["chain_id"],
                    test=args.test,
                )
            )
            _accumulate(all_downloaded, result)
        except Exception:
            logger.exception("Failed processing %s", source["name"])

    logger.info("Found %d HTML-based sources", len(HTML_SOURCES))

    for source in HTML_SOURCES:

        try:
            result = asyncio.run(download_html(source, test=args.test))
            _accumulate(all_downloaded, result)
        except Exception:
            logger.exception("Failed processing %s", source["name"])

    try:
        result = asyncio.run(download_carrefour(test=args.test))
        _accumulate(all_downloaded, result)
    except Exception:
        logger.exception("Failed processing Carrefour")

    try:
        result = asyncio.run(download_mishnatyosef(test=args.test))
        _accumulate(all_downloaded, result)
    except Exception:
        logger.exception("Failed processing Mishnat Yosef")

    try:
        result = asyncio.run(download_wolt(test=args.test))
        _accumulate(all_downloaded, result)
    except Exception:
        logger.exception("Failed processing Wolt")

    logger.info(
        "Finished. Downloaded %d %s file(s) total.",
        len(all_downloaded),
        kind_name,
    )

    return all_downloaded