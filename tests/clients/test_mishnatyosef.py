import pytest
import httpx
from unittest.mock import AsyncMock, Mock, call

from clients.mishnatyosef import MishnatYosefClient


@pytest.fixture
def client():
    return MishnatYosefClient()


def make_response(
    *,
    status_code=200,
    url="https://example.com",
    json_data=None,
    content=b"",
):
    response = Mock()
    response.status_code = status_code
    response.url = url
    response.content = content
    response.text = content.decode("utf-8", errors="ignore")
    response.json.return_value = json_data

    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP error",
            request=Mock(),
            response=response,
        )
    else:
        response.raise_for_status.return_value = None

    return response


def setup_async_client(monkeypatch, responses):
    mock_client = AsyncMock()

    mock_client.get.side_effect = responses

    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = mock_client
    context_manager.__aexit__.return_value = None

    async_client_constructor = Mock(
        return_value=context_manager
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        async_client_constructor,
    )

    return mock_client


def test_init():
    client = MishnatYosefClient()

    assert client.list_url == MishnatYosefClient.LIST_URL


@pytest.mark.asyncio
async def test_get_with_retry_success(
    client,
    monkeypatch,
):
    response = make_response(
        url="https://example.com/file"
    )

    mock_client = setup_async_client(
        monkeypatch,
        [response],
    )

    result = await client._get_with_retry(
        "https://example.com/file"
    )

    assert result is response
    mock_client.get.assert_awaited_once_with(
        "https://example.com/file"
    )


@pytest.mark.asyncio
async def test_get_with_retry_timeout_retries(
    client,
    monkeypatch,
):
    response = make_response(
        url="https://example.com/file"
    )

    mock_client = setup_async_client(
        monkeypatch,
        [
            httpx.TimeoutException("timeout"),
            response,
        ],
    )

    sleep = AsyncMock()
    monkeypatch.setattr(
        "clients.mishnatyosef.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/file"
    )

    assert result is response

    assert mock_client.get.await_count == 2

    sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_get_with_retry_connection_error_retries(
    client,
    monkeypatch,
):
    response = make_response(
        url="https://example.com/file"
    )

    mock_client = setup_async_client(
        monkeypatch,
        [
            httpx.ConnectError("connection failed"),
            response,
        ],
    )

    sleep = AsyncMock()
    monkeypatch.setattr(
        "clients.mishnatyosef.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/file"
    )

    assert result is response

    assert mock_client.get.await_count == 2

    sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_get_with_retry_exhausts_timeout_retries(
    client,
    monkeypatch,
):
    mock_client = setup_async_client(
        monkeypatch,
        [
            httpx.TimeoutException("timeout 1"),
            httpx.TimeoutException("timeout 2"),
            httpx.TimeoutException("timeout 3"),
        ],
    )

    sleep = AsyncMock()
    monkeypatch.setattr(
        "clients.mishnatyosef.asyncio.sleep",
        sleep,
    )

    with pytest.raises(httpx.TimeoutException):
        await client._get_with_retry(
            "https://example.com/file"
        )

    assert mock_client.get.await_count == 3

    assert sleep.await_args_list == [
        call(2),
        call(4),
    ]


@pytest.mark.asyncio
async def test_get_with_retry_exhausts_connection_retries(
    client,
    monkeypatch,
):
    mock_client = setup_async_client(
        monkeypatch,
        [
            httpx.ConnectError("connection 1"),
            httpx.ConnectError("connection 2"),
            httpx.ConnectError("connection 3"),
        ],
    )

    sleep = AsyncMock()
    monkeypatch.setattr(
        "clients.mishnatyosef.asyncio.sleep",
        sleep,
    )

    with pytest.raises(httpx.ConnectError):
        await client._get_with_retry(
            "https://example.com/file"
        )

    assert mock_client.get.await_count == 3

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
        url="https://example.com/file",
    )

    mock_client = setup_async_client(
        monkeypatch,
        [response],
    )

    sleep = AsyncMock()
    monkeypatch.setattr(
        "clients.mishnatyosef.asyncio.sleep",
        sleep,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client._get_with_retry(
            "https://example.com/file"
        )

    mock_client.get.assert_awaited_once_with(
        "https://example.com/file"
    )

    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_files_success(
    client,
):
    files = [
        {
            "name": "PriceFull_001.xml",
            "url": "https://example.com/PriceFull_001.xml",
        },
        {
            "name": "PriceFull_002.xml",
            "url": "https://example.com/PriceFull_002.xml",
        },
    ]

    response = make_response(
        url=client.list_url,
        json_data=files,
    )

    get_with_retry = AsyncMock(
        return_value=response
    )

    client._get_with_retry = get_with_retry

    result = await client.get_files()

    assert result == files

    get_with_retry.assert_awaited_once_with(
        client.list_url
    )


@pytest.mark.asyncio
async def test_get_files_empty_list(
    client,
):
    response = make_response(
        url=client.list_url,
        json_data=[],
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_files()

    assert result == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_response",
    [
        {},
        {"files": []},
        "not-a-list",
        123,
        None,
    ],
)
async def test_get_files_rejects_non_list_response(
    client,
    invalid_response,
):
    response = make_response(
        url=client.list_url,
        json_data=invalid_response,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    with pytest.raises(
        ValueError,
        match="not a JSON array",
    ):
        await client.get_files()


@pytest.mark.asyncio
async def test_get_files_propagates_http_error(
    client,
):
    error = httpx.HTTPStatusError(
        "HTTP 500",
        request=Mock(),
        response=Mock(),
    )

    client._get_with_retry = AsyncMock(
        side_effect=error
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_files()


@pytest.mark.asyncio
async def test_download_file_success(
    client,
):
    response = make_response(
        url="https://example.com/file.xml",
        content=b"file contents",
    )

    get_with_retry = AsyncMock(
        return_value=response
    )

    client._get_with_retry = get_with_retry

    result = await client.download_file(
        "https://example.com/file.xml"
    )

    assert result == b"file contents"

    get_with_retry.assert_awaited_once_with(
        "https://example.com/file.xml"
    )


@pytest.mark.asyncio
async def test_download_file_empty_content(
    client,
):
    response = make_response(
        url="https://example.com/empty.xml",
        content=b"",
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.download_file(
        "https://example.com/empty.xml"
    )

    assert result == b""


@pytest.mark.asyncio
async def test_download_file_propagates_error(
    client,
):
    error = httpx.HTTPStatusError(
        "HTTP 404",
        request=Mock(),
        response=Mock(),
    )

    client._get_with_retry = AsyncMock(
        side_effect=error
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.download_file(
            "https://example.com/missing.xml"
        )