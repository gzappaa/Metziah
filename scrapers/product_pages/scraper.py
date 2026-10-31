"""
scrapers/product_pages/scraper.py

Scrape product pages (image + full product content) from supermarket
websites for item codes we already have in the database.

Setup:
    Add one example product URL per supermarket to
    scrapers/product_urls.txt (one per line, '#' lines are comments).
    The URL must contain exactly one real barcode that exists on that site.

How it works:
    - The barcode in each URL is swapped for every item code.
    - The site name comes from the domain and must match chains.name_en_normalized.
    - Each site's page is opened once to detect its page type.
    - Add new page structures as scrapers/product_pages/type_*.py modules:
        * page types define MARKER (a selector) and parse(html);
        * API types define matches(payload, item_code) and
          parse(payload, item_code, base_url). They are detected from the
          network traffic of the example page (the only time a browser is
          needed for them), then the captured request is replayed per item
          code with plain HTTP. No browser is used while scraping.

Modes:
    python -m scrapers.product_pages.scraper --item 7290110115227
        Fetch one item from every site and print the JSON. Nothing saved.

    python -m scrapers.product_pages.scraper --item 7290110115227 --save
        Fetch one item from every site, print the JSON, and save found items.
        No DB required.

    python -m scrapers.product_pages.scraper --limit 20
        Fetch the first 20 unsaved item codes per site.

    python -m scrapers.product_pages.scraper
        Fetch all unsaved item codes, 300 items per chunk per site.

Output: data/raw_product_pages/<retail>/<item_code>.json
Re-running skips items that already have a file.
Items the site does not have are appended to _missing.txt.
Failures save nothing, so the next run retries them automatically.
"""

import argparse
import asyncio
import importlib
import json
import logging
import pkgutil
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import get_close_matches
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


ROOT = Path(__file__).resolve().parent.parent.parent
URLS_FILE = Path(__file__).resolve().parent / "product_urls.txt"
TYPES_PACKAGE = "scrapers.product_pages"
OUT_DIR = ROOT / "data" / "raw_product_pages"

DEFAULT_CONCURRENCY = 5
PRODUCT_WAIT_MS = 12_000
CHUNK_SIZE = 10
MAX_CONSECUTIVE_DRIVER_FAILURES = 3

BARCODE_IN_URL = re.compile(r"\d{8,14}")

API_RESOURCE_TYPES = {"xhr", "fetch"}
API_TIMEOUT_S = 30
API_DELAY_S = 2.5          # initial seconds between request starts, per site
API_MIN_DELAY_S = 0.5      # adaptive throttle will not go below this
API_MAX_DELAY_S = 10.0     # adaptive throttle will not go above this
API_SUCCESS_WINDOW = 500    # successful responses before cautiously speeding up
API_DELAY_STEP_S = 0.1    # decrease per successful window
API_MAX_ATTEMPTS = 5
API_BACKOFF_S = 5          # first wait after a rate limit; doubles each retry
API_MAX_BACKOFF_S = 300
API_RETRY_STATUSES = {429, 502, 503, 504}

# Headers the HTTP layer manages itself; replaying them breaks the request.
SKIPPED_HEADERS = {
    "cookie",
    "content-length",
    "host",
    "connection",
    "accept-encoding",
}

# These are matched case-insensitively against exception messages.
# Keep this list specific to avoid treating ordinary page errors as
# proof that the entire Playwright driver has died.
DRIVER_DEAD = (
    "connection closed while reading from the driver",
    "pipe closed by peer",
)

