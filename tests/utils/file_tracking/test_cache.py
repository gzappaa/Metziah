import json

import pytest

from clients.html_client import Candidate
from utils.file_tracking import cache


def test_html_cache_path():
    result = cache._html_cache_path("shufersal")

    assert result == cache.CACHE_DIR / "shufersal.json"


def test_save_html_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    candidates = [
        Candidate(
            text="PriceFull file",
            href="https://example.com/file.xml",
            filename="PriceFull123.xml",
            file_size=1234,
        ),
        Candidate(
            text="Price file",
            href="https://example.com/file2.xml",
            filename="Price123.xml",
            file_size=5678,
        ),
        Candidate(
            text="Missing filename",
            href="https://example.com/file3.xml",
            filename=None,
            file_size=100,
        ),
    ]

    cache._save_html_cache("test_source", candidates)

    cache_path = tmp_path / "test_source.json"

    assert cache_path.is_file()

    with cache_path.open(encoding="utf-8") as file:
        saved = json.load(file)

    assert saved == {
        "files": [
            {
                "text": "PriceFull file",
                "url": "https://example.com/file.xml",
                "filename": "PriceFull123.xml",
                "file_size": 1234,
            },
            {
                "text": "Price file",
                "url": "https://example.com/file2.xml",
                "filename": "Price123.xml",
                "file_size": 5678,
            },
        ]
    }


def test_load_html_cache_returns_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    cache_path = tmp_path / "test_source.json"

    data = {
        "files": [
            {
                "text": "Price file",
                "url": "https://example.com/file.xml",
                "filename": "Price.xml",
                "file_size": 123,
            }
        ]
    }

    with cache_path.open("w", encoding="utf-8") as file:
        json.dump(data, file)

    result = cache.load_html_cache("test_source")

    assert result == data["files"]


def test_load_html_cache_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    result = cache.load_html_cache("does_not_exist")

    assert result == []


def test_load_html_cache_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    cache_path = tmp_path / "broken.json"
    cache_path.write_text(
        "{ invalid json",
        encoding="utf-8",
    )

    result = cache.load_html_cache("broken")

    assert result == []


@pytest.mark.asyncio
async def test_fetch_and_cache_source(monkeypatch):
    candidates = [
        Candidate(
            text="Price file",
            href="https://example.com/file.xml",
            filename="Price.xml",
            file_size=123,
        )
    ]

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def fake_get_all_html_candidates(client, listing):
        assert client.kwargs["name"] == "test_source"
        assert client.kwargs["base_url"] == "https://example.com"
        assert listing == {
            "base_url": "https://example.com",
            "page": 1,
        }

        return candidates

    saved = {}

    def fake_save_html_cache(source_name, candidates_arg):
        saved["source_name"] = source_name
        saved["candidates"] = candidates_arg

    monkeypatch.setattr(
        cache,
        "HtmlFileLinkClient",
        FakeClient,
    )
    monkeypatch.setattr(
        cache,
        "get_all_html_candidates",
        fake_get_all_html_candidates,
    )
    monkeypatch.setattr(
        cache,
        "_save_html_cache",
        fake_save_html_cache,
    )

    source = {
        "name": "test_source",
        "listing": {
            "base_url": "https://example.com",
            "page": 1,
        },
        "extraction_mode": "table",
        "filename_source": "text",
    }

    name, result = await cache._fetch_and_cache_source(source)

    assert name == "test_source"
    assert result == candidates
    assert saved["source_name"] == "test_source"
    assert saved["candidates"] == candidates


@pytest.mark.asyncio
async def test_refresh_html_caches(monkeypatch):
    candidates = [
        Candidate(
            text="Price file",
            href="https://example.com/file.xml",
            filename="Price.xml",
            file_size=123,
        )
    ]

    async def fake_fetch(source):
        return source["name"], candidates

    monkeypatch.setattr(
        cache,
        "_fetch_and_cache_source",
        fake_fetch,
    )

    sources = [
        {
            "name": "source_a",
        },
        {
            "name": "source_b",
        },
    ]

    result = await cache.refresh_html_caches(sources)

    assert result == {
        "source_a": candidates,
        "source_b": candidates,
    }


@pytest.mark.asyncio
async def test_refresh_html_caches_handles_source_failure(monkeypatch):
    async def fake_fetch(source):
        if source["name"] == "broken":
            raise RuntimeError("boom")

        return source["name"], []

    monkeypatch.setattr(
        cache,
        "_fetch_and_cache_source",
        fake_fetch,
    )

    sources = [
        {
            "name": "broken",
        },
        {
            "name": "working",
        },
    ]

    result = await cache.refresh_html_caches(sources)

    assert result == {
        "broken": [],
        "working": [],
    }