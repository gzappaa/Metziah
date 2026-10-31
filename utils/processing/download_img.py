"""
utils/processing/download_product_images.py

Download one image per database product, using item_code as the filename.

Images are saved to:
    data/images/products/{item_code}.jpg

Usage:
    python utils/processing/download_product_images.py --item-code 7290019431169
    python utils/processing/download_product_images.py --item-code 7290019431169 --item-code 7290012252891
    python utils/processing/download_product_images.py --all

By default, only explicitly requested products are processed.
--all enables bulk downloading. Existing images are skipped.
"""

import argparse
import io
import json
import logging
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARSED_DIR = PROJECT_ROOT / "data" / "parsed"
IMAGE_DIR = PROJECT_ROOT / "data" / "images" / "products"

IMAGE_TIMEOUT = 20.0
MIN_IMAGE_BYTES = 128

TEMPLATE_SIZES = ("large", "medium", "small", "400", "300", "200", "original")
TEMPLATE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")


def load_database_item_codes() -> set[str]:
    """Load product codes present in both products and product_enrichment."""
    from db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT p.item_code
            FROM products AS p
            INNER JOIN product_enrichment AS pe
                ON pe.item_code = p.item_code
            WHERE p.item_code IS NOT NULL
            """
        )

        return {
            str(row[0]).strip()
            for row in cur.fetchall()
            if row[0]
        }


def record_item_code(record: dict) -> str | None:
    """Return the record's barcode-like key, if present."""
    for key in ("item_code", "barcode", "ean", "gtin", "itemCode"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def image_urls(record: dict) -> list[str]:
    """Extract image URL candidates from a parsed product record."""
    found = []

    for key in ("main_image_url", "image_url", "image"):
        value = record.get(key)

        if isinstance(value, str) and value.strip():
            found.append(value.strip())
        elif isinstance(value, dict):
            url = value.get("url")
            if isinstance(url, str) and url.strip():
                found.append(url.strip())

    images = record.get("images")

    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.strip():
                found.append(image.strip())
            elif isinstance(image, dict):
                url = image.get("url")
                if isinstance(url, str) and url.strip():
                    found.append(url.strip())

    return list(dict.fromkeys(found))


def iter_parsed_records() -> Iterable[tuple[Path, dict]]:
    """Yield records from parsed JSONL files."""
    if not PARSED_DIR.exists():
        logger.warning(
            "Parsed data directory does not exist: %s",
            PARSED_DIR,
        )
        return

    for path in sorted(PARSED_DIR.rglob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    if not line.strip():
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Skipping invalid JSON in %s:%s",
                            path,
                            line_number,
                        )
                        continue

                    if isinstance(record, dict):
                        yield path, record

        except OSError:
            logger.exception("Could not read parsed file %s", path)


def collect_image_candidates(
    requested_codes: set[str],
) -> dict[str, list[str]]:
    """Collect image URLs for requested products across retailer files."""
    candidates = {code: [] for code in requested_codes}

    for _, record in iter_parsed_records():
        code = record_item_code(record)

        if code not in candidates:
            continue

        for url in image_urls(record):
            if url not in candidates[code]:
                candidates[code].append(url)

    return candidates


def expand_url_template(url: str) -> list[str]:
    """Expand common image URL templates into concrete URL attempts."""
    if "{{" not in url and "}}" not in url:
        return [url]

    variants = []

    for size in TEMPLATE_SIZES:
        for extension in TEMPLATE_EXTENSIONS:
            candidate = url.replace("{{size}}", size)

            candidate = re.sub(
                r"\{\{\s*extension\s*\|\|\s*['\"](jpg|jpeg|png|webp)['\"]\s*\}\}",
                extension,
                candidate,
                flags=re.IGNORECASE,
            )

            candidate = re.sub(
                r"\{\{\s*extension\s*\}\}",
                extension,
                candidate,
                flags=re.IGNORECASE,
            )

            if "{{" not in candidate and "}}" not in candidate:
                if candidate not in variants:
                    variants.append(candidate)

    return variants


def all_url_attempts(urls: list[str]) -> list[str]:
    """Return concrete URLs, preserving candidate priority."""
    attempts = []

    for url in urls:
        for candidate in expand_url_template(url):
            if candidate not in attempts:
                attempts.append(candidate)

    return attempts


def image_bytes_to_jpeg(data: bytes) -> bytes | None:
    """Validate image bytes and convert valid images to JPEG."""
    if len(data) < MIN_IMAGE_BYTES:
        return None

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()

            if image.width < 2 or image.height < 2:
                return None

            if (
                image.mode in ("RGBA", "LA")
                or (
                    image.mode == "P"
                    and "transparency" in image.info
                )
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(
                    rgba,
                    mask=rgba.getchannel("A"),
                )
                image = background
            else:
                image = image.convert("RGB")

            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=90,
                optimize=True,
            )
            return output.getvalue()

    except (UnidentifiedImageError, OSError, ValueError):
        return None


def download_one_image(
    client: httpx.Client,
    item_code: str,
    urls: list[str],
) -> bool:
    """Download the first valid image, skipping an existing cached file."""
    output_path = IMAGE_DIR / f"{item_code}.jpg"

    if output_path.is_file() and output_path.stat().st_size > 0:
        logger.info("[%s] image already exists; skipping", item_code)
        return True

    attempts = all_url_attempts(urls)

    if not attempts:
        logger.info("[%s] no image URL candidates found", item_code)
        return False

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    for url in attempts:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue

        try:
            response = client.get(url)

            if response.status_code != 200:
                logger.debug(
                    "[%s] HTTP %s: %s",
                    item_code,
                    response.status_code,
                    url,
                )
                continue

            jpeg_data = image_bytes_to_jpeg(response.content)

            if jpeg_data is None:
                logger.debug(
                    "[%s] URL did not return a valid image: %s",
                    item_code,
                    url,
                )
                continue

            # Atomic write: a partial download won't appear as a completed image.
            temporary_path = output_path.with_suffix(".jpg.tmp")
            temporary_path.write_bytes(jpeg_data)
            temporary_path.replace(output_path)

            logger.info("[%s] saved image from %s", item_code, url)
            return True

        except (httpx.HTTPError, OSError):
            logger.debug(
                "[%s] failed image URL: %s",
                item_code,
                url,
                exc_info=True,
            )

    logger.warning(
        "[%s] all %s image URL attempts failed",
        item_code,
        len(attempts),
    )
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and cache product images by item_code."
    )

    parser.add_argument(
        "--item-code",
        action="append",
        dest="item_codes",
        help="Database item_code to download; repeat for multiple products.",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Attempt image downloads for every item_code in products.",
    )

    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args()

    if args.all and args.item_codes:
        logger.error("Use either --all or --item-code, not both.")
        return 2

    if not args.all and not args.item_codes:
        logger.error("Specify --item-code ITEM_CODE or --all.")
        return 2

    database_codes = load_database_item_codes()

    if args.all:
        target_codes = database_codes
    else:
        target_codes = set(args.item_codes)
        unknown_codes = target_codes - database_codes

        if unknown_codes:
            logger.warning(
                "Ignoring codes not found in products: %s",
                ", ".join(sorted(unknown_codes)),
            )

        target_codes &= database_codes

    if not target_codes:
        logger.info("No database products to process.")
        return 0

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    cached_codes = {
        code
        for code in target_codes
        if (IMAGE_DIR / f"{code}.jpg").is_file()
        and (IMAGE_DIR / f"{code}.jpg").stat().st_size > 0
    }

    missing_codes = target_codes - cached_codes

    logger.info(
        "Requested: %s; cached: %s; needing lookup: %s",
        len(target_codes),
        len(cached_codes),
        len(missing_codes),
    )

    if not missing_codes:
        return 0

    candidates = collect_image_candidates(missing_codes)
    downloaded = 0
    failed = 0

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }

    with httpx.Client(
        headers=headers,
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        for code in sorted(missing_codes):
            if download_one_image(
                client,
                code,
                candidates.get(code, []),
            ):
                downloaded += 1
            else:
                failed += 1

    logger.info(
        "Finished. Downloaded: %s; failed/unavailable: %s; already cached: %s",
        downloaded,
        failed,
        len(cached_codes),
    )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())