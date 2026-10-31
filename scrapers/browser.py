"""
scrapers/browser.py

Browser-based scraper for retailers protected by Cloudflare.

Modes:
    python -m scrapers.browser
        Phase 1: discover and save categories for all retailers marked
        available=false in scraper_coverage.json.
        Phase 2: scrape them with up to 8 retailers running concurrently.
        Each retailer processes its categories one at a time.

    python -m scrapers.browser --categories
        Discover and save categories only.

    python -m scrapers.browser --concurrency 4
        Change the number of concurrent retailers (default 8).

    python -m scrapers.browser --retailer chain --category 79698
        Scrape one category for manual testing.

Product requests and pagination use the browser's own session.
Inactive or empty categories are skipped, and individual category
failures do not stop the rest of a retailer's scrape.
"""

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from scrapers.generic import extract_js_object, get_all_categories


ROOT = Path(__file__).resolve().parent.parent
COVERAGE_FILE = ROOT / "monitoring" / "data" / "scraper_coverage.json"
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_CONCURRENCY = 8
MAX_CONSECUTIVE_FAILURES = 3  # recreate a retailer's context after this many

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_retailers():
    """Load retailer configuration keyed by chain ID."""
    with COVERAGE_FILE.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Expected a dictionary in scraper_coverage.json")

    retailers = []
    for chain_id, retailer in data.items():
        if not isinstance(retailer, dict):
            continue

        retailer = retailer.copy()
        retailer.setdefault("chain_id", chain_id)
        retailers.append(retailer)

    return retailers


def retailer_name(retailer):
    """Return the normalized retailer name used for output directories."""
    return (
        retailer.get("name_en_normalized")
        or retailer.get("name_en")
        or retailer.get("name")
        or retailer.get("retailer_id")
    )


def extract_frontend_data(text):
    """Extract frontendData from JavaScript using generic.py's parser."""
    extracted = extract_js_object(text, "frontendData")

    try:
        return json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise ValueError(f"frontendData is not valid JSON: {exc}") from exc


def get_categories(frontend_data):
    """Return the recursively flattened category list."""
    try:
        categories = frontend_data["tree"]["categories"]
    except (KeyError, TypeError) as exc:
        raise ValueError("frontendData does not contain tree.categories") from exc

    if not isinstance(categories, list):
        raise ValueError("frontendData tree.categories is not a list")

    return get_all_categories(categories)


