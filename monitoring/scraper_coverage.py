"""
monitoring/scraper_coverage.py

Discover the frontend/API structure used by Metziah's generic web scraper.

For each supermarket website in chains.json:

    - try normal HTTP first
    - discover data.js directly from the homepage HTML
    - if normal HTTP succeeds but data.js cannot be discovered,
      use Playwright only to observe the frontend request
    - if the homepage returns HTTP 403, use Playwright as a fallback
    - extract frontendData
    - validate branches and categories
    - build the product API URL

Websites successfully discovered through normal HTTP are saved with:

    "available": true

Websites requiring Playwright only because data.js is dynamically requested
are also saved with:

    "available": true

Websites whose homepage returns HTTP 403 and therefore require the
Playwright fallback are saved with:

    "available": false

Websites for which discovery fails completely are omitted.

This does NOT scrape products or validate the complete scraper.
"""

import json
import re
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]

CHAINS_FILE = BASE_DIR / "data" / "reference" / "chains.json"

OUTPUT_FILE = (
    BASE_DIR
    / "monitoring"
    / "data"
    / "scraper_coverage.json"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}


def extract_js_object(text, key):
    marker = f"{key}:"
    start = text.find(marker)

    if start == -1:
        raise ValueError(f"Could not find {key}")

    start = text.find("{", start)

    if start == -1:
        raise ValueError(f"Could not find object for {key}")

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        char = text[i]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True

        elif char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    raise ValueError(f"Could not extract {key}")


def get_all_categories(categories):
    result = []

    for category in categories:
        result.append(category)

        result.extend(
            get_all_categories(
                category.get("subCategories", [])
            )
        )

    return result


def get_data_url_from_html(html):
    match = re.search(
        r'<script[^>]+src=["\']([^"\']*data\.js[^"\']*)["\']',
        html,
        re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(1)


def get_data_url_with_playwright(url):
    data_url = None

    with sync_playwright() as p:
        browser = p.chromium.launch()

        page = browser.new_page(
            user_agent=HEADERS["User-Agent"],
            locale="he-IL",
        )

        def handle_request(request):
            nonlocal data_url

            if "/data.js" in request.url:
                data_url = request.url

                print(
                    f"  Found data.js request: {data_url}"
                )

        def handle_response(response):
            nonlocal data_url

            if "/data.js" in response.url:
                data_url = response.url

                print(
                    "  Found data.js response: "
                    f"{response.url} "
                    f"(status {response.status})"
                )

        page.on("request", handle_request)
        page.on("response", handle_response)

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        print(
            "  Playwright page status: "
            f"{response.status if response else 'unknown'}"
        )

        print(
            f"  Playwright page title: "
            f"{page.title()}"
        )

        if not data_url:
            page.wait_for_timeout(3_000)

        if not data_url:
            html = page.content()

            data_url = get_data_url_from_html(
                html,
            )

            if data_url:
                print(
                    "  Found data.js in rendered HTML: "
                    f"{data_url}"
                )

        browser.close()

    if not data_url:
        raise RuntimeError(
            "Playwright could not find data.js."
        )

    return data_url


def discover_website(client, website_url):
    website_url = website_url.rstrip("/") + "/"

    used_playwright_fallback = False

    response = client.get(
        website_url,
        headers=HEADERS,
        timeout=30,
    )

    if response.status_code == 403:
        used_playwright_fallback = True

        print(
            "  HTTP 403 — falling back to Playwright..."
        )

        data_url = get_data_url_with_playwright(
            website_url,
        )

    else:
        response.raise_for_status()

        html = response.text

        data_url = get_data_url_from_html(
            html,
        )

        if data_url:
            print(
                "  Found data.js in homepage HTML: "
                f"{data_url}"
            )

        if not data_url:
            print(
                "  data.js not found through normal HTTP — "
                "using Playwright for request discovery..."
            )

            data_url = get_data_url_with_playwright(
                website_url,
            )

    print(f"  data.js: {data_url}")

    data_response = client.get(
        data_url,
        headers=HEADERS,
        timeout=30,
    )

    data_response.raise_for_status()

    js = data_response.text

    frontend_data_text = extract_js_object(
        js,
        "frontendData",
    )

    frontend_data = json.loads(
        frontend_data_text,
    )

    retailer_id = frontend_data["rid"]

    branches = frontend_data["retailer"]["branches"]

    categories = get_all_categories(
        frontend_data["tree"]["categories"]
    )

    if not branches:
        raise RuntimeError("No branches found")

    if not categories:
        raise RuntimeError("No categories found")

    scraping_url = (
        f"{website_url.rstrip('/')}"
        f"/v2/retailers/{retailer_id}"
        f"/branches/{{branch_id}}"
        f"/categories/{{category_id}}/products"
    )

    return {
        "data_url": data_url,
        "scraping_url": scraping_url,
        "retailer_id": retailer_id,
        "available": not used_playwright_fallback,
    }


def main():
    if not CHAINS_FILE.exists():
        print(
            f"File not found: {CHAINS_FILE}"
        )
        raise SystemExit(1)

    with CHAINS_FILE.open(
        encoding="utf-8",
    ) as f:
        chains = json.load(f)

    websites = []

    for chain_id, chain in chains.items():
        website = chain.get("web_site")

        if not website:
            continue

        websites.append(
            (
                chain_id,
                chain.get(
                    "name_en_normalized",
                    "",
                ),
                website,
            )
        )

    total = len(websites)

    normal_count = 0
    playwright_count = 0
    failed_count = 0

    coverage = {}

    with httpx.Client(
        follow_redirects=True,
    ) as client:
        for index, (
            chain_id,
            name,
            website,
        ) in enumerate(
            websites,
            1,
        ):
            print(
                f"[{index}/{total}] "
                f"{chain_id} | {name} | {website}"
            )

            try:
                result = discover_website(
                    client,
                    website,
                )

            except Exception as e:
                failed_count += 1

                print(
                    f"  FAILED: "
                    f"{type(e).__name__}: {e}"
                )

                continue

            coverage[chain_id] = {
                "name_en_normalized": name,
                "web_site": website,
                "data_url": result["data_url"],
                "scraping_url": result["scraping_url"],
                "retailer_id": result["retailer_id"],
                "available": result["available"],
            }

            if result["available"]:
                normal_count += 1
                print("  OK")
            else:
                playwright_count += 1
                print(
                    "  PLAYWRIGHT FALLBACK"
                )

            print(
                f"  scraping: "
                f"{result['scraping_url']}"
            )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            coverage,
            f,
            ensure_ascii=False,
            indent=4,
        )

    print()
    print("=" * 40)
    print(
        f"Normal: {normal_count}"
    )
    print(
        f"Playwright fallback: "
        f"{playwright_count}"
    )
    print(
        f"Failed: {failed_count}"
    )
    print(
        f"Saved: "
        f"{len(coverage)}/{total}"
    )
    print(
        f"Output: {OUTPUT_FILE}"
    )
    print("=" * 40)


if __name__ == "__main__":
    main()