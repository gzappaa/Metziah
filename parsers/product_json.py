
"""
parsers/product_json.py

Parse chain product JSON dumps (data/raw/{company}/*.json) into flat records.

Import usage:
    from parsers.product_json import iter_products, parse_product
"""

import json
import re
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from database.records import is_valid_gtin

# Language ids as seen in the samples
HE, EN, RU = "1", "2", "4"


def _get(d: Any, *keys: str) -> Any:
    """Safe nested get: _get(raw, "brand", "names", "1") -> value or None."""
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _barcode_from_image_url(url: Any) -> str | None:
    """Extract a valid GTIN from a GS1 product image URL."""
    if not isinstance(url, str):
        return None

    path = urlparse(url).path

    if "product-images" in path or "gs1-products" not in path:
        return None

    match = re.search(r"/\{\{size\}\}/(\d+)", path)
    if not match:
        return None

    candidate = match.group(1)
    return candidate if is_valid_gtin(candidate) else None


def _resolve_barcode(
    raw_barcode: Any,
    images: list[dict[str, Any]],
) -> str | None:
    """Preserve the source barcode; infer one from images only if missing."""
    if raw_barcode is not None and str(raw_barcode).strip():
        return str(raw_barcode).strip()

    for image in images:
        candidate = _barcode_from_image_url(image.get("url"))
        if candidate:
            return candidate

    return None


def _collect_images(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge `image` (default) and `images` (array) into one deduplicated list.

    URLs are kept exactly as in the source (size/extension placeholders untouched).
    """
    candidates: list[dict[str, Any]] = []
    if isinstance(raw.get("image"), dict):
        candidates.append(raw["image"])
    candidates.extend(i for i in (raw.get("images") or []) if isinstance(i, dict))

    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for img in candidates:
        key = img.get("id", img.get("url"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": img.get("id"),
            "url": img.get("url"),
            "is_default": bool(img.get("isDefault")),
            "classification": img.get("classification"),
            "sort": img.get("sort"),
            "source": img.get("source"),
            "tag": img.get("tag"),
            "uploaded_on": img.get("uploadedOn"),
            "backup_path": img.get("backupPath"),
        })
    return out


def _main_category_path(family: dict[str, Any]) -> list[dict[str, Any]]:
    """The path selected by mainCategoryPathIndex, or [] if missing/invalid."""
    paths = family.get("categoriesPaths") or []
    idx = family.get("mainCategoryPathIndex")
    if isinstance(idx, int) and 0 <= idx < len(paths) and isinstance(paths[idx], list):
        return paths[idx]
    return []


def parse_product(raw: dict[str, Any]) -> dict[str, Any]:
    family = raw.get("family") or {}
    data = raw.get("data") or {}
    main_path = _main_category_path(family)
    images = _collect_images(raw)
    default_image = next((i for i in images if i["is_default"]), None)

    return {
        # --- identity ---
        "barcode": _resolve_barcode(raw.get("barcode"), images),
        "local_barcode": raw.get("localBarcode"),
        "product_id": raw.get("productId"),
        "id": raw.get("id"),
        "retailer_id": raw.get("retailerId"),
        "supplier_id": raw.get("supplierId"),
        # --- name ---
        "local_name": raw.get("localName"),
        "name_he": _get(raw, "names", HE, "long"),
        "name_en": _get(raw, "names", EN, "long"),
        "name_ru": _get(raw, "names", RU, "long"),
        # --- brand ---
        "brand_id": _get(raw, "brand", "id"),
        "brand_name_he": _get(raw, "brand", "names", HE),
        "brand_name_en": _get(raw, "brand", "names", EN),
        "brand_name_ru": _get(raw, "brand", "names", RU),
        # --- search keywords ---
        "search_keywords": raw.get("searchKeywords") or [],
        "family_search_keywords": family.get("searchKeywords") or [],
        # --- department ---
        "department_id": _get(raw, "department", "id"),
        "department_external_id": _get(raw, "department", "externalId"),
        "department_name": _get(raw, "department", "name"),
        # --- family + categories ---
        "family_id": family.get("id"),
        "family_name_he": _get(family, "names", HE, "name"),
        "family_name_en": _get(family, "names", EN, "name"),
        "category_ids": [c.get("id") for c in family.get("categories") or []],
        "category_path_ids": [c.get("id") for c in main_path],
        "category_path_he": [_get(c, "names", HE) for c in main_path],
        "category_path_en": [_get(c, "names", EN) for c in main_path],
        "categories_paths": family.get("categoriesPaths") or [],
        # --- content ---
        "ingredients_he": _get(data, HE, "ingredients"),
        "ingredients_en": _get(data, EN, "ingredients"),
        "ingredients_ru": _get(data, RU, "ingredients"),
        "description_he": _get(data, HE, "description"),
        "description_en": _get(data, EN, "description"),
        "description_ru": _get(data, RU, "description"),
        # --- nutrition ---
        "nutrition_facts": raw.get("nutritionFacts"),
        "nutrition_values": raw.get("nutritionValues"),
        # --- images ---
        "main_image_url": default_image["url"] if default_image else None,
        "images": images,
        "nutrition_image_url": raw.get("nutritionImageUrl"),
    }


def iter_products(
    path: Path,
    stats: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed products and optionally count recovered barcodes."""
    with path.open(encoding="utf-8") as f:
        doc = json.load(f)

    if isinstance(doc, dict) and isinstance(doc.get("products"), list):
        products = doc["products"]
    elif isinstance(doc, list):
        products = doc
    else:
        keys = list(doc)[:5] if isinstance(doc, dict) else type(doc).__name__
        raise ValueError(f"no 'products' list (top-level: {keys})")

    for raw in products:
        if not isinstance(raw, dict):
            continue

        product = parse_product(raw)

        raw_barcode = raw.get("barcode")
        if (
            stats is not None
            and (raw_barcode is None or not str(raw_barcode).strip())
            and product["barcode"] is not None
        ):
            stats["barcodes_recovered"] = (
                stats.get("barcodes_recovered", 0) + 1
            )

        yield product
