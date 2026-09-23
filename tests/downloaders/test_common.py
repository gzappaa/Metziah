# tests/unit/test_downloaders_common.py

from pathlib import Path

import pytest

from clients.html_client import Candidate
from downloaders.common import (
    normalize_store_id,
    get_data_dir,
    _load_html_cache,
    clear_test_feeds,
    get_test_stores,
    filter_test_stores,
    filter_test_store_files,
    trim_for_test,
    filter_ignored_bina_stores,
    normalize_carrefour_listing,
    normalize_wolt_file_urls,
    normalize_mishnatyosef_listing,
    _page_fingerprint,
)


# ---------------------------------------------------------------------------
# normalize_store_id
# ---------------------------------------------------------------------------

def test_normalize_store_id_removes_leading_zeroes():
    assert normalize_store_id("041") == "41"
    assert normalize_store_id("006") == "6"


def test_normalize_store_id_keeps_non_numeric_text():
    assert normalize_store_id("TEST_STORE") == "TEST_STORE"


def test_normalize_store_id_handles_integer():
    assert normalize_store_id(41) == "41"


def test_normalize_store_id_handles_none():
    assert normalize_store_id(None) == "None"


# ---------------------------------------------------------------------------
# get_data_dir
# ---------------------------------------------------------------------------

def test_get_data_dir_returns_test_directory_in_test_mode():
    assert get_data_dir(True).name == "test_feeds"


def test_get_data_dir_returns_normal_directory_outside_test_mode():
    assert get_data_dir(False).name == "feeds"


# ---------------------------------------------------------------------------
# _load_html_cache
# ---------------------------------------------------------------------------

def test_load_html_cache_returns_candidates(tmp_path, monkeypatch):
    cache_dir = tmp_path / "data" / "cache"
    cache_dir.mkdir(parents=True)

    cache_file = cache_dir / "test.json"
    cache_file.write_text(
        """
        {
            "files": [
                {
                    "text": "Price file",
                    "url": "https://example.com/price.xml",
                    "filename": "price.xml",
                    "file_size": 123
                },
                {
                    "text": "Promo file",
                    "url": "https://example.com/promo.xml"
                }
            ]
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "downloaders.common.BASE_DIR",
        tmp_path,
    )

    result = _load_html_cache("test")

    assert len(result) == 2
    assert result[0].text == "Price file"
    assert result[0].href == "https://example.com/price.xml"
    assert result[0].filename == "price.xml"
    assert result[0].file_size == 123

    assert result[1].text == "Promo file"
    assert result[1].href == "https://example.com/promo.xml"
    assert result[1].filename is None
    assert result[1].file_size is None


def test_load_html_cache_skips_entries_without_url(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    (cache_dir / "test.json").write_text(
        """
        {
            "files": [
                {
                    "text": "No URL",
                    "filename": "missing.xml"
                }
            ]
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "downloaders.common.BASE_DIR",
        tmp_path,
    )

    assert _load_html_cache("test") == []


def test_load_html_cache_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "downloaders.common.BASE_DIR",
        tmp_path,
    )

    assert _load_html_cache("missing") == []


