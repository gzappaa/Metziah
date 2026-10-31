"""utils/brand_resolution.py
Shared brand-resolution logic for shopper-facing store brands.
Matches configured brands against store names with Hebrew/whitespace normalization
and boundary-aware pattern matching.
"""
import re
import unicodedata


def normalize_text_for_matching(text: str) -> str:
    """Normalize text for boundary and character comparisons."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    # Hebrew punctuation normalization (geresh / gershayim to standard quotes/apostrophes)
    text = text.replace("״", '"').replace("׳", "'").replace("־", "-")
    # Normalize AM-PM variations
    text = re.sub(r"(?i)\bam[\s\-:]*pm\b", "am-pm", text)
    # Normalize consecutive whitespaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def resolve_shopper_brand(
    store_name: str | None,
    chain_brands: list[str] | None,
    chain_fallback_name: str | None = None,
) -> str:
    """
    Resolve the shopper-facing retail brand for a store.

    1. Read the chain's configured brands array.
    2. Normalize whitespace and Hebrew text consistently.
    3. Match configured brand names against the store name using careful,
       boundary-aware matching (longer brands first to handle overlaps like 'יש חסד' vs 'יש').
    4. If a configured shopper-facing brand matches, use it for display.
    5. If none matches, fall back to the chain's own public brand/name.
    """
    fallback = (chain_fallback_name or "").strip()
    if not store_name:
        return fallback

    normalized_store = normalize_text_for_matching(store_name)
    if not normalized_store or not chain_brands:
        return fallback

    # Filter out empty or whitespace-only brands
    valid_brands = [b.strip() for b in chain_brands if b and b.strip()]
    if not valid_brands:
        return fallback

    # Sort candidates by length in descending order to prioritize specific/longer matches
    # (e.g., 'יש חסד' before 'יש', 'מחסני מזון' before 'מחסני')
    sorted_brands = sorted(valid_brands, key=lambda b: len(b), reverse=True)

    for brand in sorted_brands:
        norm_brand = normalize_text_for_matching(brand)
        if not norm_brand:
            continue

        # Boundary-aware regex pattern:
        # (?<![\w\u0590-\u05fe]) ensures not preceded by a Hebrew or alphanumeric letter
        # (?![\w\u0590-\u05fe]) ensures not followed by a Hebrew or alphanumeric letter
        escaped = re.escape(norm_brand)
        pattern = rf"(?<![\w\u0590-\u05fe]){escaped}(?![\w\u0590-\u05fe])"

        if re.search(pattern, normalized_store, flags=re.IGNORECASE):
            return brand

    return fallback
