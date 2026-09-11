# utils/file_tracking/file_size.py

import logging
import re

import requests

logger = logging.getLogger(__name__)


def get_file_size(
    url: str,
    slow: bool = False,
) -> int | None:
    if not slow:
        return None

    try:
        response = requests.head(
            url,
            timeout=10,
            allow_redirects=True,
        )
        response.raise_for_status()

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length is None:
            return None

        return int(content_length)

    except Exception:
        logger.exception(
            "Failed getting file size from %s",
            url,
        )
        return None


def get_file_size_get(
    url: str,
) -> int | None:
    try:
        response = requests.get(
            url,
            timeout=10,
            stream=True,
        )
        response.raise_for_status()

        content_length = response.headers.get(
            "Content-Length"
        )

        response.close()

        if content_length is None:
            return None

        return int(content_length)

    except Exception:
        logger.exception(
            "Failed getting file size from %s",
            url,
        )
        return None


def parse_file_size(value) -> int | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    match = re.fullmatch(
        r"\s*([\d.]+)\s*(B|KB|MB|GB)\s*",
        str(value),
        re.IGNORECASE,
    )

    if not match:
        return None

    number = float(match.group(1))
    unit = match.group(2).upper()

    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
    }

    return int(number * multipliers[unit])