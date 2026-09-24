from datetime import datetime
from pathlib import Path

import pytest

from downloaders.stores import (
    find_latest_matching_file,
    find_latest_stores_file,
    find_latest_stores_file_binaprojects,
    find_latest_stores_file_laibcatalog,
    get_storage_path,
)


def test_find_latest_matching_file_returns_latest():
    files = [
        {
            "filename": "Stores7290661400001-20260921-120000.gz",
        },
        {
            "filename": "Stores7290661400001-20260923-120000.gz",
        },
        {
            "filename": "Stores7290661400001-20260922-120000.gz",
        },
    ]

    result = find_latest_matching_file(
        files,
        filename_key="filename",
    )

    assert result["filename"] == (
        "Stores7290661400001-20260923-120000.gz"
    )
    assert result["chain_id"] == "7290661400001"
    assert result["timestamp"] == datetime(2026, 9, 23)


def test_find_latest_matching_file_ignores_invalid_files():
    files = [
        {"filename": "invalid.xml"},
        {"filename": ""},
        {},
    ]

    result = find_latest_matching_file(
        files,
        filename_key="filename",
    )

    assert result is None


def test_find_latest_matching_file_ignores_invalid_date():
    files = [
        {
            "filename": "Stores7290661400001-20261399-120000.gz",
        },
    ]

    result = find_latest_matching_file(
        files,
        filename_key="filename",
    )

    assert result is None


def test_find_latest_matching_file_uses_date_key():
    files = [
        {
            "FileNm": "Stores7290661400001-20260923-100000.gz",
            "DateFile": "10:00 22/09/2026",
        },
        {
            "FileNm": "Stores7290661400001-20260922-120000.gz",
            "DateFile": "12:00 23/09/2026",
        },
    ]

    result = find_latest_matching_file(
        files,
        filename_key="FileNm",
        date_key="DateFile",
        date_format="%H:%M %d/%m/%Y",
    )

    assert result["filename"] == (
        "Stores7290661400001-20260922-120000.gz"
    )
    assert result["timestamp"] == datetime(2026, 9, 23, 12, 0)


def test_find_latest_matching_file_ignores_invalid_date_key():
    files = [
        {
            "FileNm": "Stores7290661400001-20260923-120000.gz",
            "DateFile": "invalid",
        },
    ]

    result = find_latest_matching_file(
        files,
        filename_key="FileNm",
        date_key="DateFile",
        date_format="%H:%M %d/%m/%Y",
    )

    assert result is None


def test_find_latest_stores_file():
    response = {
        "aaData": [
            {
                "fname": (
                    "Stores7290661400001-20260921-120000.gz"
                ),
            },
            {
                "fname": (
                    "Stores7290661400001-20260923-120000.gz"
                ),
            },
        ]
    }

    result = find_latest_stores_file(response)

    assert result["filename"] == (
        "Stores7290661400001-20260923-120000.gz"
    )
    assert result["chain_id"] == "7290661400001"
    assert result["url"].endswith(
        "/file/d/Stores7290661400001-20260923-120000.gz"
    )


def test_find_latest_stores_file_nested_path():
    response = {
        "aaData": [
            {
                "fname": (
                    "Stores7290661400001-20260923-120000.gz"
                ),
            },
        ]
    }

    result = find_latest_stores_file(
        response,
        cd="/folder/subfolder",
    )

    assert result["url"].endswith(
        "/file/d/folder/subfolder/"
        "Stores7290661400001-20260923-120000.gz"
    )


def test_find_latest_stores_file_returns_none():
    response = {
        "aaData": [
            {"fname": "Price7290661400001-20260923-120000.gz"},
        ]
    }

    assert find_latest_stores_file(response) is None


def test_find_latest_stores_file_binaprojects():
    files = [
        {
            "FileNm": "Stores7290661400001-20260922-120000.gz",
            "DateFile": "12:00 22/09/2026",
        },
        {
            "FileNm": "Stores7290661400001-20260923-120000.gz",
            "DateFile": "12:00 23/09/2026",
        },
    ]

    result = find_latest_stores_file_binaprojects(files)

    assert result["filename"] == (
        "Stores7290661400001-20260923-120000.gz"
    )


def test_find_latest_stores_file_laibcatalog():
    files = [
        {
            "fileName": (
                "Stores7290661400001-20260922-120000.gz"
            ),
        },
        {
            "fileName": (
                "Stores7290661400001-20260923-120000.gz"
            ),
        },
    ]

    result = find_latest_stores_file_laibcatalog(files)

    assert result["filename"] == (
        "Stores7290661400001-20260923-120000.gz"
    )


def test_get_storage_path():
    result = get_storage_path(
        "7290661400001",
        Path("/data/feeds"),
    )

    assert result == Path(
        "/data/feeds/7290661400001/stores"
    )