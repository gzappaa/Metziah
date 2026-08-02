# tests/clients/test_laibcatalog.py
import httpx
import pytest
import respx

from clients.laibcatalog import LaibcatalogClient


CHAIN_ID = "7290661400001"
GETFILES_URL = "https://laibcatalog.co.il/webapi/api/getfiles"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    async def fake_sleep(seconds):
        pass
    monkeypatch.setattr("clients.laibcatalog.asyncio.sleep", fake_sleep)


@pytest.fixture
def client():
    return LaibcatalogClient(CHAIN_ID)


# ---- build_download_url: pure logic, no mocking ----

def test_build_download_url(client):
    url = client.build_download_url("PriceFull7290661400001-001-001.gz")
    assert url == (
        "https://laibcatalog.co.il"
        "/webapi/7290661400001/PriceFull7290661400001-001-001.gz"
    )


# ---- get_files ----

@pytest.mark.asyncio
@respx.mock
async def test_get_files_sends_edi_param(client):
    route = respx.get(GETFILES_URL).mock(
        return_value=httpx.Response(200, json={"files": []})
    )

    await client.get_files()

    assert route.called
    request = route.calls[0].request
    assert request.url.params["edi"] == CHAIN_ID
    assert "branchNumber" not in request.url.params


@pytest.mark.asyncio
@respx.mock
async def test_get_files_includes_branch_number_when_given(client):
    route = respx.get(GETFILES_URL).mock(
        return_value=httpx.Response(200, json={"files": []})
    )

    await client.get_files(branch_number="020")

    request = route.calls[0].request
    assert request.url.params["branchNumber"] == "020"


@pytest.mark.asyncio
@respx.mock
async def test_get_files_returns_parsed_json(client):
    respx.get(GETFILES_URL).mock(
        return_value=httpx.Response(200, json={"files": [{"name": "x.gz"}]})
    )

    result = await client.get_files()

    assert result == {"files": [{"name": "x.gz"}]}


@pytest.mark.asyncio
@respx.mock
async def test_get_files_raises_on_http_error(client):
    respx.get(GETFILES_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_files()


@pytest.mark.asyncio
@respx.mock
async def test_get_files_raises_on_network_error(client):
    respx.get(GETFILES_URL).mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(httpx.ConnectError):
        await client.get_files()


@pytest.mark.asyncio
@respx.mock
async def test_get_files_raises_on_malformed_json(client):
    # 200 status but a body that isn't valid JSON (e.g. an HTML error page)
    respx.get(GETFILES_URL).mock(
        return_value=httpx.Response(200, content=b"<html>not json</html>")
    )

    with pytest.raises(ValueError):  # httpx raises json.JSONDecodeError, a ValueError subclass
        await client.get_files()


# ---- download_file ----

@pytest.mark.asyncio
@respx.mock
async def test_download_file_returns_bytes(client):
    url = "https://laibcatalog.co.il/webapi/7290661400001/Price.gz"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"gzipbytes"))

    content = await client.download_file(url)

    assert content == b"gzipbytes"


@pytest.mark.asyncio
@respx.mock
async def test_download_file_raises_on_http_error(client):
    url = "https://laibcatalog.co.il/webapi/7290661400001/Price.gz"
    respx.get(url).mock(return_value=httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        await client.download_file(url)


@pytest.mark.asyncio
@respx.mock
async def test_download_file_raises_on_network_error(client):
    url = "https://laibcatalog.co.il/webapi/7290661400001/Price.gz"
    respx.get(url).mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(httpx.ConnectError):
        await client.download_file(url)

# ---- retry behavior ----

@pytest.mark.asyncio
@respx.mock
async def test_get_files_retries_then_succeeds(client):
    route = respx.get(GETFILES_URL).mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"files": []}),
        ]
    )

    result = await client.get_files()

    assert result == {"files": []}
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_get_files_gives_up_after_max_retries(client):
    route = respx.get(GETFILES_URL).mock(
        side_effect=httpx.ConnectError("boom")
    )

    with pytest.raises(httpx.ConnectError):
        await client.get_files()

    assert route.call_count == client.MAX_RETRIES


@pytest.mark.asyncio
@respx.mock
async def test_get_files_does_not_retry_on_http_status_error(client):
    route = respx.get(GETFILES_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_files()

    assert route.call_count == 1  # no retry on 4xx/5xx


@pytest.mark.asyncio
@respx.mock
async def test_get_files_retries_on_timeout_too(client):
    route = respx.get(GETFILES_URL).mock(
        side_effect=[
            httpx.ReadTimeout("timed out"),
            httpx.Response(200, json={"files": []}),
        ]
    )

    result = await client.get_files()

    assert result == {"files": []}
    assert route.call_count == 2


# same shape for download_file

@pytest.mark.asyncio
@respx.mock
async def test_download_file_retries_then_succeeds(client):
    url = "https://laibcatalog.co.il/webapi/7290661400001/Price.gz"
    route = respx.get(url).mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, content=b"gzipbytes"),
        ]
    )

    content = await client.download_file(url)

    assert content == b"gzipbytes"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_download_file_does_not_retry_on_http_status_error(client):
    url = "https://laibcatalog.co.il/webapi/7290661400001/Price.gz"
    route = respx.get(url).mock(return_value=httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        await client.download_file(url)

    assert route.call_count == 1