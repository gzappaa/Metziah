from unittest.mock import AsyncMock, Mock, call

import httpx
import pytest

from clients.laibcatalog import LaibcatalogClient


@pytest.fixture
def client():
    return LaibcatalogClient(
        "7290661400001"
    )


def make_response(
    *,
    content=b"",
    json_data=None,
    status_code=200,
    url="https://laibcatalog.co.il",
):
    response = Mock(spec=httpx.Response)

    response.content = content
    response.status_code = status_code
    response.url = httpx.URL(url)

    if json_data is not None:
        response.json.return_value = json_data

    return response


def setup_async_client(
    monkeypatch,
    get,
):
    async_client = Mock()

    async_client.__aenter__ = AsyncMock(
        return_value=async_client
    )
    async_client.__aexit__ = AsyncMock(
        return_value=None
    )
    async_client.get = get

    async_client_class = Mock(
        return_value=async_client
    )

    monkeypatch.setattr(
        "clients.laibcatalog.httpx.AsyncClient",
        async_client_class,
    )

    return async_client, async_client_class


def test_init(client):
    assert client.chain_id == "7290661400001"
    assert client.source_url == (
        "https://laibcatalog.co.il"
    )


@pytest.mark.asyncio
async def test_get_with_retry_success(
    client,
    monkeypatch,
):
    response = make_response(
        status_code=200,
    )

    response.raise_for_status = Mock()

    get = AsyncMock(
        return_value=response
    )

    async_client, async_client_class = (
        setup_async_client(
            monkeypatch,
            get,
        )
    )

    result = await client._get_with_retry(
        "https://example.com/test",
    )

    assert result is response

    async_client_class.assert_called_once_with(
        timeout=client.TIMEOUT
    )

    get.assert_awaited_once_with(
        "https://example.com/test",
        params=None,
    )

    response.raise_for_status.assert_called_once()

    async_client.__aenter__.assert_awaited_once()
    async_client.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_with_retry_passes_params(
    client,
    monkeypatch,
):
    response = make_response()

    response.raise_for_status = Mock()

    get = AsyncMock(
        return_value=response
    )

    setup_async_client(
        monkeypatch,
        get,
    )

    params = {
        "edi": "7290661400001",
        "branchNumber": "123",
    }

    result = await client._get_with_retry(
        "https://example.com/test",
        params=params,
    )

    assert result is response

    get.assert_awaited_once_with(
        "https://example.com/test",
        params=params,
    )


@pytest.mark.asyncio
async def test_get_with_retry_retries_timeout(
    client,
    monkeypatch,
):
    response = make_response()

    response.raise_for_status = Mock()

    get = AsyncMock(
        side_effect=[
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            response,
        ]
    )

    setup_async_client(
        monkeypatch,
        get,
    )

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.laibcatalog.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/test",
    )

    assert result is response

    assert get.await_count == 3

    assert sleep.await_args_list == [
        call(2),
        call(4),
    ]


@pytest.mark.asyncio
async def test_get_with_retry_retries_connect_error(
    client,
    monkeypatch,
):
    response = make_response()

    response.raise_for_status = Mock()

    get = AsyncMock(
        side_effect=[
            httpx.ConnectError(
                "connection failed"
            ),
            response,
        ]
    )

    setup_async_client(
        monkeypatch,
        get,
    )

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.laibcatalog.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/test",
    )

    assert result is response

    assert get.await_count == 2

    sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_get_with_retry_raises_after_all_retries(
    client,
    monkeypatch,
):
    error = httpx.TimeoutException(
        "timeout"
    )

    get = AsyncMock(
        side_effect=error
    )

    setup_async_client(
        monkeypatch,
        get,
    )

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.laibcatalog.asyncio.sleep",
        sleep,
    )

    with pytest.raises(
        httpx.TimeoutException,
        match="timeout",
    ):
        await client._get_with_retry(
            "https://example.com/test",
        )

    assert get.await_count == 3

    assert sleep.await_args_list == [
        call(2),
        call(4),
    ]


