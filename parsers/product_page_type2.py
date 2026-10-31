
"""
parsers/product_page_type2.py

Parse type_2 product page dumps ( style: item_code / details / gs ...)
into the SAME flat record schema as parsers/product_json.py.

Import usage:
    from parsers.product_page_type2 import iter_products, parse_product
"""

import html
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterator

from database.records import is_valid_gtin

HE = "1"
BASE_URL = "https://www.rami-levy.co.il"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_LESS_THAN_RE = re.compile(r"^\s*(?:פחות\s*מ[-־\s]*|<)")


# ----------------------------------------------------------------- helpers
def _text(value: Any) -> str | None:
    """Stripped string or None (empty / whitespace-only -> None)."""
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    return value or None


def _dict(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _html_to_text(value: Any) -> str:
    s = html.unescape(_text(value) or "")
    s = s.replace("\xa0", " ")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", s)
    s = re.sub(_TAG_RE, " ", s)
    s = _WS_RE.sub(" ", s)
    s = re.sub(r" *\n *", "\n", s)
    return s.strip() or None


def _abs_url(url: Any) -> str | None:
    u = _text(url)
    if not u:
        return None
    return BASE_URL + u if u.startswith("/") else u


def _to_number(value: Any) -> int | float | str | None:
    """'6.3' -> 6.3, '182' -> 182, anything unparseable stays as the string."""
    s = _text(value)
    if s is None:
        return None
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return s
    return int(f) if f.is_integer() else f


def _ref(d: Any) -> tuple[Any, str | None]:
    """(id, name) of a {name,id,sort,slug} object (department/group/subGroup)."""
    d = _dict(d)
    return d.get("id"), _text(d.get("name"))


# ----------------------------------------------------------------- barcode
def _resolve_barcode(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Return (barcode, local_barcode).

    The chain's own internal codes (12xxxxxxxxxxx) are not real GTINs, so a
    code only goes to `barcode` if it passes is_valid_gtin; otherwise it is
    kept in `local_barcode` so nothing is lost.
    """
    details = _dict(raw.get("details"))
    code = (
        _text(details.get("barcode"))
        or _text(raw.get("item_code"))
        or _text(raw.get("page_code"))
    )
    if code is None:
        return None, None
    if code.endswith(".0"):  # number serialised as float
        code = code[:-2]
    if is_valid_gtin(code):
        return code, None
    return None, code


# ------------------------------------------------------------- categories
def _category_path(details: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the normalized department > group > subGroup hierarchy."""
    levels = (
        (details.get("department"), details.get("department_id")),
        (details.get("group"), details.get("group_id")),
        (details.get("subGroup"), details.get("sub_group_id")),
    )

    path: list[dict[str, Any]] = []

    for obj, fallback_id in levels:
        category_id, name = _ref(obj)
        if category_id is None:
            category_id = fallback_id

        # A category without a name is not useful in the category path.
        if not name:
            continue

        path.append({
            "id": category_id,
            "name_he": name,
        })

    return path


# ---------------------------------------------------------------- images
def _collect_images(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_images = {
        _text(url).rsplit("/", 1)[-1]: _text(url)
        for url in _list(raw.get("images"))
        if _text(url)
    }

    details = _dict(raw.get("details"))
    image_details = _dict(details.get("images"))

    images = []
    seen = set()

    for image_type in ("original", "trim", "small", "transparent"):
        relative_url = _text(image_details.get(image_type))
        if not relative_url:
            continue

        filename = relative_url.rsplit("/", 1)[-1]
        url = raw_images.get(filename)

        if not url or url in seen:
            continue

        seen.add(url)
        images.append({
            "url": url,
            "type": image_type,
            "is_default": image_type == "original",
        })

    for item in _list(image_details.get("gallery")):
        if not isinstance(item, Mapping):
            continue

        relative_url = _text(item.get("url"))
        filename = relative_url.rsplit("/", 1)[-1]
        url = raw_images.get(filename)

        if not url or url in seen:
            continue

        seen.add(url)
        images.append({**item, "url": url})

    return images

# ------------------------------------------------------------- nutrition
def _nutrition(gs: Mapping[str, Any]) -> dict[str, Any] | None:
    """
    -> {"sizes":  [{"id", "names": {"1": basis}}],
        "values": [{"id", "names": {"1": nutrient},
                    "sizeValues": [{"sizeId", "unitOfMeasure": {"names": {"1": unit}},
                                    "value", "valueLessThan"}]}]}
    (same shape as the Carrefour / Tiv Taam dumps)
    """
    sizes: dict[Any, dict[str, Any]] = {}
    values: list[dict[str, Any]] = []

    for nutrient in _list(gs.get("Nutritional_Values")):
        if not isinstance(nutrient, Mapping):
            continue

        label = _text(nutrient.get("label"))
        if not label:
            continue

        size_values = []

        for field in _list(nutrient.get("fields")):
            if not isinstance(field, Mapping):
                continue

            size_id = _to_int(field.get("col_code"))
            basis = _text(field.get("col_label"))

            if size_id not in sizes:
                sizes[size_id] = {"id": size_id, "names": {HE: basis}}

            text = _text(field.get("text")) or ""

            size_values.append({
                "sizeId": size_id,
                "unitOfMeasure": {
                    "names": {HE: _text(field.get("UOM")) or ""}
                },
                "value": _to_number(field.get("value")),
                "valueLessThan": bool(_LESS_THAN_RE.match(text)),
            })

        if size_values:
            values.append({
                "id": _to_int(nutrient.get("code")),
                "names": {HE: label},
                "sizeValues": size_values,
            })

    if not values:
        return None

    return {"sizes": list(sizes.values()), "values": values}


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- keywords
def _keywords(gs: Mapping[str, Any], barcode_like: set[str]) -> list[str]:
    out: list[str] = []

    for tag in _list(gs.get("Search_Tags")):
        t = _text(tag)
        if t and t not in barcode_like and t not in out:
            out.append(t)

    return out


# ------------------------------------------------------------ description
def _description_he(details: Mapping[str, Any]) -> str | None:
    for key in ("full_desc", "short_desc"):
        d = _html_to_text(details.get(key))
        if d:
            return d

    # Fallback: "תיאור מוצר" property blocks.
    parts = []

    for prop in _list(details.get("properties")):
        if (
            isinstance(prop, Mapping)
            and _text(prop.get("property_parent_name")) == "תיאור מוצר"
        ):
            text = _html_to_text(prop.get("value"))
            if text:
                parts.append(text)

    return "\n\n".join(parts) or None


# ------------------------------------------------------------------ main
def parse_product(raw: dict[str, Any]) -> dict[str, Any]:
    details = _dict(raw.get("details"))
    gs = _dict(details.get("gs"))

    barcode, local_barcode = _resolve_barcode(raw)
    images = _collect_images(raw)
    default_image = next((i for i in images if i["is_default"]), None)

    dept_id, dept_name = _ref(details.get("department"))
    if dept_id is None:
        dept_id = details.get("department_id")

    group_id, group_name = _ref(details.get("group"))
    if group_id is None:
        group_id = details.get("group_id")

    path = _category_path(details)
    nutrition_values = _nutrition(gs)

    local_name = _text(raw.get("name")) or _text(details.get("name"))
    name_he = local_name or _text(gs.get("name")) or _text(gs.get("short_name"))

    barcode_like = {
        x for x in (barcode, local_barcode, _text(raw.get("item_code")) if raw else None)
        if x
    }

    return {
        # --- identity ---
        "barcode": barcode,
        "local_barcode": local_barcode,
        "product_id": details.get("id"),
        "id": details.get("id"),
        "retailer_id": None,
        "supplier_id": None,

        # --- name ---
        "local_name": local_name,
        "name_he": name_he,
        "name_en": None,
        "name_ru": None,

        # --- brand ---
        "brand_id": None,
        "brand_name_he": _text(gs.get("BrandName")),
        "brand_name_en": None,
        "brand_name_ru": None,

        # --- search keywords ---
        "search_keywords": _keywords(gs, barcode_like),
        "family_search_keywords": [],

        # --- department ---
        "department_id": dept_id,
        "department_external_id": None,
        "department_name": dept_name,

        # --- family + categories ---
        "family_id": group_id,
        "family_name_he": group_name,
        "family_name_en": None,
        "category_ids": [c["id"] for c in path if c["id"] is not None],
        "category_path_ids": [c["id"] for c in path],
        "category_path_he": [c["name_he"] for c in path],
        "category_path_en": [None for _ in path],
        "categories_paths": (
            [[
                {
                    "id": c["id"],
                    "names": {HE: c["name_he"]},
                    "keywords": [],
                }
                for c in path
            ]]
            if path
            else []
        ),

        # --- content ---
        "ingredients_he": _text(gs.get("Ingredient_Sequence_and_Name")),
        "ingredients_en": None,
        "ingredients_ru": None,
        "description_he": _description_he(details),
        "description_en": _text(gs.get("Product_Description_English")),
        "description_ru": None,

        # --- nutrition ---
        "nutrition_facts": None,
        "nutrition_values": nutrition_values,

        # --- images ---
        "main_image_url": default_image["url"] if default_image else None,
        "images": images,
        "nutrition_image_url": None,
    }


def iter_products(
    path: Path,
    stats: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed products; optionally count non-GTIN (local-only) codes."""
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
        raise ValueError(f"unrecognised type_2 layout (top-level: {keys})")

    for raw in products:
        if not isinstance(raw, Mapping):
            continue

        product = parse_product(dict(raw))

        if stats is not None and product["barcode"] is None:
            stats["no_valid_gtin"] = stats.get("no_valid_gtin", 0) + 1

        yield product
