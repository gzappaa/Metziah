from datetime import date
from pathlib import Path

import pytest

from downloaders.pricesfull import (
    download_pricefull_publishedprices,
    download_pricefull_binaprojects,
    download_pricefull_laibcatalog,
    download_pricefull_carrefour,
    download_pricefull_html,
    download_pricefull_mishnatyosef,
    download_pricefull_wolt,
)


TODAY = date.today()


def _filename(chain="7290661400001", store="001", time="120000"):
    return (
        f"PriceFull{chain}-001-{store}-"
        f"{TODAY:%Y%m%d}-{time}.gz"
    )


def _latest(filename=None):
    filename = filename or _filename()
    return {
        "filename": filename,
        "chain_id": "7290661400001",
        "store_id": "1",
        "file_date": TODAY,
    }


def test_download_pricefull_publishedprices(monkeypatch, tmp_path):
    class FakeClient:
        BASE_URL = "https://example.com"

        def __init__(self, username, password):
            pass

        def login(self):
            pass

        def download_file(self, url):
            return b"data"

    monkeypatch.setattr(
        "downloaders.pricesfull.PublishedPricesClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.list_publishedprices_entries_recursive",
        lambda client: [],
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("chain", "store"): _latest()
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.save_full_file",
        lambda **kwargs: Path(tmp_path / kwargs["filename"]),
    )

    result = download_pricefull_publishedprices(
        "Test",
        "user",
        "pass",
    )

    assert result == [tmp_path / _filename()]


def test_download_pricefull_publishedprices_login_failure(monkeypatch):
    class FakeClient:
        def __init__(self, username, password):
            pass

        def login(self):
            raise RuntimeError("login failed")

    monkeypatch.setattr(
        "downloaders.pricesfull.PublishedPricesClient",
        FakeClient,
    )

    result = download_pricefull_publishedprices(
        "Test",
        "user",
        "pass",
    )

    assert result == []


def test_download_pricefull_binaprojects(monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self, url):
            pass

        def get_hok_files(self, file_type):
            assert file_type == 4
            return []

        def download_file(self, filename):
            return b"data"

    monkeypatch.setattr(
        "downloaders.pricesfull.BinaProjectsClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.filter_ignored_bina_stores",
        lambda files, *args: files,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("chain", "store"): _latest()
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.save_full_file",
        lambda **kwargs: Path(tmp_path / kwargs["filename"]),
    )

    result = download_pricefull_binaprojects("Test", "url")

    assert result == [tmp_path / _filename()]


@pytest.mark.asyncio
async def test_download_pricefull_laibcatalog(monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self, chain_id):
            pass

        async def get_files(self):
            return []

        def build_download_url(self, filename):
            return "https://example.com/" + filename

        async def download_file(self, url):
            return b"data"

    monkeypatch.setattr(
        "downloaders.pricesfull.LaibcatalogClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("chain", "store"): _latest()
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.save_full_file_async",
        lambda **kwargs: _async_path(tmp_path, kwargs["filename"]),
    )

    result = await download_pricefull_laibcatalog(
        "Test",
        "url",
        "7290661400001",
    )

    assert result == [tmp_path / _filename()]


@pytest.mark.asyncio
async def test_download_pricefull_carrefour(monkeypatch, tmp_path):
    class FakeClient:
        base_url = "https://example.com"

        async def get_files(self):
            return {
                "path": "/files",
                "files": [],
            }

        async def download_file(self, url):
            return b"data"

    monkeypatch.setattr(
        "downloaders.pricesfull.CarrefourClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.normalize_carrefour_listing",
        lambda files: files,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("chain", "store"): _latest()
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.save_full_file_async",
        lambda **kwargs: _async_path(tmp_path, kwargs["filename"]),
    )

    result = await download_pricefull_carrefour()

    assert result == [tmp_path / _filename()]


@pytest.mark.asyncio
async def test_download_pricefull_html(monkeypatch, tmp_path):
    class Candidate:
        def __init__(self):
            self.filename = _filename()
            self.href = "https://example.com/file.gz"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "downloaders.pricesfull.HtmlFileLinkClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull._load_html_cache",
        lambda name: [Candidate()],
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.parse_filename",
        lambda filename: {
            "file_type": "PriceFull",
            "chain_id": "7290661400001",
            "store_id": "1",
            "file_date": TODAY,
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("chain", "store"): _latest()
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.save_full_file_async",
        lambda **kwargs: _async_path(tmp_path, kwargs["filename"]),
    )

    result = await download_pricefull_html(
        {
            "name": "Test",
            "listing": {"base_url": "https://example.com"},
            "extraction_mode": "test",
            "filename_source": "test",
        }
    )

    assert result == [tmp_path / _filename()]


@pytest.mark.asyncio
async def test_download_pricefull_mishnatyosef(monkeypatch, tmp_path):
    class FakeClient:
        async def get_files(self):
            return []

        async def download_file(self, url):
            return b"data"

    monkeypatch.setattr(
        "downloaders.pricesfull.MishnatYosefClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.normalize_mishnatyosef_listing",
        lambda *args: ([{"filename": _filename()}], {
            _filename(): "https://example.com/file.gz"
        }),
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("chain", "store"): _latest()
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.save_full_file_async",
        lambda **kwargs: _async_path(tmp_path, kwargs["filename"]),
    )

    result = await download_pricefull_mishnatyosef()

    assert result == [tmp_path / _filename()]


@pytest.mark.asyncio
async def test_download_pricefull_wolt(monkeypatch, tmp_path):
    class FakeClient:
        async def get_date_pages(self):
            return ["2026-09-23"]

        async def get_files(self, page):
            return ["https://example.com/" + _filename()]

        async def download_file(self, url):
            return b"data"

    monkeypatch.setattr(
        "downloaders.pricesfull.WoltClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.normalize_wolt_file_urls",
        lambda urls: (
            [{"filename": _filename()}],
            {_filename(): "https://example.com/" + _filename()},
        ),
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("chain", "store"): _latest()
        },
    )
    monkeypatch.setattr(
        "downloaders.pricesfull.save_full_file_async",
        lambda **kwargs: _async_path(tmp_path, kwargs["filename"]),
    )

    result = await download_pricefull_wolt()

    assert result == [tmp_path / _filename()]


async def _async_path(tmp_path, filename):
    return tmp_path / filename