async def load_frontend_data(browser, retailer):
    """Open the website, then load its configured frontend data asset."""
    website_url = retailer.get("web_site")
    data_url = retailer.get("data_url")

    if not website_url or not data_url:
        raise ValueError("Retailer must have web_site and data_url")

    context = await browser.new_context(
        viewport={"width": 1440, "height": 1000},
        locale="he-IL",
    )

    try:
        page = await context.new_page()

        logger.info("[%s] opening website: %s", retailer_name(retailer), website_url)
        try:
            await page.goto(
                website_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
        except PlaywrightTimeoutError:
            logger.warning(
                "[%s] website navigation timed out; continuing",
                retailer_name(retailer),
            )

        await page.wait_for_timeout(1500)

        try:
            frontend_data = await page.evaluate(
                """() => {
                    if (typeof frontendData !== "undefined") {
                        return frontendData;
                    }
                    return window.frontendData || null;
                }"""
            )
        except Exception:
            frontend_data = None

        if isinstance(frontend_data, dict):
            try:
                get_categories(frontend_data)
                return frontend_data
            except ValueError:
                pass

        logger.info(
            "[%s] loading frontend data: %s",
            retailer_name(retailer),
            data_url,
        )
        try:
            response = await page.goto(
                data_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                f"Timed out loading frontend data: {data_url}"
            ) from exc

        if response is None:
            raise RuntimeError(f"No browser response received for {data_url}")

        if response.status >= 400:
            raise RuntimeError(
                f"Frontend data returned HTTP {response.status}: {data_url}"
            )

        return extract_frontend_data(await response.text())

    finally:
        await context.close()


def save_categories(retailer, categories):
    """Save categories to data/raw/<retailer>/categories.json."""
    name = retailer_name(retailer)
    if not name:
        raise ValueError("Retailer has no usable name")

    output_dir = RAW_DIR / str(name)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "categories.json"

    payload = {
        "retailer": name,
        "retailer_id": retailer.get("retailer_id"),
        "categories_count": len(categories),
        "categories": categories,
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def load_saved_categories(retailer):
    """Read categories from the retailer's existing categories.json."""
    name = retailer_name(retailer)
    path = RAW_DIR / str(name) / "categories.json"

    if not path.exists():
        raise FileNotFoundError(
            f"{path.relative_to(ROOT)} does not exist; run category discovery first"
        )

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    categories = data.get("categories", []) if isinstance(data, dict) else data
    if not isinstance(categories, list):
        raise ValueError(f"Invalid categories format in {path}")

    return categories


class NoProductResponse(Exception):
    """The category page never produced a product API response (likely blocked)."""


async def new_retailer_context(browser):
    """Create one isolated, long-lived session for a retailer."""
    return await browser.new_context(
        viewport={"width": 1440, "height": 1000},
        locale="he-IL",
    )


async def scrape_category(context, retailer, category_id):
    """
    Capture all products from a category using browser-side pagination.

    Uses the retailer's shared context (cookies persist across categories)
    and opens a fresh page for this category only.
    """
    name = retailer_name(retailer)
    website_url = retailer.get("web_site")

    if not website_url:
        raise ValueError("Retailer is missing web_site")

    category_id = str(category_id)
    url = urljoin(
        website_url.rstrip("/") + "/",
        f"categories/{category_id}/products",
    )

    output_dir = RAW_DIR / str(name)
    output_file = output_dir / f"{category_id}.json"

    page = await context.new_page()
    try:
        responses = []
        page.on("response", lambda response: responses.append(response))

        logger.info("[%s] category=%s opening %s", name, category_id, url)

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
        except PlaywrightTimeoutError:
            logger.warning(
                "[%s] category=%s navigation timed out",
                name,
                category_id,
            )

        try:
            await page.wait_for_load_state("networkidle", timeout=8_000)
        except PlaywrightTimeoutError:
            pass

        logger.info(
            "[%s] category=%s final_page=%s title=%s",
            name,
            category_id,
            page.url,
            await page.title(),
        )

        # Find the actual product API response initiated by the page.
        api_response = None
        data = None

        for response in reversed(responses):
            if (
                response.status == 200
                and f"/categories/{category_id}/products" in response.url
                and "json" in response.headers.get("content-type", "").lower()
            ):
                try:
                    candidate = await response.json()
                except Exception:
                    continue

                if (
                    isinstance(candidate, dict)
                    and isinstance(candidate.get("products"), list)
                    and "total" in candidate
                ):
                    api_response = response
                    data = candidate
                    break

        if api_response is None:
            raise NoProductResponse(
                f"no product JSON response captured for category {category_id}"
            )

        products = data["products"]
        total = int(data.get("total") or 0)

        if not products or not total:
            logger.info(
                "[%s] category=%s inactive/empty; skipping",
                name,
                category_id,
            )
            return False

        api_url = api_response.url
        logger.info(
            "[%s] category=%s API total=%s initial_batch=%s",
            name,
            category_id,
            total,
            len(products),
        )

        # Fetch subsequent batches through the browser's own session.
        batch_size = max(len(products), 1)
        all_products = list(products)
        next_from = len(products)

        while next_from < total:
            result = await page.evaluate(
                """async ({ apiUrl, offset, size }) => {
                    const url = new URL(apiUrl);
                    url.searchParams.set("from", String(offset));
                    url.searchParams.set("size", String(size));

                    const response = await fetch(url.toString(), {
                        credentials: "include"
                    });

                    if (!response.ok) {
                        throw new Error(
                            `Product API returned HTTP ${response.status} at from=${offset}`
                        );
                    }

                    return await response.json();
                }""",
                {
                    "apiUrl": api_url,
                    "offset": next_from,
                    "size": batch_size,
                },
            )

            batch = result.get("products", [])
            if not batch:
                logger.warning(
                    "[%s] category=%s pagination stopped at %s/%s: empty batch",
                    name,
                    category_id,
                    len(all_products),
                    total,
                )
                break

            all_products.extend(batch)
            next_from += len(batch)

            logger.info(
                "[%s] category=%s collected %s/%s products",
                name,
                category_id,
                len(all_products),
                total,
            )

        data["products"] = all_products
        data["total"] = total
        data["_metziah"] = {
            "chain_id": retailer["chain_id"],
            "retailer_id": retailer.get("retailer_id"),
            "category_id": category_id,
            "source_url": api_url,
        }

        output_dir.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        complete = len(all_products) == total
        logger.info(
            "[%s] category=%s %s %s/%s products -> %s",
            name,
            category_id,
            "saved" if complete else "partially saved",
            len(all_products),
            total,
            output_file.relative_to(ROOT),
        )
        return complete

    finally:
        await page.close()


async def discover_retailer(browser, retailer):
    """Phase 1: discover and save one retailer's categories."""
    name = retailer_name(retailer) or "unknown"

    frontend_data = await load_frontend_data(browser, retailer)
    categories = get_categories(frontend_data)

    if not categories:
        raise ValueError("No categories found in frontendData")

    output_path = save_categories(retailer, categories)
    logger.info(
        "[%s] saved %s categories to %s",
        name,
        len(categories),
        output_path.relative_to(ROOT),
    )
    return categories


async def scrape_retailer_categories(browser, retailer, categories):
    """
    Phase 2: scrape one retailer's categories, one at a time, inside a
    single persistent browser context (one session per retailer).

    If several categories in a row fail, the context is replaced with a
    fresh one in case the session was flagged or went stale.
    """
    name = retailer_name(retailer) or "unknown"
    total_categories = len(categories)
    completed = 0
    skipped_or_failed = 0
    consecutive_failures = 0
    started = time.monotonic()

    context = await new_retailer_context(browser)

    try:
        for index, category in enumerate(categories, start=1):
            if not isinstance(category, dict) or category.get("id") is None:
                logger.warning(
                    "[%s] category %s/%s has no ID; skipping",
                    name,
                    index,
                    total_categories,
                )
                skipped_or_failed += 1
                continue

            category_id = str(category["id"])
            category_label = (
                category.get("name")
                or category.get("name_en")
                or category.get("label")
                or category_id
            )

            logger.info(
                "[%s] category %s/%s: %s (%s)",
                name,
                index,
                total_categories,
                category_label,
                category_id,
            )

            failed = False
            try:
                success = await scrape_category(context, retailer, category_id)
                if success:
                    completed += 1
                else:
                    skipped_or_failed += 1  # empty or partial, not a session problem
            except NoProductResponse as exc:
                failed = True
                skipped_or_failed += 1
                logger.warning("[%s] category=%s %s", name, category_id, exc)
            except Exception:
                failed = True
                skipped_or_failed += 1
                logger.exception(
                    "[%s] category=%s failed; continuing to next category",
                    name,
                    category_id,
                )

            if failed:
                consecutive_failures += 1
            else:
                consecutive_failures = 0

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "[%s] %s consecutive failures; starting a fresh browser session",
                    name,
                    consecutive_failures,
                )
                await context.close()
                context = await new_retailer_context(browser)
                consecutive_failures = 0
    finally:
        await context.close()

    elapsed = time.monotonic() - started
    logger.info(
        "[%s] finished in %.1f min: %s/%s categories complete, %s skipped or failed",
        name,
        elapsed / 60,
        completed,
        total_categories,
        skipped_or_failed,
    )
    return completed, skipped_or_failed, elapsed


async def scrape_single_category(browser, retailer, category_id):
    """Manual single-category testing mode."""
    name = retailer_name(retailer) or "unknown"
    categories = load_saved_categories(retailer)
    matching = [
        category
        for category in categories
        if isinstance(category, dict)
        and str(category.get("id")) == str(category_id)
    ]

    if not matching:
        raise ValueError(
            f"Category {category_id} not found in "
            f"data/raw/{name}/categories.json"
        )

    context = await new_retailer_context(browser)
    try:
        return await scrape_category(context, retailer, category_id)
    finally:
        await context.close()


async def worker(worker_id, browser, queue, results):
    """
    Pull retailers from the queue until it is empty.

    When a worker finishes a retailer, it immediately takes the next one,
    so the number of active retailers stays at the concurrency limit until
    the queue runs dry.
    """
    while True:
        try:
            retailer, categories = queue.get_nowait()
        except asyncio.QueueEmpty:
            logger.info("Worker %s: queue empty, exiting", worker_id)
            return

        name = retailer_name(retailer) or "unknown"
        logger.info(
            "Worker %s: starting %s (%s categories)",
            worker_id,
            name,
            len(categories),
        )

        try:
            completed, skipped, elapsed = await scrape_retailer_categories(
                browser, retailer, categories
            )
            results[name] = {
                "status": "done",
                "completed": completed,
                "skipped_or_failed": skipped,
                "elapsed_min": round(elapsed / 60, 1),
            }
        except Exception as exc:
            logger.exception("[%s] retailer task failed", name)
            results[name] = {"status": "failed", "error": str(exc)}
        finally:
            queue.task_done()


async def main():
    parser = argparse.ArgumentParser(
        description=(
            "Discover categories and scrape retailer products with Playwright."
        )
    )
    parser.add_argument(
        "--retailer",
        help="Retailer name or ID, e.g. walmart.",
    )
    parser.add_argument(
        "--category",
        help="Scrape only this category ID from the existing categories.json.",
    )
    parser.add_argument(
        "--categories",
        action="store_true",
        help="Discover and save categories only; do not scrape products.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max retailers scraped at once (default {DEFAULT_CONCURRENCY}).",
    )
    args = parser.parse_args()

    if args.category and args.categories:
        parser.error("--category cannot be combined with --categories")
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")

    retailers = load_retailers()

    if args.retailer:
        target = args.retailer.strip().casefold()
        retailers = [
            retailer
            for retailer in retailers
            if target in {
                str(value).casefold()
                for value in (
                    retailer_name(retailer),
                    retailer.get("name_en"),
                    retailer.get("name"),
                    retailer.get("retailer_id"),
                    retailer.get("chain_id"),
                )
                if value is not None
            }
        ]
    else:
        # Only browser-based retailers are selected by default.
        retailers = [
            retailer
            for retailer in retailers
            if retailer.get("available") is False
        ]

    if not retailers:
        logger.error("No matching retailers found")
        return

    if args.category and len(retailers) != 1:
        logger.error("Specify --retailer when using --category")
        return

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)

        try:
            # Manual single-category mode.
            if args.category:
                try:
                    await scrape_single_category(
                        browser, retailers[0], args.category
                    )
                except Exception:
                    logger.exception(
                        "[%s] single-category run failed",
                        retailer_name(retailers[0]),
                    )
                return

            # ---- Phase 1: discover categories for every retailer ----
            logger.info("Phase 1: discovering categories for %s retailer(s)", len(retailers))
            discovered = []
            discovery_failed = []

            for index, retailer in enumerate(retailers, start=1):
                name = retailer_name(retailer) or "unknown"
                logger.info("Discovery %s/%s: %s", index, len(retailers), name)

                try:
                    categories = await discover_retailer(browser, retailer)
                    discovered.append((retailer, categories))
                except Exception:
                    discovery_failed.append(name)
                    logger.exception("[%s] category discovery failed", name)

            logger.info(
                "Discovery finished: %s succeeded, %s failed",
                len(discovered),
                len(discovery_failed),
            )

            if args.categories:
                if discovery_failed:
                    logger.warning("Discovery failed for: %s", ", ".join(discovery_failed))
                return

            if not discovered:
                logger.error("No retailers with discovered categories; nothing to scrape")
                return

            # ---- Phase 2: scrape with a bounded pool of retailer workers ----
            worker_count = min(args.concurrency, len(discovered))
            logger.info(
                "Phase 2: scraping %s retailer(s) with %s concurrent worker(s)",
                len(discovered),
                worker_count,
            )

            queue = asyncio.Queue()
            for item in discovered:
                queue.put_nowait(item)

            results = {}
            await asyncio.gather(
                *(
                    worker(worker_id, browser, queue, results)
                    for worker_id in range(1, worker_count + 1)
                )
            )

            # ---- Summary ----
            done = [n for n, r in results.items() if r["status"] == "done"]
            failed = [n for n, r in results.items() if r["status"] == "failed"]

            logger.info(
                "Finished: %s/%s retailer(s) completed, %s failed during scrape, "
                "%s failed discovery",
                len(done),
                len(discovered),
                len(failed),
                len(discovery_failed),
            )
            for n in sorted(done, key=lambda k: results[k]["elapsed_min"], reverse=True):
                r = results[n]
                logger.info(
                    "  %-20s %6.1f min  %s ok, %s skipped/failed",
                    n,
                    r["elapsed_min"],
                    r["completed"],
                    r["skipped_or_failed"],
                )
            if failed:
                logger.warning("Scrape failed for: %s", ", ".join(failed))
            if discovery_failed:
                logger.warning("Discovery failed for: %s", ", ".join(discovery_failed))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())