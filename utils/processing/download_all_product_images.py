"""
utils/processing/download_product_image.py

Download product images from parsed product URLs.

"""

import argparse
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx

from logging_config import setup_isolated_logging


PARSED_DIR = Path("data/parsed")
IMAGE_DIR = Path("data/images")

SIZE_OPTIONS = ("medium", "small", "large")
EXTENSION_OPTIONS = ("jpg", "png")

# Delay between image requests in seconds.
# Set to 0 for no delay.
REQUEST_DELAY = 0

MAX_COMPANIES = 3

logger = setup_isolated_logging(
    "download_product_image",
    log_to_console=True,
)


def is_zip_url(url: str) -> bool:
    """Return whether the URL points to a ZIP file."""
    return urlparse(url).path.lower().endswith(".zip")


def render_url(
    url: str,
    size: str,
    extension: str,
) -> str:
    """Replace image URL templates with concrete values."""
    url = url.replace("{{size}}", size)

    return re.sub(
        r"\{\{extension(?:\|\|[^}]*)?\}\}",
        extension,
        url,
    )


def get_image_urls(product: dict) -> list[str]:
    """Return unique non-empty image URLs from a parsed product."""
    urls = []

    main_url = product.get("main_image_url")

    if main_url:
        urls.append(main_url)

    for image in product.get("images") or []:
        if not isinstance(image, dict):
            continue

        url = image.get("url")

        if url:
            urls.append(url)

    return list(dict.fromkeys(urls))


def is_valid_image(response: httpx.Response) -> bool:
    """Return whether the response contains an image."""
    if response.status_code != 200:
        return False

    content_type = response.headers.get(
        "content-type",
        "",
    ).lower()

    return content_type.startswith("image/") and bool(
        response.content
    )


def download_image(
    client: httpx.Client,
    source_url: str,
    output_path: Path,
) -> tuple[bool, str | None]:
    """
    Try image variants in order.

    medium.jpg
    small.jpg
    large.jpg
    medium.png
    small.png
    large.png
    """
    for size in SIZE_OPTIONS:
        for extension in EXTENSION_OPTIONS:
            url = render_url(
                source_url,
                size,
                extension,
            )

            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                logger.debug(
                    "Request failed: %s - %s",
                    url,
                    exc,
                )

                if REQUEST_DELAY > 0:
                    time.sleep(REQUEST_DELAY)

                continue

            if REQUEST_DELAY > 0:
                time.sleep(REQUEST_DELAY)

            if not is_valid_image(response):
                logger.debug(
                    "Image failed: %s - HTTP %s - %s",
                    url,
                    response.status_code,
                    response.headers.get(
                        "content-type",
                        "",
                    ),
                )
                continue

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_path = output_path.with_suffix(
                f".{extension}"
            )

            output_path.write_bytes(
                response.content
            )

            return True, url

    return False, None


def get_output_path(
    company: str,
    barcode: object,
    image_index: int,
) -> Path:
    """Build the image path."""
    barcode_value = (
        str(barcode)
        if barcode not in (None, "")
        else "unknown_barcode"
    )

    return (
        IMAGE_DIR
        / company
        / f"{barcode_value}_{image_index:03d}.jpg"
    )


def image_exists(output_path: Path) -> bool:
    """Return whether an image already exists."""
    return (
        output_path.with_suffix(".jpg").exists()
        or output_path.with_suffix(".png").exists()
    )


def process_company(
    company: str,
    company_dir: Path,
) -> None:
    """Download product images for one company."""
    files = sorted(
        company_dir.glob("*.jsonl")
    )

    processed = 0

    logger.info(
        "Starting company: %s",
        company,
    )

    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/154.0 Safari/537.36"
            )
        },
    ) as client:
        for parsed_file in files:
            with parsed_file.open(
                encoding="utf-8"
            ) as f:
                for line in f:
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        product = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Invalid JSON: %s",
                            parsed_file,
                        )
                        continue

                    urls = get_image_urls(product)

                    if not urls:
                        continue

                    barcode = product.get("barcode")

                    logger.info(
                        "[%s] barcode=%s urls=%d",
                        company,
                        barcode,
                        len(urls),
                    )

                    image_index = 1

                    for source_url in urls:
                        if is_zip_url(source_url):
                            logger.info(
                                "SKIP ZIP: %s",
                                source_url,
                            )
                            continue

                        output_path = get_output_path(
                            company,
                            barcode,
                            image_index,
                        )

                        if image_exists(output_path):
                            existing_path = (
                                output_path.with_suffix(".jpg")
                                if output_path.with_suffix(
                                    ".jpg"
                                ).exists()
                                else output_path.with_suffix(".png")
                            )

                            logger.info(
                                "Already exists: %s",
                                existing_path,
                            )

                            image_index += 1
                            continue

                        success, resolved_url = (
                            download_image(
                                client,
                                source_url,
                                output_path,
                            )
                        )

                        if success:
                            saved_path = (
                                output_path.with_suffix(
                                    Path(resolved_url).suffix
                                    or ".jpg"
                                )
                            )

                            logger.info(
                                "Downloaded: %s",
                                resolved_url,
                            )
                            logger.info(
                                "Saved: %s",
                                saved_path,
                            )
                            image_index += 1
                        else:
                            logger.warning(
                                "Could not download image: "
                                "barcode=%s url=%s",
                                barcode,
                                source_url,
                            )

                    processed += 1

    logger.info(
        "Finished company: %s - %d products",
        company,
        processed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download parsed product images."
    )

    parser.add_argument(
        "--company",
        help="Process only this company.",
    )

    args = parser.parse_args()

    companies = sorted(
        path
        for path in PARSED_DIR.iterdir()
        if path.is_dir()
    )

    if args.company:
        companies = [
            path
            for path in companies
            if path.name == args.company
        ]

    logger.info(
        "Found %d companies: %s",
        len(companies),
        ", ".join(
            path.name for path in companies
        ),
    )

    with ThreadPoolExecutor(
        max_workers=MAX_COMPANIES
    ) as executor:
        futures = [
            executor.submit(
                process_company,
                company_dir.name,
                company_dir,
            )
            for company_dir in companies
        ]

        for future in futures:
            future.result()


if __name__ == "__main__":
    main()