SQL_ITEM_CODES = """
    SELECT p.item_code
    FROM products p
    WHERE EXISTS (
        SELECT 1
        FROM prices pr
        WHERE pr.item_code = p.item_code
          AND pr.chain_id IN (
              SELECT chain_id
              FROM chains
              WHERE name_en_normalized = %s
          )
    )
    ORDER BY p.item_code
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def is_driver_dead(exc):
    """Return True when an exception indicates a disconnected Playwright driver."""
    message = str(exc).casefold()
    return any(marker in message for marker in DRIVER_DEAD)


# ============================================================
# Page types
# ============================================================

@dataclass(frozen=True)
class PageType:
    name: str
    marker: Optional[str]
    matches: Optional[Callable]
    prepare: Optional[Callable]
    parse: Callable


@dataclass(frozen=True)
class ApiRequest:
    """A captured request, with the item code replaced by {item_code}."""
    method: str
    url: str
    body: Optional[str]
    headers: dict

    def render(self, item_code):
        code = str(item_code)

        def fill(text):
            return text.replace("{item_code}", code)

        return {
            "url": fill(self.url),
            "method": self.method,
            "data": fill(self.body) if self.body is not None else None,
            "headers": {k: fill(v) for k, v in self.headers.items()},
        }


def discover_types():
    """Import every scrapers/product_pages/type_*.py module."""
    package = importlib.import_module(TYPES_PACKAGE)
    types = []

    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        if not info.name.startswith("type_"):
            continue

        module = importlib.import_module(f"{TYPES_PACKAGE}.{info.name}")
        marker = getattr(module, "MARKER", None)
        matches = getattr(module, "matches", None)
        parse = getattr(module, "parse", None)

        if not callable(parse) or not (marker or callable(matches)):
            raise ValueError(
                f"{info.name} must define parse() and either MARKER "
                f"or matches()"
            )

        types.append(
            PageType(
                info.name,
                marker,
                matches if callable(matches) else None,
                getattr(module, "prepare", None),
                parse,
            )
        )

    if not types:
        raise ValueError(f"No page types found in {TYPES_PACKAGE}")

    return types


# ============================================================
# Sites
# ============================================================

class Throttle:
    """Adaptive per-site request pacing with a shared cooldown for all workers."""

    def __init__(self, interval):
        self.interval = max(API_MIN_DELAY_S, min(interval, API_MAX_DELAY_S))
        self._next = 0.0
        self._cooldown_until = 0.0
        self._generation = 0
        self._successes = 0
        self._lock = asyncio.Lock()

    async def wait(self):
        # Reserve a request slot, then verify that no cooldown was introduced
        # while this worker was sleeping for its turn.
        while True:
            async with self._lock:
                now = time.monotonic()
                if now < self._cooldown_until:
                    delay = self._cooldown_until - now
                    generation = None
                else:
                    slot = max(now, self._next)
                    self._next = slot + self.interval
                    delay = slot - now
                    generation = self._generation

            if delay > 0:
                await asyncio.sleep(delay)

            if generation is None:
                continue

            async with self._lock:
                now = time.monotonic()
                if generation != self._generation or now < self._cooldown_until:
                    continue
                return

    async def success(self):
        """Gradually increase request rate after a sustained run of successes."""
        async with self._lock:
            self._successes += 1
            if self._successes < API_SUCCESS_WINDOW:
                return

            self._successes = 0
            old_interval = self.interval
            self.interval = max(API_MIN_DELAY_S, self.interval - API_DELAY_STEP_S)
            if self.interval < old_interval:
                logger.info(
                    "Adaptive throttle: delay %.2fs -> %.2fs after %s successful responses",
                    old_interval,
                    self.interval,
                    API_SUCCESS_WINDOW,
                )

    async def cooldown(self, seconds):
        """Pause every worker and reduce request rate after a retryable response."""
        async with self._lock:
            now = time.monotonic()
            old_interval = self.interval
            self.interval = min(API_MAX_DELAY_S, max(self.interval * 2, self.interval + 0.5))
            self._successes = 0
            until = now + seconds
            if until > self._cooldown_until:
                self._cooldown_until = until
                self._generation += 1
            self._next = max(self._next, self._cooldown_until)
            if self.interval > old_interval:
                logger.warning(
                    "Adaptive throttle: delay %.2fs -> %.2fs after rate limiting",
                    old_interval,
                    self.interval,
                )




@dataclass(frozen=True)
class Site:
    name: str
    url_template: str
    page_type: PageType
    api: Optional[ApiRequest] = None
    throttle: Throttle = field(default_factory=lambda: Throttle(API_DELAY_S))


def site_name(url):
    """Match a retailer hostname to its closest normalized database chain name."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    hostname = host.split(".")[0].replace("-", " ")

    from db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name_en_normalized FROM chains")
        chain_names = [row[0] for row in cur.fetchall() if row[0]]

    matches = get_close_matches(hostname, chain_names, n=1, cutoff=0.65)
    return matches[0] if matches else hostname


def read_site_entries():
    """Return (name, example_url, url_template, example_code) entries."""
    entries = []

    for line in URLS_FILE.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if not url or url.startswith("#"):
            continue

        codes = set(BARCODE_IN_URL.findall(url))
        if len(codes) != 1:
            raise ValueError(f"Expected exactly one barcode in URL: {url}")

        code = codes.pop()
        template = url.replace(code, "{item_code}")
        entries.append((site_name(url), url, template, code))

    return entries


