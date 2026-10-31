
"""
parsers/product_page_type1.py

Parse type_1 product page dumps into the same flat record
schema as parsers/product_json.py and parsers/product_page_type2.py.
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterator

from database.records import is_valid_gtin

HE = "1"
PLACEHOLDER_IMAGE_NAMES = {"Z_P_default.png", "S_P_default.png"}

S_DATA = "נתונים"
S_INGREDIENTS = "רכיבים"
S_NUTRITION = "ערכים תזונתיים"
K_BRAND = "מותג/יצרן"
K_SKU = 'מק"ט'

_LESS_THAN_RE = re.compile(r"^\s*(?:פחות\s*מ[-־\s]*|<\s*)(.+)$")


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    return value or None


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _join(value: Any) -> str | None:
    if isinstance(value, list):
        parts = [t for t in (_text(v) for v in value) if t]
        return ", ".join(parts) or None
    return _text(value)


def _sections(raw: Mapping[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for section in raw.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        title = _text(section.get("title"))
        if title:
            out.setdefault(title, []).append(section.get("content"))
    return out


def _to_number(value: Any) -> int | float | str | None:
    s = _text(value)
    if s is None:
        return None
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return s
    return int(f) if f.is_integer() else f


def _split_less_than(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        m = _LESS_THAN_RE.match(value)
        if m:
            return _to_number(m.group(1)), True
    return _to_number(value) if isinstance(value, str) else value, False


def _resolve_barcode(
    raw: Mapping[str, Any],
    data: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    candidates = [
        _text(raw.get("item_code")),
        _text(raw.get("page_code")),
        _text(_first(data.get(K_SKU))),
    ]
    for candidate in candidates:
        if candidate and is_valid_gtin(candidate):
            return candidate, None
    return None, next((c for c in candidates if c), None)


def _basis_label(basis: Any) -> str:
    b = (_text(basis) or "unknown").replace('"', "").replace("״", "")
    if b.startswith("ל"):
        return b
    return f"ל-{b}" if b[0].isdigit() else f"ל{b}"


def _categories(raw: Mapping[str, Any]) -> list[str]:
    """Return breadcrumb categories, excluding the root and product name."""
    categories = raw.get("categories")
    if not isinstance(categories, list) or len(categories) <= 2:
        return []

    names = []
    for item in categories[1:-1]:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get(HE))
        if name:
            names.append(name)

    return names


def _nutrition_values(
    sections: Mapping[str, list[Any]],
) -> dict[str, Any] | None:
    blocks: list[Mapping[str, Any]] = []
    for content in sections.get(S_NUTRITION, []):
        items = content if isinstance(content, list) else [content]
        blocks.extend(i for i in items if isinstance(i, Mapping))

    sizes: list[dict[str, Any]] = []
    values: dict[str, dict[str, Any]] = {}

    for block in blocks:
        nutrients = block.get("nutrients")
        if not isinstance(nutrients, Mapping) or not nutrients:
            continue

        size_id = len(sizes) + 1
        sizes.append({
            "id": size_id,
            "names": {HE: _basis_label(block.get("for"))},
        })

        for name, item in nutrients.items():
            name = str(name).strip()
            if not name:
                continue

            if isinstance(item, Mapping):
                value, less = _split_less_than(item.get("value"))
                unit = _text(item.get("unit")) or ""
            else:
                value, less = _split_less_than(item)
                unit = ""

            entry = values.setdefault(
                name,
                {"id": None, "names": {HE: name}, "sizeValues": []},
            )
            entry["sizeValues"].append({
                "sizeId": size_id,
                "unitOfMeasure": {"names": {HE: unit}},
                "value": value,
                "valueLessThan": less,
            })

    if not sizes:
        return None

    return {"sizes": sizes, "values": list(values.values())}


def _classification(url: str) -> str | None:
    match = re.search(r"/products_([a-z]+)/", url)
    return match.group(1) if match else None


def _collect_images(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    urls: list[str] = []

    for url in raw.get("images") or []:
        url = _text(url)
        if not url or url in seen:
            continue
        if Path(url.split("?", 1)[0]).name in PLACEHOLDER_IMAGE_NAMES:
            continue
        seen.add(url)
        urls.append(url)

    default = next(
        (url for url in urls if _classification(url) == "zoom"),
        urls[0] if urls else None,
    )

    return [
        {
            "id": None,
            "url": url,
            "is_default": url == default,
            "classification": _classification(url),
            "sort": i,
            "source": None,
            "tag": None,
            "uploaded_on": None,
            "backup_path": None,
        }
        for i, url in enumerate(urls)
    ]


def parse_product(
    raw: dict[str, Any],
    company: str,
    source_file: str,
) -> dict[str, Any]:
    sections = _sections(raw)

    data: Mapping[str, Any] = {}
    for content in sections.get(S_DATA, []):
        if isinstance(content, Mapping):
            data = content
            break

    barcode, local_barcode = _resolve_barcode(raw, data)
    images = _collect_images(raw)
    default_image = next((image for image in images if image["is_default"]), None)
    name = _text(raw.get("name"))
    categories = _categories(raw)

    ingredients = next(
        (
            ingredient
            for ingredient in (
                _join(content) for content in sections.get(S_INGREDIENTS, [])
            )
            if ingredient
        ),
        None,
    )

    return {
        "company": company,
        "source": company,
        "source_file": source_file,

        "barcode": barcode,
        "local_barcode": local_barcode,
        "product_id": None,
        "id": None,
        "retailer_id": None,
        "supplier_id": None,

        "local_name": name,
        "name_he": name,
        "name_en": None,
        "name_ru": None,

        "brand_id": None,
        "brand_name_he": _text(_first(data.get(K_BRAND))),
        "brand_name_en": None,
        "brand_name_ru": None,

        "search_keywords": [],
        "family_search_keywords": [],

        "department_id": None,
        "department_external_id": None,
        "department_name": None,

        "family_id": None,
        "family_name_he": None,
        "family_name_en": None,
        "category_ids": [],
        "category_path_ids": [],
        "category_path_he": categories,
        "category_path_en": [],
        "categories_paths": [
            [{HE: category} for category in categories]
        ] if categories else [],

        "ingredients_he": ingredients,
        "ingredients_en": None,
        "ingredients_ru": None,
        "description_he": None,
        "description_en": None,
        "description_ru": None,

        "nutrition_facts": None,
        "nutrition_values": _nutrition_values(sections),

        "main_image_url": default_image["url"] if default_image else None,
        "images": images,
        "nutrition_image_url": None,
    }


def iter_products(
    path: Path,
    stats: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed products; optionally count products without a valid GTIN."""
    with path.open(encoding="utf-8") as f:
        doc = json.load(f)

    if isinstance(doc, Mapping) and "item_code" in doc:
        products = [doc]
    elif isinstance(doc, Mapping) and isinstance(doc.get("products"), list):
        products = doc["products"]
    elif isinstance(doc, list):
        products = doc
    else:
        keys = list(doc)[:5] if isinstance(doc, Mapping) else type(doc).__name__
        raise ValueError(f"unrecognised type_1 layout (top-level: {keys})")

    # Company comes from the directory containing the JSON file.
    company = path.parent.name
    source_file = path.name

    for raw in products:
        if not isinstance(raw, Mapping):
            continue

        product = parse_product(
            dict(raw),
            company=company,
            source_file=source_file,
        )

        if stats is not None and product["barcode"] is None:
            stats["no_valid_gtin"] = stats.get("no_valid_gtin", 0) + 1

        yield product