@pytest.mark.asyncio
async def test_get_with_retry_does_not_retry_http_error(
    client,
    monkeypatch,
):
    response = make_response(
        status_code=404,
    )

    error = httpx.HTTPStatusError(
        "404",
        request=Mock(),
        response=response,
    )

    response.raise_for_status = Mock(
        side_effect=error
    )

    get = AsyncMock(
        return_value=response
    )

    setup_async_client(
        monkeypatch,
        get,
    )

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.laibcatalog.asyncio.sleep",
        sleep,
    )

    with pytest.raises(
        httpx.HTTPStatusError,
        match="404",
    ):
        await client._get_with_retry(
            "https://example.com/test",
        )

    get.assert_awaited_once_with(
        "https://example.com/test",
        params=None,
    )

    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_files_without_branch(
    client,
    monkeypatch,
):
    expected = [
        {
            "FileNm": "price.xml",
            "FileType": 2,
        },
        {
            "FileNm": "pricefull.xml",
            "FileType": 4,
        },
    ]

    response = make_response(
        json_data=expected,
    )

    get = AsyncMock(
        return_value=response
    )

    get_with_retry = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get_with_retry,
    )

    result = await client.get_files()

    assert result == expected

    get_with_retry.assert_awaited_once_with(
        "https://laibcatalog.co.il"
        "/webapi/api/getfiles",
        params={
            "edi": "7290661400001",
        },
    )


@pytest.mark.asyncio
async def test_get_files_with_branch(
    client,
    monkeypatch,
):
    expected = [
        {
            "FileNm": "price.xml",
            "Branch": "123",
        }
    ]

    response = make_response(
        json_data=expected,
    )

    get_with_retry = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get_with_retry,
    )

    result = await client.get_files(
        branch_number="123"
    )

    assert result == expected

    get_with_retry.assert_awaited_once_with(
        "https://laibcatalog.co.il"
        "/webapi/api/getfiles",
        params={
            "edi": "7290661400001",
            "branchNumber": "123",
        },
    )


@pytest.mark.parametrize(
    "branch_number",
    [
        None,
        "",
        0,
    ],
)
@pytest.mark.asyncio
async def test_get_files_omits_falsy_branch_number(
    client,
    monkeypatch,
    branch_number,
):
    response = make_response(
        json_data=[],
    )

    get_with_retry = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get_with_retry,
    )

    result = await client.get_files(
        branch_number=branch_number
    )

    assert result == []

    get_with_retry.assert_awaited_once_with(
        "https://laibcatalog.co.il"
        "/webapi/api/getfiles",
        params={
            "edi": "7290661400001",
        },
    )


def test_build_download_url(client):
    result = client.build_download_url(
        "price.xml"
    )

    assert result == (
        "https://laibcatalog.co.il"
        "/webapi/7290661400001/price.xml"
    )


def test_build_download_url_with_path(
    client,
):
    result = client.build_download_url(
        "folder/price.xml"
    )

    assert result == (
        "https://laibcatalog.co.il"
        "/webapi/7290661400001/"
        "folder/price.xml"
    )


@pytest.mark.asyncio
async def test_download_file(
    client,
    monkeypatch,
):
    response = make_response(
        content=b"file contents",
    )

    get_with_retry = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get_with_retry,
    )

    url = (
        "https://laibcatalog.co.il"
        "/webapi/7290661400001/price.xml"
    )

    result = await client.download_file(
        url
    )

    assert result == b"file contents"

    get_with_retry.assert_awaited_once_with(
        url
    )


@pytest.mark.asyncio
async def test_check(
    client,
    monkeypatch,
):
    files = [
        {
            "FileNm": "price.xml",
            "FileType": 2,
        },
        {
            "FileNm": "pricefull.xml",
            "FileType": 4,
        },
    ]

    get_files = AsyncMock(
        return_value=files
    )

    monkeypatch.setattr(
        client,
        "get_files",
        get_files,
    )

    result = await client.check()

    assert result == {
        "chain_id": "7290661400001",
        "url": "https://laibcatalog.co.il",
        "files": files,
    }

    get_files.assert_awaited_once_with()