def request_body(request):
    """Request body as text, or None if there is none or it is binary."""
    try:
        return request.post_data
    except UnicodeDecodeError:
        return None


def build_api_request(request, item_code):
    """Turn a captured request into a template by swapping out the item code."""
    code = str(item_code)

    def swap(text):
        return text.replace(code, "{item_code}")

    body = request_body(request)

    return ApiRequest(
        method=request.method,
        url=swap(request.url),
        body=swap(body) if body is not None else None,
        headers={
            key: swap(value)
            for key, value in request.headers.items()
            if key.lower() not in SKIPPED_HEADERS and not key.startswith(":")
        },
    )


async def match_api(response, item_code, api_types):
    """Return (page_type, ApiRequest) if this response is a product payload."""
    request = response.request

    if request.resource_type not in API_RESOURCE_TYPES:
        return None

    # The request must carry the code, or it cannot be replayed per item.
    code = str(item_code)
    if code not in request.url and code not in (request_body(request) or ""):
        return None

    try:
        payload = await response.json()
    except Exception:
        return None

    for page_type in api_types:
        if page_type.matches(payload, code):
            return page_type, build_api_request(request, code)

    return None


async def detect_type(context, name, example_url, example_code, types):
    """
    Open the example page once and find which type fits it.

    Returns (page_type, api_request). api_request is None for page types,
    and the replayable request template for API types.
    """
    api_types = [t for t in types if t.matches]
    page_types = [t for t in types if t.marker]
    combined = ", ".join(t.marker for t in page_types)

    captured = []
    page = await context.new_page()
    page.on("response", lambda response: captured.append(response))

    try:
        await page.goto(
            example_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + (PRODUCT_WAIT_MS * 2) / 1000
        seen = 0

        while True:
            while seen < len(captured):
                response = captured[seen]
                seen += 1

                found = await match_api(response, example_code, api_types)
                if found:
                    page_type, api = found
                    logger.info(
                        "[%s] detected page type: %s (api)",
                        name,
                        page_type.name,
                    )
                    return page_type, api

            if combined:
                for page_type in page_types:
                    if await page.locator(page_type.marker).count():
                        logger.info(
                            "[%s] detected page type: %s",
                            name,
                            page_type.name,
                        )
                        return page_type, None

            if loop.time() >= deadline:
                break

            await page.wait_for_timeout(500)
    finally:
        await page.close()

    raise ValueError(
        f"[{name}] no known page type matched {example_url}. "
        f"Check the URL has a real product, or add a type file "
        f"in {TYPES_PACKAGE.replace('.', '/')}/"
    )


# ============================================================
# Database
# ============================================================

def load_item_codes(site_name_):
    # Imported here so --item works without a DB connection.
    from db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(SQL_ITEM_CODES, (site_name_,))
        return [row[0] for row in cur.fetchall()]


# ============================================================
# Scraping
# ============================================================

async def block_heavy(route):
    if route.request.resource_type in {"image", "media", "font"}:
        await route.abort()
    else:
        await route.continue_()


async def new_context(browser):
    context = await browser.new_context(
        viewport={"width": 1440, "height": 1000},
        locale="he-IL",
    )
    await context.route("**/*", block_heavy)
    return context


async def fetch_html(page, site, url):
    """Open a product page; return HTML, or None if there is no product."""
    response = await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60_000,
    )

    if response is not None and response.status == 404:
        return None

    try:
        await page.wait_for_selector(
            site.page_type.marker,
            timeout=PRODUCT_WAIT_MS,
        )
    except PlaywrightTimeoutError:
        return None

    if site.page_type.prepare:
        await site.page_type.prepare(page)

    return await page.content()


def request_api(site, item_code):
    """Replay the captured request with plain HTTP; returns the response."""
    spec = site.api.render(item_code)

    return requests.request(
        spec["method"],
        spec["url"],
        headers=spec["headers"],
        data=spec["data"].encode("utf-8") if spec["data"] is not None else None,
        timeout=API_TIMEOUT_S,
    )


def retry_after_seconds(response):
    """Seconds from a Retry-After header, or None."""
    value = response.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else None


