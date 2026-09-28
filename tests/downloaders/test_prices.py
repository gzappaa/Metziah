from datetime import date

import pytest

from downloaders.prices import (
    download_price_publishedprices,
    download_price_binaprojects,
    download_price_laibcatalog,
    download_price_carrefour,
    download_price_html,
    download_price_mishnatyosef,
    download_price_wolt,
    download_prices,
)


TODAY = date.today()


def _filename(
    chain="7290661400001",
    store="001",
    time="120000",
):
    return f"Price{chain}-001-{store}-{TODAY:%Y%m%d}-{time}.gz"


def _price_file(filename=None):
    filename = filename or _filename()

    return {
        "filename": filename,
        "chain_id": "7290661400001",
        "store_id": "1",
        "file_date": TODAY,
        "path": "some/path",
    }


def _async_path(tmp_path, filename):
    return tmp_path / filename


def test_download_price_publishedprices_login_failure(monkeypatch):
    class FakeClient:
        BASE_URL = "https://example.com"

        def __init__(self, username, password):
            pass

        def login(self):
            raise Exception("login failed")

    monkeypatch.setattr(
        "downloaders.prices.PublishedPricesClient",
        FakeClient,
    )

    result = download_price_publishedprices(
        "Test",
        "user",
        "password",
    )

    assert result == []


def test_download_price_publishedprices(monkeypatch, tmp_path):
    latest = _price_file()

    class FakeClient:
        BASE_URL = "https://example.com"

        def __init__(self, username, password):
            pass

        def login(self):
            pass

    monkeypatch.setattr(
        "downloaders.prices.PublishedPricesClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.prices.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.prices.list_publishedprices_entries_recursive",
        lambda client: [],
    )
    monkeypatch.setattr(
        "downloaders.prices.find_delta_files",
        lambda *args, **kwargs: [latest],
    )

    saved = []

    def fake_save(**kwargs):
        saved.append(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.prices.save_delta_file",
        fake_save,
    )

    result = download_price_publishedprices(
        "Test",
        "user",
        "password",
    )

    assert result == [tmp_path / latest["filename"]]
    assert saved[0]["chain_id"] == latest["chain_id"]
    assert saved[0]["store_id"] == latest["store_id"]
    assert saved[0]["filename"] == latest["filename"]
    assert saved[0]["subfolder"] == "prices"


def test_download_price_binaprojects(monkeypatch, tmp_path):
    latest = _price_file()

    class FakeClient:
        def __init__(self, url):
            pass

        def get_hok_files(self, file_type):
            return []

    monkeypatch.setattr(
        "downloaders.prices.BinaProjectsClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.prices.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.prices.find_delta_files",
        lambda *args, **kwargs: [latest],
    )
    monkeypatch.setattr(
        "downloaders.prices.filter_ignored_bina_stores",
        lambda files, *args: files,
    )

    monkeypatch.setattr(
        "downloaders.prices.save_delta_file",
        lambda **kwargs: tmp_path / kwargs["filename"],
    )

    result = download_price_binaprojects(
        "Test",
        "https://example.com",
    )

    assert result == [tmp_path / latest["filename"]]


@pytest.mark.asyncio
async def test_download_price_laibcatalog(monkeypatch, tmp_path):
    latest = _price_file()

    class FakeClient:
        def __init__(self, chain_id):
            pass

        async def get_files(self):
            return []

        def build_download_url(self, filename):
            return f"https://example.com/{filename}"

        async def download_file(self, url):
            return b"data"

    monkeypatch.setattr(
        "downloaders.prices.LaibcatalogClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.prices.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.prices.find_delta_files",
        lambda *args, **kwargs: [latest],
    )
    monkeypatch.setattr(
        "downloaders.prices.keep_latest_file_per_store",
        lambda files: files,
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.prices.save_delta_file_async",
        fake_save,
    )

    result = await download_price_laibcatalog(
        "Test",
        "https://example.com",
        "7290661400001",
    )

    assert result == [tmp_path / latest["filename"]]


@pytest.mark.asyncio
async def test_download_price_carrefour(monkeypatch, tmp_path):
    latest = _price_file()

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
        "downloaders.prices.CarrefourClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.prices.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.prices.normalize_carrefour_listing",
        lambda files: [],
    )
    monkeypatch.setattr(
        "downloaders.prices.find_delta_files",
        lambda *args, **kwargs: [latest],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.prices.save_delta_file_async",
        fake_save,
    )

    result = await download_price_carrefour()

    assert result == [tmp_path / latest["filename"]]


@pytest.mark.asyncio
async def test_download_price_html(monkeypatch, tmp_path):
    latest = _price_file()

    source = {
        "name": "Test HTML",
        "listing": {
            "base_url": "https://example.com",
        },
        "extraction_mode": "table",
        "filename_source": "text",
    }

    class Candidate:
        filename = latest["filename"]
        href = "https://example.com/file.gz"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "downloaders.prices.HtmlFileLinkClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.prices.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.prices._load_html_cache",
        lambda name: [Candidate()],
    )
    monkeypatch.setattr(
        "downloaders.prices.parse_filename",
        lambda filename: {"file_type": "Price"},
    )
    monkeypatch.setattr(
        "downloaders.prices.find_delta_files",
        lambda *args, **kwargs: [latest],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.prices.save_delta_file_async",
        fake_save,
    )

    result = await download_price_html(source)

    assert result == [tmp_path / latest["filename"]]


@pytest.mark.asyncio
async def test_download_price_mishnatyosef(monkeypatch, tmp_path):
    latest = _price_file()

    class FakeClient:
        async def get_files(self):
            return []

        async def download_file(self, href):
            return b"data"

    monkeypatch.setattr(
        "downloaders.prices.MishnatYosefClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.prices.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.prices.normalize_mishnatyosef_listing",
        lambda files, file_type: (
            [{"filename": latest["filename"]}],
            {latest["filename"]: "https://example.com/file.gz"},
        ),
    )
    monkeypatch.setattr(
        "downloaders.prices.find_delta_files",
        lambda *args, **kwargs: [latest],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.prices.save_delta_file_async",
        fake_save,
    )

    result = await download_price_mishnatyosef()

    assert result == [tmp_path / latest["filename"]]


@pytest.mark.asyncio
async def test_download_price_wolt(monkeypatch, tmp_path):
    latest = _price_file()

    class FakeClient:
        async def get_date_pages(self):
            return ["https://example.com/date"]

        async def get_files(self, date_page):
            return []

        async def download_file(self, href):
            return b"data"

    monkeypatch.setattr(
        "downloaders.prices.WoltClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.prices.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.prices.normalize_wolt_file_urls",
        lambda urls: (
            [{"filename": latest["filename"]}],
            {latest["filename"]: "https://example.com/file.gz"},
        ),
    )
    monkeypatch.setattr(
        "downloaders.prices.find_delta_files",
        lambda *args, **kwargs: [latest],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.prices.save_delta_file_async",
        fake_save,
    )

    result = await download_price_wolt()

    assert result == [tmp_path / latest["filename"]]


@pytest.mark.asyncio
async def test_download_prices(monkeypatch):
    expected = ["a", "b"]

    async def fake_run_all_sources(*args, **kwargs):
        return expected

    monkeypatch.setattr(
        "downloaders.prices.run_all_sources",
        fake_run_all_sources,
    )

    result = await download_prices(test=True)

    assert result == expected