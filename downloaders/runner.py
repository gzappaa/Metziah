# downloaders/runner.py
"""
Generic download orchestration for downloader entry points. Each per-file-type
module (pricesfull.py, promosfull.py, prices.py, promos.py, stores.py)
builds its own set of per-source-type download callables.

Two ways to run them:

    run_all_sources()  -- awaitable, no argparse/sys.argv involvement.
                           Safe to `await` directly from an async context,
                           e.g. the scheduler.

    run_cli()           -- thin CLI wrapper around run_all_sources(),
                           used by each module's `if __name__ == "__main__"`.

`run` is kept as a backward-compatible alias for `run_cli`.

A download callable may return either a list[Path] (full/delta family)
or a single Path | None (stores family) -- both helpers handle both.
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


async def run_all_sources(
    kind_name: str,
    download_publishedprices,
    download_binaprojects,
    download_laibcatalog,
    download_html,
    download_carrefour,
    download_mishnatyosef,
    download_wolt,
    test: bool = False,
    clear_test_data: bool = False,
) -> list:
    """
    Runs the standard source-by-source download loop for one feed kind
    (PriceFull, PromoFull, Price, Promo, Stores, ...) and returns the
    combined list of downloaded paths.

    Awaitable and argparse-free, so this is the entry point the
    scheduler should call directly (it already owns its own CLI args).
    """

    if test and clear_test_data:
        clear_test_feeds()

    all_downloaded: list = []

    # ------------------------------------------------------------------
    # PublishedPrices
    #
    # All PublishedPrices sources run in parallel.
    #
    # Each individual source still processes its files sequentially because
    # download_publishedprices() itself uses a normal for-loop.
    #
    # PublishedPrices is synchronous/blocking, so each source runs in its
    # own worker thread via asyncio.to_thread().
    # ------------------------------------------------------------------

    pp_sources = get_publishing_sources("PublishedPricesClient")
    logger.info("Found %d PublishedPrices sources", len(pp_sources))

    async def run_publishedprices_source(source):
        credentials = source.get("credentials", {})
        username = credentials.get("username")
        password = credentials.get("password", "")

        if not username:
            logger.warning(
                "Skipping %s: no username",
                source["name"],
            )
            return []

        try:
            result = await asyncio.to_thread(
                download_publishedprices,
                source["name"],
                username,
                password,
                test=test,
            )
            return result
        except Exception:
            logger.exception(
                "Failed processing %s",
                source["name"],
            )
            return []

    pp_results = await asyncio.gather(
        *(run_publishedprices_source(source) for source in pp_sources)
    )

    for result in pp_results:
        _accumulate(all_downloaded, result)

    # ------------------------------------------------------------------
    # BinaProjects
    #
    # All BinaProjects sources run in parallel.
    #
    # Each individual source still processes its files sequentially because
    # download_binaprojects() uses a normal for-loop.
    #
    # asyncio.to_thread() is used because download_binaprojects() and
    # its HTTP client are synchronous/blocking functions.
    # ------------------------------------------------------------------

    bina_sources = get_publishing_sources("BinaProjectsClient")
    logger.info("Found %d BinaProjects sources", len(bina_sources))

    async def run_bina_source(source):
        try:
            result = await asyncio.to_thread(
                download_binaprojects,
                source["name"],
                source["url"],
                test=test,
            )
            return result
        except Exception:
            logger.exception(
                "Failed processing %s",
                source["name"],
            )
            return []

    bina_results = await asyncio.gather(
        *(run_bina_source(source) for source in bina_sources)
    )

    for result in bina_results:
        _accumulate(all_downloaded, result)

    # ------------------------------------------------------------------
    # Laibcatalog
    #
    # All Laibcatalog sources run in parallel.
    #
    # download_laibcatalog() is already async, so no worker threads are
    # necessary.
    #
    # Each individual source still processes its files sequentially because
    # download_pricefull_laibcatalog() uses a normal for-loop and awaits
    # each save/download before continuing to the next file.
    # ------------------------------------------------------------------

    laib_sources = get_publishing_sources("LaibcatalogClient")
    logger.info("Found %d Laibcatalog sources", len(laib_sources))

    async def run_laibcatalog_source(source):
        if not source.get("chain_id"):
            logger.warning(
                "Skipping %s: no chain_id in registry",
                source["name"],
            )
            return []

        try:
            result = await download_laibcatalog(
                source["name"],
                source["url"],
                source["chain_id"],
                test=test,
            )
            return result
        except Exception:
            logger.exception(
                "Failed processing %s",
                source["name"],
            )
            return []

    laib_results = await asyncio.gather(
        *(run_laibcatalog_source(source) for source in laib_sources)
    )

    for result in laib_results:
        _accumulate(all_downloaded, result)

    # ------------------------------------------------------------------
    # HTML sources
    # ------------------------------------------------------------------

    logger.info("Found %d HTML-based sources", len(HTML_SOURCES))

    for source in HTML_SOURCES:

        try:
            result = await download_html(source, test=test)
            _accumulate(all_downloaded, result)
        except Exception:
            logger.exception(
                "Failed processing %s",
                source["name"],
            )

    # ------------------------------------------------------------------
    # Carrefour
    # ------------------------------------------------------------------

    try:
        result = await download_carrefour(test=test)
        _accumulate(all_downloaded, result)
    except Exception:
        logger.exception("Failed processing Carrefour")

    # ------------------------------------------------------------------
    # Mishnat Yosef
    # ------------------------------------------------------------------

    try:
        result = await download_mishnatyosef(test=test)
        _accumulate(all_downloaded, result)
    except Exception:
        logger.exception("Failed processing Mishnat Yosef")

    # ------------------------------------------------------------------
    # Wolt
    # ------------------------------------------------------------------

    try:
        result = await download_wolt(test=test)
        _accumulate(all_downloaded, result)
    except Exception:
        logger.exception("Failed processing Wolt")

    logger.info(
        "Finished. Downloaded %d %s file(s) total.",
        len(all_downloaded),
        kind_name,
    )

    return all_downloaded


def run_cli(
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
    CLI wrapper: parses --test from sys.argv, then runs run_all_sources().

    Used by each downloader module's `if __name__ == "__main__"` block
    (`python -m downloaders.prices --test`). Not used by the scheduler.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test",
        action="store_true",
        help=test_help,
    )
    args = parser.parse_args()

    return asyncio.run(
        run_all_sources(
            kind_name,
            download_publishedprices,
            download_binaprojects,
            download_laibcatalog,
            download_html,
            download_carrefour,
            download_mishnatyosef,
            download_wolt,
            test=args.test,
            clear_test_data=clear_test_data,
        )
    )


# Backward-compatible alias -- stores.py (and anything else) can keep
# importing `run` unchanged.
run = run_cli