async def fetch_api(site, item_code):
    """JSON payload, or None if the site has no such item. Backs off on rate limits."""
    for attempt in range(1, API_MAX_ATTEMPTS + 1):
        await site.throttle.wait()
        response = await asyncio.to_thread(request_api, site, item_code)

        if response.status_code == 404:
            await site.throttle.success()
            return None

        if response.status_code in API_RETRY_STATUSES:
            wait = retry_after_seconds(response) or min(
                API_BACKOFF_S * 2 ** (attempt - 1),
                API_MAX_BACKOFF_S,
            )
            await site.throttle.cooldown(wait)
            logger.warning(
                "[%s] HTTP %s on %s, pausing %ss (attempt %s/%s)",
                site.name,
                response.status_code,
                item_code,
                wait,
                attempt,
                API_MAX_ATTEMPTS,
            )
            continue

        response.raise_for_status()
        await site.throttle.success()
        return response.json()

    raise RuntimeError(f"still rate limited after {API_MAX_ATTEMPTS} attempts")


async def scrape_item(context, site, item_code):
    """Return the result dict, or None if the site has no such product."""
    url = site.url_template.replace("{item_code}", str(item_code))

    if site.api:
        payload = await fetch_api(site, item_code)
        if payload is None:
            return None

        parsed = site.page_type.parse(
            payload,
            item_code,
            image_base_url(url),
        )
    else:
        page = await context.new_page()
        try:
            html = await fetch_html(page, site, url)
        finally:
            await page.close()

        if html is None:
            return None

        parsed = site.page_type.parse(html)

    if parsed is None:
        return None

    if parsed.get("page_code") and str(parsed["page_code"]) != str(item_code):
        logger.warning(
            "[%s] %s page shows a different code: %s",
            site.name,
            item_code,
            parsed["page_code"],
        )

    return {
        "item_code": item_code,
        "source": site.name,
        "url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **parsed,
    }


def save_result(out_dir, item_code, result):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{item_code}.json"
    tmp = path.with_suffix(".json.tmp")

    tmp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)  # A half-written file never counts as done.


async def worker(worker_id, context, site, queue, stats, out_dir, total):
    while True:
        try:
            item_code = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        try:
            result = await scrape_item(context, site, item_code)

            if result is None:
                stats["missing"] += 1
                with (out_dir / "_missing.txt").open(
                    "a",
                    encoding="utf-8",
                ) as file:
                    file.write(str(item_code) + "\n")
            else:
                save_result(out_dir, item_code, result)
                stats["saved"] += 1

        except Exception as exc:
            if is_driver_dead(exc):
                logger.error(
                    "[%s] worker %s detected a disconnected Playwright driver "
                    "while processing item %s",
                    site.name,
                    worker_id,
                    item_code,
                )
                raise

            stats["failed"] += 1
            logger.exception("[%s] %s failed", site.name, item_code)

        done = stats["saved"] + stats["missing"] + stats["failed"]
        if done and done % 50 == 0:
            logger.info("[%s] %s/%s done %s", site.name, done, total, stats)


async def run_site(browser, site, item_codes, concurrency):
    out_dir = OUT_DIR / site.page_type.name / site.name
    out_dir.mkdir(parents=True, exist_ok=True)

    queue = asyncio.Queue()
    for code in item_codes:
        queue.put_nowait(code)

    stats = {"saved": 0, "missing": 0, "failed": 0}
    context = await new_context(browser) if browser else None

    tasks = [
        asyncio.create_task(
            worker(
                worker_id,
                context,
                site,
                queue,
                stats,
                out_dir,
                len(item_codes),
            )
        )
        for worker_id in range(1, min(concurrency, len(item_codes)) + 1)
    ]

    try:
        await asyncio.gather(*tasks)
    except BaseException:
        # gather() does not automatically cancel its sibling tasks when one
        # raises. Cancel and await them before closing their shared context.
        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                logger.debug(
                    "[%s] context.close failed; the driver may already be disconnected",
                    site.name,
                    exc_info=True,
                )

    logger.info("[%s] finished: %s", site.name, stats)


