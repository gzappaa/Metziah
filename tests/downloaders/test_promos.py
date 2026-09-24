from datetime import date

import pytest

from downloaders.promos import (
    download_promo_publishedprices,
    download_promo_binaprojects,
    download_promo_laibcatalog,
    download_promo_carrefour,
    download_promo_html,
    download_promo_mishnatyosef,
    download_promo_wolt,
    download_promos,
)


TODAY = date.today()


def _filename(
    chain="7290661400001",
    store="001",
    time="120000",
):
    return f"Promo{chain}-001-{store}-{TODAY:%Y%m%d}-{time}.gz"


def _promo_file(filename=None):
    filename = filename or _filename()

    return {
        "filename": filename,
        "chain_id": "7290661400001",
        "store_id": "1",
        "file_date": TODAY,
        "path": "some/path",
    }


def test_download_promo_publishedprices_login_failure(monkeypatch):
    class FakeClient:
        BASE_URL = "https://example.com"

        def __init__(self, username, password):
            pass

        def login(self):
            raise Exception("login failed")

    monkeypatch.setattr(
        "downloaders.promos.PublishedPricesClient",
        FakeClient,
    )

    result = download_promo_publishedprices(
        "Test",
        "user",
        "password",
    )

    assert result == []


def test_download_promo_publishedprices(monkeypatch, tmp_path):
    promo_file = _promo_file()

    class FakeClient:
        BASE_URL = "https://example.com"

        def __init__(self, username, password):
            pass

        def login(self):
            pass

    monkeypatch.setattr(
        "downloaders.promos.PublishedPricesClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promos.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promos.list_publishedprices_entries_recursive",
        lambda client: [],
    )
    monkeypatch.setattr(
        "downloaders.promos.find_delta_files",
        lambda *args, **kwargs: [promo_file],
    )

    saved = []

    def fake_save(**kwargs):
        saved.append(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promos.save_delta_file",
        fake_save,
    )

    result = download_promo_publishedprices(
        "Test",
        "user",
        "password",
    )

    assert result == [tmp_path / promo_file["filename"]]
    assert saved[0]["chain_id"] == promo_file["chain_id"]
    assert saved[0]["store_id"] == promo_file["store_id"]
    assert saved[0]["filename"] == promo_file["filename"]
    assert saved[0]["subfolder"] == "promos"


def test_download_promo_binaprojects(monkeypatch, tmp_path):
    promo_file = _promo_file()

    class FakeClient:
        def __init__(self, url):
            pass

        def get_hok_files(self, file_type):
            assert file_type == 3
            return []

    monkeypatch.setattr(
        "downloaders.promos.BinaProjectsClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promos.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promos.filter_ignored_bina_stores",
        lambda files, *args: files,
    )
    monkeypatch.setattr(
        "downloaders.promos.find_delta_files",
        lambda *args, **kwargs: [promo_file],
    )
    monkeypatch.setattr(
        "downloaders.promos.save_delta_file",
        lambda **kwargs: tmp_path / kwargs["filename"],
    )

    result = download_promo_binaprojects(
        "Test",
        "https://example.com",
    )

    assert result == [tmp_path / promo_file["filename"]]


@pytest.mark.asyncio
async def test_download_promo_laibcatalog(monkeypatch, tmp_path):
    promo_file = _promo_file()

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
        "downloaders.promos.LaibcatalogClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promos.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promos.find_delta_files",
        lambda *args, **kwargs: [promo_file],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promos.save_delta_file_async",
        fake_save,
    )

    result = await download_promo_laibcatalog(
        "Test",
        "https://example.com",
        "7290661400001",
    )

    assert result == [tmp_path / promo_file["filename"]]


@pytest.mark.asyncio
async def test_download_promo_carrefour(monkeypatch, tmp_path):
    promo_file = _promo_file()

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
        "downloaders.promos.CarrefourClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promos.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promos.normalize_carrefour_listing",
        lambda files: [],
    )
    monkeypatch.setattr(
        "downloaders.promos.find_delta_files",
        lambda *args, **kwargs: [promo_file],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promos.save_delta_file_async",
        fake_save,
    )

    result = await download_promo_carrefour()

    assert result == [tmp_path / promo_file["filename"]]


@pytest.mark.asyncio
async def test_download_promo_html(monkeypatch, tmp_path):
    promo_file = _promo_file()

    source = {
        "name": "Test HTML",
        "listing": {
            "base_url": "https://example.com",
        },
        "extraction_mode": "table",
        "filename_source": "text",
    }

    class Candidate:
        filename = promo_file["filename"]
        href = "https://example.com/file.gz"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "downloaders.promos.HtmlFileLinkClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promos.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promos._load_html_cache",
        lambda name: [Candidate()],
    )
    monkeypatch.setattr(
        "downloaders.promos.parse_filename",
        lambda filename: {"file_type": "Promo"},
    )
    monkeypatch.setattr(
        "downloaders.promos.find_delta_files",
        lambda *args, **kwargs: [promo_file],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promos.save_delta_file_async",
        fake_save,
    )

    result = await download_promo_html(source)

    assert result == [tmp_path / promo_file["filename"]]


@pytest.mark.asyncio
async def test_download_promo_mishnatyosef(monkeypatch, tmp_path):
    promo_file = _promo_file()

    class FakeClient:
        async def get_files(self):
            return []

        async def download_file(self, href):
            return b"data"

    monkeypatch.setattr(
        "downloaders.promos.MishnatYosefClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promos.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promos.normalize_mishnatyosef_listing",
        lambda files, file_type: (
            [{"filename": promo_file["filename"]}],
            {
                promo_file["filename"]:
                    "https://example.com/file.gz"
            },
        ),
    )
    monkeypatch.setattr(
        "downloaders.promos.find_delta_files",
        lambda *args, **kwargs: [promo_file],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promos.save_delta_file_async",
        fake_save,
    )

    result = await download_promo_mishnatyosef()

    assert result == [tmp_path / promo_file["filename"]]


@pytest.mark.asyncio
async def test_download_promo_wolt(monkeypatch, tmp_path):
    promo_file = _promo_file()

    class FakeClient:
        async def get_date_pages(self):
            return ["https://example.com/date"]

        async def get_files(self, date_page):
            return []

        async def download_file(self, href):
            return b"data"

    monkeypatch.setattr(
        "downloaders.promos.WoltClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "downloaders.promos.get_data_dir",
        lambda test: tmp_path,
    )
    monkeypatch.setattr(
        "downloaders.promos.normalize_wolt_file_urls",
        lambda urls: (
            [{"filename": promo_file["filename"]}],
            {
                promo_file["filename"]:
                    "https://example.com/file.gz"
            },
        ),
    )
    monkeypatch.setattr(
        "downloaders.promos.find_delta_files",
        lambda *args, **kwargs: [promo_file],
    )

    async def fake_save(**kwargs):
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(
        "downloaders.promos.save_delta_file_async",
        fake_save,
    )

    result = await download_promo_wolt()

    assert result == [tmp_path / promo_file["filename"]]


@pytest.mark.asyncio
async def test_download_promos(monkeypatch):
    expected = ["a", "b"]

    async def fake_run_all_sources(*args, **kwargs):
        return expected

    monkeypatch.setattr(
        "downloaders.promos.run_all_sources",
        fake_run_all_sources,
    )

    result = await download_promos(test=True)

    assert result == expected