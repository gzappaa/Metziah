"""
scrapers/generic.py

Generic scraper for retailer category products.

Scrapes every retailer marked as available=true in
data/reference/chains_extra.json.

Available retailers run concurrently. Categories and branches within
each retailer are processed sequentially to avoid excessive request
concurrency.

Results are saved under:
    data/raw/<retailer name>/<category_id>.json

Logging is isolated to:
    logs/scrape_categories.log
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from logging_config import setup_isolated_logging


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG_FILE = (
    PROJECT_ROOT
    / "monitoring"
    / "data"
    / "scraper_coverage.json"
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw"

MAX_RETAILERS = 10
PAGE_SIZE = 100
REQUEST_TIMEOUT = 10.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": (
        "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7"
    ),
}


logger = setup_isolated_logging(
    "scrape_categories",
    log_to_console=True,
)


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
                return text[start : i + 1]

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


def load_retailers():
    with CONFIG_FILE.open(encoding="utf-8") as file:
        config = json.load(file)

    return [
        {
            "chain_id": chain_id,
            **retailer,
        }
        for chain_id, retailer in config.items()
        if retailer.get("available") is True
    ]


def get_frontend_data(client, retailer):
    response = client.get(retailer["data_url"])
    response.raise_for_status()

    return json.loads(
        extract_js_object(
            response.text,
            "frontendData",
        )
    )


def scrape_category(
    client,
    retailer,
    branch_id,
    category_id,
):
    url = retailer["scraping_url"].format(
        branch_id=branch_id,
        category_id=category_id,
    )

    try:
        response = client.get(
            url,
            params={
                "from": 0,
                "size": PAGE_SIZE,
            },
        )
        response.raise_for_status()
        data = response.json()

    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "[%s] branch=%s category=%s ERROR: %s",
            retailer["name_en_normalized"],
            branch_id,
            category_id,
            exc,
        )
        return None

    total = data.get("total", 0)
    products = data.get("products", [])

    logger.info(
        "[%s] branch=%s category=%s products=%s/%s",
        retailer["name_en_normalized"],
        branch_id,
        category_id,
        len(products),
        total,
    )

    if not products:
        return None

    while len(products) < total:
        offset = len(products)

        try:
            response = client.get(
                url,
                params={
                    "from": offset,
                    "size": PAGE_SIZE,
                },
            )
            response.raise_for_status()
            page_data = response.json()

        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "[%s] branch=%s category=%s "
                "pagination ERROR: %s",
                retailer["name_en_normalized"],
                branch_id,
                category_id,
                exc,
            )
            return None

        page_products = page_data.get("products", [])

        if not page_products:
            logger.warning(
                "[%s] branch=%s category=%s "
                "pagination stopped unexpectedly",
                retailer["name_en_normalized"],
                branch_id,
                category_id,
            )
            return None

        products.extend(page_products)

        logger.info(
            "[%s] branch=%s category=%s products=%s/%s",
            retailer["name_en_normalized"],
            branch_id,
            category_id,
            len(products),
            total,
        )

    if len(products) < total:
        logger.warning(
            "[%s] branch=%s category=%s "
            "INCOMPLETE -> skipping",
            retailer["name_en_normalized"],
            branch_id,
            category_id,
        )
        return None

    data["products"] = products

    data["_metziah"] = {
        "chain_id": retailer["chain_id"],
        "retailer_id": retailer["retailer_id"],
        "branch_id": branch_id,
        "category_id": category_id,
    }

    return data


def scrape_retailer(retailer):
    name = retailer["name_en_normalized"]
    retailer_id = retailer["retailer_id"]

    output_dir = OUTPUT_DIR / name
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger.info(
        "[%s] START retailer_id=%s",
        name,
        retailer_id,
    )

    try:
        with httpx.Client(
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            frontend_data = get_frontend_data(
                client,
                retailer,
            )

            categories = get_all_categories(
                frontend_data["tree"]["categories"]
            )

            branches = frontend_data["retailer"]["branches"]

            branch_ids = [
                str(branch["id"])
                for branch in branches
            ]

            logger.info(
                "[%s] categories=%s branches=%s",
                name,
                len(categories),
                len(branch_ids),
            )

            for index, category in enumerate(
                categories,
                1,
            ):
                category_id = category["id"]

                output_file = (
                    output_dir
                    / f"{category_id}.json"
                )

                if output_file.exists():
                    logger.info(
                        "[%s] [%s/%s] category=%s "
                        "already saved",
                        name,
                        index,
                        len(categories),
                        category_id,
                    )
                    continue

                logger.info(
                    "[%s] [%s/%s] category=%s",
                    name,
                    index,
                    len(categories),
                    category_id,
                )

                found = False

                for branch_id in branch_ids:
                    data = scrape_category(
                        client=client,
                        retailer=retailer,
                        branch_id=branch_id,
                        category_id=category_id,
                    )

                    if data is None:
                        continue

                    output_file.write_text(
                        json.dumps(
                            data,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                    logger.info(
                        "[%s] category=%s FOUND "
                        "branch=%s -> %s",
                        name,
                        category_id,
                        branch_id,
                        output_file,
                    )

                    found = True
                    break

                if not found:
                    logger.info(
                        "[%s] category=%s "
                        "no products in any branch",
                        name,
                        category_id,
                    )

    except Exception:
        logger.exception(
            "[%s] FAILED",
            name,
        )
        return False

    logger.info(
        "[%s] FINISHED",
        name,
    )

    return True


def main():
    retailers = load_retailers()

    if not retailers:
        logger.warning(
            "No retailers with available=true found"
        )
        return

    logger.info(
        "Found %s available retailers: %s",
        len(retailers),
        ", ".join(
            retailer["name_en_normalized"]
            for retailer in retailers
        ),
    )

    with ThreadPoolExecutor(
        max_workers=min(
            MAX_RETAILERS,
            len(retailers),
        )
    ) as executor:
        futures = {
            executor.submit(
                scrape_retailer,
                retailer,
            ): retailer
            for retailer in retailers
        }

        for future in as_completed(futures):
            retailer = futures[future]
            name = retailer["name_en_normalized"]

            try:
                success = future.result()

                if success:
                    logger.info(
                        "[%s] completed successfully",
                        name,
                    )
                else:
                    logger.error(
                        "[%s] completed with errors",
                        name,
                    )

            except Exception:
                logger.exception(
                    "[%s] worker crashed",
                    name,
                )

    logger.info("All available retailers finished")


if __name__ == "__main__":
    main()