async def run_site_chunked(site, item_codes, concurrency, headless):
    if site.api:
        await run_site(None, site, item_codes, concurrency)
        return

    failed_chunks = 0

    for i in range(0, len(item_codes), CHUNK_SIZE):
        chunk = item_codes[i:i + CHUNK_SIZE]

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=headless)

                try:
                    await run_site(browser, site, chunk, concurrency)
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        logger.debug(
                            "[%s] browser.close failed; browser may already be disconnected",
                            site.name,
                            exc_info=True,
                        )

            failed_chunks = 0

        except Exception as exc:
            if not is_driver_dead(exc):
                raise

            failed_chunks += 1
            logger.error(
                "[%s] chunk starting at %s failed: Playwright driver disconnected "
                "(consecutive failures: %s/%s)",
                site.name,
                i,
                failed_chunks,
                MAX_CONSECUTIVE_DRIVER_FAILURES,
            )

            if failed_chunks >= MAX_CONSECUTIVE_DRIVER_FAILURES:
                raise RuntimeError(
                    f"[{site.name}] Playwright driver disconnected for "
                    f"{failed_chunks} consecutive chunks; stopping."
                ) from exc


def image_base_url(page_url):
    """Build the image CDN base URL from the product page URL."""
    parts = urlsplit(page_url)
    hostname = parts.hostname or ""

    if hostname.startswith("www."):
        hostname = "img." + hostname[4:]

    netloc = hostname
    if parts.port:
        netloc = f"{hostname}:{parts.port}"

    return urlunsplit((parts.scheme, netloc, "/", "", ""))



# ============================================================
# Main
# ============================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Scrape supermarket product pages."
    )
    parser.add_argument(
        "--item",
        help="Fetch one item code from every site.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="With --item: also save the JSON to the output folder.",
    )
    parser.add_argument(
        "--site",
        help="Only this site, e.g. 'chain name' or 'chain-name'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max item codes per site (test runs).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip codes listed in _missing.txt from earlier runs.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=API_DELAY_S,
        help="API sites: initial seconds between requests; adapts automatically (default: 2).",
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    if args.save and not args.item:
        parser.error("--save requires --item")

    types = discover_types()
    entries = read_site_entries()

    if args.site:
        wanted = args.site.strip().casefold().replace("-", " ")
        entries = [entry for entry in entries if entry[0] == wanted]

    if not entries:
        logger.error("No matching sites")
        return

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=args.headless)

        try:
            # Detect each site's page type once.
            sites = []
            context = await new_context(browser)

            try:
                for name, example_url, template, example_code in entries:
                    page_type, api = await detect_type(
                        context,
                        name,
                        example_url,
                        example_code,
                        types,
                    )
                    sites.append(
                        Site(name, template, page_type, api, Throttle(args.delay))
                    )
            finally:
                try:
                    await context.close()
                except Exception:
                    logger.debug(
                        "Initial detection context cleanup failed",
                        exc_info=True,
                    )

            if args.item:
                for site in sites:
                    context = None if site.api else await new_context(browser)

                    try:
                        result = await scrape_item(
                            context,
                            site,
                            args.item,
                        )
                    finally:
                        if context:
                            try:
                                await context.close()
                            except Exception:
                                logger.debug(
                                    "[%s] context cleanup failed",
                                    site.name,
                                    exc_info=True,
                                )

                    print(
                        json.dumps(
                            result or {
                                "item_code": args.item,
                                "source": site.name,
                                "found": False,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )

                    if args.save and result:
                        save_result(
                            OUT_DIR / site.name,
                            args.item,
                            result,
                        )
                        logger.info(
                            "[%s] saved -> %s",
                            site.name,
                            (
                                OUT_DIR
                                / site.name
                                / f"{args.item}.json"
                            ).relative_to(ROOT),
                        )

                return

            for site in sites:
                codes = load_item_codes(site.name)

                if not codes:
                    logger.error(
                        "[%s] no item codes found in the DB",
                        site.name,
                    )
                    continue

                out_dir = OUT_DIR / site.page_type.name / site.name
                skip = {path.stem for path in out_dir.glob("*.json")}

                missing_file = out_dir / "_missing.txt"
                if args.skip_missing and missing_file.exists():
                    skip |= set(
                        missing_file.read_text(encoding="utf-8").split()
                    )

                remaining = [
                    code for code in codes
                    if str(code) not in skip
                ]

                if args.limit:
                    remaining = remaining[:args.limit]

                logger.info(
                    "[%s] %s codes in DB, %s to fetch",
                    site.name,
                    len(codes),
                    len(remaining),
                )

                if remaining:
                    await run_site_chunked(
                        site,
                        remaining,
                        args.concurrency,
                        args.headless,
                    )
        finally:
            try:
                await browser.close()
            except Exception:
                logger.debug(
                    "Main browser cleanup failed",
                    exc_info=True,
                )


if __name__ == "__main__":
    asyncio.run(main())