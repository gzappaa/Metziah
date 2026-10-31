"""
Type 2: product data served as JSON by an API call.

There is no DOM marker. The scraper detects this type by watching the
network traffic of the example product page: a JSON response that contains
the example item code, from a request that also contains that code, means
the site exposes its product data through an API. The scraper then replays
that request with the code swapped, and hands the JSON to parse().

Nothing here is tied to a site. The product is located by searching the
JSON for the item code, and fields are picked with generic key/format
heuristics. Everything else is kept untouched under "details".
"""

import re
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit

from scrapers.product_pages.common import clean, unique


# Common keys a product name is stored under, in priority order.
NAME_KEYS = ("name", "title", "product_name", "item_name", "productName", "itemName")

IMAGE_URL = re.compile(
    r"\.(?:jpe?g|png|webp|gif|avif|svg)(?:[?#].*)?$",
    re.IGNORECASE,
)


def _children(node):
    if isinstance(node, dict):
        return node.values()
    if isinstance(node, list):
        return node
    return ()


def find_product(payload, item_code):
    """Return the outermost dict that holds the item code as a value, or None."""
    code = str(item_code)
    queue = deque([payload])

    while queue:
        node = queue.popleft()

        if isinstance(node, dict):
            for value in node.values():
                if not isinstance(value, (dict, list)) and str(value) == code:
                    return node

        queue.extend(_children(node))

    return None


def _strings(node):
    """Yield every string anywhere inside a JSON value."""
    stack = [node]

    while stack:
        current = stack.pop()

        if isinstance(current, str):
            yield current
        else:
            stack.extend(_children(current))


def _image_path(value):
    """Extract the path from an image URL or relative image path."""
    path = urlsplit(value).path
    return path if IMAGE_URL.search(path) else None


def _image_base_url(page_url):
    """Build the image CDN base URL from the product page URL."""
    parts = urlsplit(page_url)
    hostname = parts.hostname or ""

    if hostname.startswith("www."):
        hostname = "img." + hostname[4:]

    netloc = hostname

    if parts.port:
        netloc = f"{hostname}:{parts.port}"

    return urlunsplit((parts.scheme, netloc, "/", "", ""))


def matches(payload, item_code):
    """Detection hook: is this JSON response a product payload for the code?"""
    return find_product(payload, item_code) is not None


def parse(payload, item_code, base_url):
    """Return a dict with page_code, name, images, and the full product record."""
    product = find_product(payload, item_code)

    if product is None:
        return None

    name = None

    for key in NAME_KEYS:
        value = product.get(key)

        if isinstance(value, str) and value.strip():
            name = clean(value)
            break

    # Extract only product images, excluding unrelated images such as banners.
    image_data = product.get("images", {})

    image_base_url = _image_base_url(base_url)

    images = unique(
        [
            urljoin(image_base_url, path)
            for text in _strings(image_data)
            if (path := _image_path(text))
        ]
    )

    return {
        "page_code": str(item_code),
        "name": name,
        "images": images,
        "details": product,
    }