def test_load_html_cache_invalid_json_returns_empty(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    (cache_dir / "test.json").write_text(
        "not valid json",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "downloaders.common.BASE_DIR",
        tmp_path,
    )

    assert _load_html_cache("test") == []


# ---------------------------------------------------------------------------
# get_test_stores / filtering
# ---------------------------------------------------------------------------

def test_get_test_stores_finds_pricefull_store_pairs(tmp_path, monkeypatch):
    pricefull = (
        tmp_path
        / "chain1"
        / "041"
        / "pricesfull"
    )
    pricefull.mkdir(parents=True)

    (pricefull / "PriceFull.xml").touch()

    monkeypatch.setattr(
        "downloaders.common.BASE_DIR",
        tmp_path.parent,
    )

    # BASE_DIR / data / test_feeds
    test_feeds = tmp_path.parent / "data" / "test_feeds"

    # Recreate under the actual expected location.
    target = test_feeds / "chain1" / "041" / "pricesfull"
    target.mkdir(parents=True)

    (target / "PriceFull.xml").touch()

    result = get_test_stores()

    assert ("chain1", "041") in result


def test_filter_test_stores_keeps_only_known_test_stores(
    monkeypatch,
):
    monkeypatch.setattr(
        "downloaders.common.get_test_stores",
        lambda: {
            ("chain1", "001"),
        },
    )

    latest_files = {
        "a": {
            "chain_id": "chain1",
            "store_id": "001",
        },
        "b": {
            "chain_id": "chain1",
            "store_id": "002",
        },
    }

    result = filter_test_stores(latest_files)

    assert result == {
        "a": latest_files["a"],
    }


def test_filter_test_store_files_keeps_only_known_test_stores(
    monkeypatch,
):
    monkeypatch.setattr(
        "downloaders.common.get_test_stores",
        lambda: {
            ("chain1", "001"),
        },
    )

    files = [
        {"chain_id": "chain1", "store_id": "001"},
        {"chain_id": "chain1", "store_id": "002"},
    ]

    assert filter_test_store_files(files) == [files[0]]


# ---------------------------------------------------------------------------
# trim_for_test
# ---------------------------------------------------------------------------

def test_trim_for_test_limits_mapping():
    latest = {
        "a": 1,
        "b": 2,
        "c": 3,
    }

    assert trim_for_test(latest, "PriceFull", limit=2) == {
        "a": 1,
        "b": 2,
    }


def test_trim_for_test_returns_same_mapping_when_under_limit():
    latest = {
        "a": 1,
        "b": 2,
    }

    assert trim_for_test(latest, "PriceFull", limit=5) == latest


# ---------------------------------------------------------------------------
# filter_ignored_bina_stores
# ---------------------------------------------------------------------------

def test_filter_ignored_bina_stores_removes_ignored_store():
    files = [
        {"filename": "ignored.xml"},
        {"filename": "normal.xml"},
    ]

    def parse_filename(filename):
        if filename == "ignored.xml":
            return {
                "chain_id": "7290058156016",
                "sub_chain_id": "017",
                "store_id": "396",
            }

        return {
            "chain_id": "123",
            "sub_chain_id": "001",
            "store_id": "001",
        }

    result = filter_ignored_bina_stores(
        files,
        "filename",
        parse_filename,
    )

    assert result == [
        {"filename": "normal.xml"},
    ]


def test_filter_ignored_bina_stores_skips_empty_filename():
    files = [
        {"filename": ""},
        {"filename": None},
        {"filename": "normal.xml"},
    ]

    def parse_filename(filename):
        return {
            "chain_id": "123",
            "sub_chain_id": "001",
            "store_id": "001",
        }

    assert filter_ignored_bina_stores(
        files,
        "filename",
        parse_filename,
    ) == [
        {"filename": "normal.xml"},
    ]


def test_filter_ignored_bina_stores_skips_invalid_filename():
    files = [
        {"filename": "bad.xml"},
        {"filename": "good.xml"},
    ]

    def parse_filename(filename):
        if filename == "bad.xml":
            raise ValueError("invalid filename")

        return {
            "chain_id": "123",
            "sub_chain_id": "001",
            "store_id": "001",
        }

    assert filter_ignored_bina_stores(
        files,
        "filename",
        parse_filename,
    ) == [
        {"filename": "good.xml"},
    ]


# ---------------------------------------------------------------------------
# Carrefour
# ---------------------------------------------------------------------------

def test_normalize_carrefour_listing_accepts_strings_and_dicts():
    files = [
        "Price.xml",
        {"name": "Promo.xml"},
        {"fileName": "PriceFull.xml"},
        {"Name": "PromoFull.xml"},
    ]

    assert normalize_carrefour_listing(files) == [
        {"filename": "Price.xml"},
        {"filename": "Promo.xml"},
        {"filename": "PriceFull.xml"},
        {"filename": "PromoFull.xml"},
    ]


def test_normalize_carrefour_listing_skips_dict_without_filename():
    files = [
        {"name": None},
        {"fileName": ""},
        {"Name": None},
    ]

    assert normalize_carrefour_listing(files) == []


# ---------------------------------------------------------------------------
# Wolt
# ---------------------------------------------------------------------------

def test_normalize_wolt_file_urls_extracts_filename_and_url():
    urls = [
        "https://example.com/files/Price001.xml",
        "https://example.com/files/Promo001.xml",
    ]

    normalized, hrefs = normalize_wolt_file_urls(urls)

    assert normalized == [
        {"filename": "Price001.xml"},
        {"filename": "Promo001.xml"},
    ]

    assert hrefs == {
        "Price001.xml": "https://example.com/files/Price001.xml",
        "Promo001.xml": "https://example.com/files/Promo001.xml",
    }


def test_normalize_wolt_file_urls_skips_url_without_filename():
    urls = [
        "https://example.com/files/",
        "https://example.com/files/Price.xml",
    ]

    normalized, hrefs = normalize_wolt_file_urls(urls)

    assert normalized == [
        {"filename": "Price.xml"},
    ]

    assert hrefs == {
        "Price.xml": "https://example.com/files/Price.xml",
    }


# ---------------------------------------------------------------------------
# Mishnat Yosef
# ---------------------------------------------------------------------------

def test_normalize_mishnatyosef_listing_filters_file_type():
    files = [
        {
            "type": "Price",
            "name": "Price.xml",
            "url": "https://example.com/price.xml",
        },
        {
            "type": "Promo",
            "name": "Promo.xml",
            "url": "https://example.com/promo.xml",
        },
    ]

    normalized, hrefs = normalize_mishnatyosef_listing(
        files,
        "Price",
    )

    assert normalized == [
        {"filename": "Price.xml"},
    ]

    assert hrefs == {
        "Price.xml": "https://example.com/price.xml",
    }


def test_normalize_mishnatyosef_listing_skips_missing_name_or_url():
    files = [
        {
            "type": "Price",
            "name": None,
            "url": "https://example.com/price.xml",
        },
        {
            "type": "Price",
            "name": "Price2.xml",
            "url": None,
        },
    ]

    normalized, hrefs = normalize_mishnatyosef_listing(
        files,
        "Price",
    )

    assert normalized == []
    assert hrefs == {}


# ---------------------------------------------------------------------------
# HTML page fingerprint
# ---------------------------------------------------------------------------

def test_page_fingerprint_uses_filename_href_and_text():
    candidates = [
        Candidate(
            text="Price",
            href="https://example.com/price.xml",
            filename="price.xml",
            file_size=123,
        ),
        Candidate(
            text="Promo",
            href="https://example.com/promo.xml",
            filename="promo.xml",
            file_size=456,
        ),
    ]

    assert _page_fingerprint(candidates) == (
        (
            "price.xml",
            "https://example.com/price.xml",
            "Price",
        ),
        (
            "promo.xml",
            "https://example.com/promo.xml",
            "Promo",
        ),
    )


def test_page_fingerprint_same_content_produces_same_fingerprint():
    candidates_a = [
        Candidate(
            text="Price",
            href="https://example.com/price.xml",
            filename="price.xml",
        )
    ]

    candidates_b = [
        Candidate(
            text="Price",
            href="https://example.com/price.xml",
            filename="price.xml",
        )
    ]

    assert _page_fingerprint(candidates_a) == _page_fingerprint(
        candidates_b
    )