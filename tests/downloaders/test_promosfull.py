from datetime import date

import pytest

from downloaders.promosfull import (
    download_promofull_publishedprices,
    download_promofull_binaprojects,
    download_promofull_laibcatalog,
    download_promofull_carrefour,
    download_promofull_html,
    download_promofull_mishnatyosef,
    download_promofull_wolt,
    download_promofull,
)


TODAY = date.today()


def _filename(
    chain="7290661400001",
    store="001",
    time="120000",
):
    return f"PromoFull{chain}-001-{store}-{TODAY:%Y%m%d}-{time}.gz"


def _full_file(filename=None):
    filename = filename or _filename()

    return {
        "filename": filename,
        "chain_id": "7290661400001",
        "store_id": "1",
        "file_date": TODAY,
        "path": "some/path",
    }


def test_download_promofull_publishedprices_login_failure(monkeypatch):
    class FakeClient:
        BASE_URL = "https://example.com"

        def __init__(self, username, password):
            pass

        def login(self):
            raise Exception("login failed")

    monkeypatch.setattr(
        "downloaders.promosfull.PublishedPricesClient",
        FakeClient,
    )

    result = download_promofull_publishedprices(
        "Test",
        "user",
        "password",
    )

    assert result == []


def test_download_promofull_publishedprices(monkeypatch, tmp_path):
    full_file = _full_file()

    class FakeClient:
        BASE_URL = "https://example.com"

        def __init__(self, username, password):
            pass

        def login(self):
            pass

    monkeypatch.setattr(
        "downloaders.promosfull.PublishedPricesClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.list_publishedprices_entries_recursive",
        lambda client: [],
    )
    monkeypatch.setattr(
        "downloaders.promosfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("7290661400001", "1"): full_file
        },
    )

    saved = []

    def fake_save(**kwargs):
        saved.append(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promosfull.save_full_file",
        fake_save,
    )

    result = download_promofull_publishedprices(
        "Test",
        "user",
        "password",
    )

    assert result == [tmp_path / full_file["filename"]]
    assert saved[0]["chain_id"] == full_file["chain_id"]
    assert saved[0]["store_id"] == full_file["store_id"]
    assert saved[0]["filename"] == full_file["filename"]
    assert saved[0]["file_type"] == "PromoFull"
    assert saved[0]["subfolder"] == "promosfull"


def test_download_promofull_binaprojects(monkeypatch, tmp_path):
    full_file = _full_file()

    class FakeClient:
        def __init__(self, url):
            pass

        def get_hok_files(self, file_type):
            assert file_type == 5
            return []

    monkeypatch.setattr(
        "downloaders.promosfull.BinaProjectsClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.filter_ignored_bina_stores",
        lambda files, *args: files,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("7290661400001", "1"): full_file
        },
    )
    monkeypatch.setattr(
        "downloaders.promosfull.save_full_file",
        lambda **kwargs: tmp_path / kwargs["filename"],
    )

    result = download_promofull_binaprojects(
        "Test",
        "https://example.com",
    )

    assert result == [tmp_path / full_file["filename"]]


@pytest.mark.asyncio
async def test_download_promofull_laibcatalog(monkeypatch, tmp_path):
    full_file = _full_file()

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
        "downloaders.promosfull.LaibcatalogClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("7290661400001", "1"): full_file
        },
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promosfull.save_full_file_async",
        fake_save,
    )

    result = await download_promofull_laibcatalog(
        "Test",
        "https://example.com",
        "7290661400001",
    )

    assert result == [tmp_path / full_file["filename"]]


@pytest.mark.asyncio
async def test_download_promofull_carrefour(monkeypatch, tmp_path):
    full_file = _full_file()

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
        "downloaders.promosfull.CarrefourClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.normalize_carrefour_listing",
        lambda files: [],
    )
    monkeypatch.setattr(
        "downloaders.promosfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("7290661400001", "1"): full_file
        },
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promosfull.save_full_file_async",
        fake_save,
    )

    result = await download_promofull_carrefour()

    assert result == [tmp_path / full_file["filename"]]


@pytest.mark.asyncio
async def test_download_promofull_html(monkeypatch, tmp_path):
    full_file = _full_file()

    source = {
        "name": "Test HTML",
        "listing": {
            "base_url": "https://example.com",
        },
        "extraction_mode": "table",
        "filename_source": "text",
    }

    class Candidate:
        filename = full_file["filename"]
        href = "https://example.com/file.gz"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "downloaders.promosfull.HtmlFileLinkClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promosfull._load_html_cache",
        lambda name: [Candidate()],
    )
    monkeypatch.setattr(
        "downloaders.promosfull.parse_filename",
        lambda filename: {"file_type": "PromoFull"},
    )
    monkeypatch.setattr(
        "downloaders.promosfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("7290661400001", "1"): full_file
        },
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promosfull.save_full_file_async",
        fake_save,
    )

    result = await download_promofull_html(source)

    assert result == [tmp_path / full_file["filename"]]


@pytest.mark.asyncio
async def test_download_promofull_mishnatyosef(monkeypatch, tmp_path):
    full_file = _full_file()

    class FakeClient:
        async def get_files(self):
            return []

        async def download_file(self, href):
            return b"data"

    monkeypatch.setattr(
        "downloaders.promosfull.MishnatYosefClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.normalize_mishnatyosef_listing",
        lambda files, file_type: (
            [{"filename": full_file["filename"]}],
            {
                full_file["filename"]:
                    "https://example.com/file.gz"
            },
        ),
    )
    monkeypatch.setattr(
        "downloaders.promosfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("7290661400001", "1"): full_file
        },
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promosfull.save_full_file_async",
        fake_save,
    )

    result = await download_promofull_mishnatyosef()

    assert result == [tmp_path / full_file["filename"]]


@pytest.mark.asyncio
async def test_download_promofull_wolt(monkeypatch, tmp_path):
    full_file = _full_file()

    class FakeClient:
        async def get_date_pages(self):
            return ["https://example.com/date"]

        async def get_files(self, date_page):
            return []

        async def download_file(self, href):
            return b"data"

    monkeypatch.setattr(
        "downloaders.promosfull.WoltClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promosfull.normalize_wolt_file_urls",
        lambda urls: (
            [{"filename": full_file["filename"]}],
            {
                full_file["filename"]:
                    "https://example.com/file.gz"
            },
        ),
    )
    monkeypatch.setattr(
        "downloaders.promosfull.find_latest_full_files_per_store",
        lambda *args, **kwargs: {
            ("7290661400001", "1"): full_file
        },
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promosfull.save_full_file_async",
        fake_save,
    )

    result = await download_promofull_wolt()

    assert result == [tmp_path / full_file["filename"]]


@pytest.mark.asyncio
async def test_download_promofull(monkeypatch):
    expected = ["a", "b"]

    async def fake_run_all_sources(*args, **kwargs):
        return expected

    monkeypatch.setattr(
        "downloaders.promosfull.run_all_sources",
        fake_run_all_sources,
    )

    result = await download_promofull(test=True)

    assert result == expected