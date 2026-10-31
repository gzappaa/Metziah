"""Shared helpers for scrapers/product_pages/type_*.py modules."""

import re


def clean(text):
    """Collapse all whitespace runs into single spaces."""
    return " ".join(text.split())


def split_list(text):
    """Split comma-, newline-, and HTML-break-separated text into a clean list."""
    parts = (
        clean(part)
        for part in re.split(r",|\n|<br\s*/?>", text, flags=re.IGNORECASE)
    )
    return [part for part in parts if part]


def unique(items):
    return list(dict.fromkeys(item for item in items if item))


def add_field(fields, label, value):
    """Labels can repeat (e.g. two kashrut lines), so values are lists."""
    if label and value:
        fields.setdefault(label, []).append(value)