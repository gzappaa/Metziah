import pytest

from downloaders.runner import _accumulate, run_all_sources


def test_accumulate_list():
    downloaded = ["a"]

    _accumulate(downloaded, ["b", "c"])

    assert downloaded == ["a", "b", "c"]


def test_accumulate_single_value():
    downloaded = ["a"]

    _accumulate(downloaded, "b")

    assert downloaded == ["a", "b"]


def test_accumulate_none():
    downloaded = ["a"]

    _accumulate(downloaded, None)

    assert downloaded == ["a"]


@pytest.mark.asyncio
async def test_run_all_sources_runs_all_source_types(monkeypatch):
    def fake_get_sources(client):
        if client == "PublishedPricesClient":
            return [{
                "name": "PP",
                "credentials": {
                    "username": "user",
                    "password": "pass",
                },
            }]
        if client == "BinaProjectsClient":
            return [{
                "name": "Bina",
                "url": "https://bina",
            }]
        if client == "LaibcatalogClient":
            return [{
                "name": "Laib",
                "url": "https://laib",
                "chain_id": "123",
            }]
        return []

    monkeypatch.setattr(
        "downloaders.runner.get_publishing_sources",
        fake_get_sources,
    )
    monkeypatch.setattr("downloaders.runner.HTML_SOURCES", [])

    def fake_published(*args, **kwargs):
        return ["published"]

    def fake_bina(*args, **kwargs):
        return ["bina"]

    async def fake_laib(*args, **kwargs):
        return ["laib"]

    async def fake_html(*args, **kwargs):
        return ["html"]

    async def fake_carrefour(*args, **kwargs):
        return ["carrefour"]

    async def fake_mishnat(*args, **kwargs):
        return ["mishnat"]

    async def fake_wolt(*args, **kwargs):
        return ["wolt"]

    result = await run_all_sources(
        "Price",
        fake_published,
        fake_bina,
        fake_laib,
        fake_html,
        fake_carrefour,
        fake_mishnat,
        fake_wolt,
    )

    assert result == [
        "published",
        "bina",
        "laib",
        "carrefour",
        "mishnat",
        "wolt",
    ]


@pytest.mark.asyncio
async def test_run_all_sources_skips_publishedprices_without_credentials(
    monkeypatch,
):
    def fake_get_sources(client):
        if client == "PublishedPricesClient":
            return [{
                "name": "PP",
                "credentials": {},
            }]
        return []

    monkeypatch.setattr(
        "downloaders.runner.get_publishing_sources",
        fake_get_sources,
    )
    monkeypatch.setattr("downloaders.runner.HTML_SOURCES", [])

    called = False

    def fake_published(*args, **kwargs):
        nonlocal called
        called = True
        return ["published"]

    async def empty(*args, **kwargs):
        return []

    result = await run_all_sources(
        "Price",
        fake_published,
        empty,
        empty,
        empty,
        empty,
        empty,
        empty,
    )

    assert result == []
    assert called is False


@pytest.mark.asyncio
async def test_run_all_sources_skips_laib_without_chain_id(monkeypatch):
    def fake_get_sources(client):
        if client == "LaibcatalogClient":
            return [{
                "name": "Laib",
                "url": "https://laib",
            }]
        return []

    monkeypatch.setattr(
        "downloaders.runner.get_publishing_sources",
        fake_get_sources,
    )
    monkeypatch.setattr("downloaders.runner.HTML_SOURCES", [])

    called = False

    async def fake_laib(*args, **kwargs):
        nonlocal called
        called = True
        return ["laib"]

    async def empty(*args, **kwargs):
        return []

    result = await run_all_sources(
        "Price",
        lambda *args, **kwargs: [],
        lambda *args, **kwargs: [],
        fake_laib,
        empty,
        empty,
        empty,
        empty,
    )

    assert result == []
    assert called is False


@pytest.mark.asyncio
async def test_run_all_sources_continues_after_source_failure(monkeypatch):
    monkeypatch.setattr(
        "downloaders.runner.get_publishing_sources",
        lambda client: [],
    )
    monkeypatch.setattr("downloaders.runner.HTML_SOURCES", [])

    def fake_published(*args, **kwargs):
        return []

    def fake_bina(*args, **kwargs):
        return []

    async def fake_laib(*args, **kwargs):
        return []

    async def fake_html(*args, **kwargs):
        return []

    async def fake_carrefour(*args, **kwargs):
        raise RuntimeError("boom")

    async def fake_mishnat(*args, **kwargs):
        return ["mishnat"]

    async def fake_wolt(*args, **kwargs):
        return ["wolt"]

    result = await run_all_sources(
        "Price",
        fake_published,
        fake_bina,
        fake_laib,
        fake_html,
        fake_carrefour,
        fake_mishnat,
        fake_wolt,
    )

    assert result == ["mishnat", "wolt"]


@pytest.mark.asyncio
async def test_run_all_sources_clears_test_feeds(monkeypatch):
    monkeypatch.setattr(
        "downloaders.runner.get_publishing_sources",
        lambda client: [],
    )
    monkeypatch.setattr("downloaders.runner.HTML_SOURCES", [])

    called = False

    def fake_clear():
        nonlocal called
        called = True

    monkeypatch.setattr(
        "downloaders.runner.clear_test_feeds",
        fake_clear,
    )

    def empty_sync(*args, **kwargs):
        return []

    async def empty_async(*args, **kwargs):
        return []

    await run_all_sources(
        "Price",
        empty_sync,
        empty_sync,
        empty_async,
        empty_async,
        empty_async,
        empty_async,
        empty_async,
        test=True,
        clear_test_data=True,
    )

    assert called is True