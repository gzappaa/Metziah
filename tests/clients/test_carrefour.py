import asyncio
from unittest.mock import AsyncMock, Mock, call

import httpx
import pytest

from clients.carrefour import CarrefourClient


@pytest.fixture
def client():
    return CarrefourClient()


def make_response(
    *,
    text="",
    content=b"",
    status_code=200,
    url="https://prices.carrefour.co.il",
):
    response = Mock(spec=httpx.Response)

    response.text = text
    response.content = content
    response.status_code = status_code
    response.url = httpx.URL(url)

    return response


@pytest.mark.asyncio
async def test_init(client):
    assert client.base_url == (
        "https://prices.carrefour.co.il"
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
        "clients.carrefour.httpx.AsyncClient",
        async_client_class,
    )

    result = await client._get_with_retry(
        "https://example.com/test"
    )

    assert result is response

    async_client_class.assert_called_once_with(
        timeout=client.TIMEOUT
    )

    get.assert_awaited_once_with(
        "https://example.com/test"
    )

    response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_get_with_retry_retries_timeout(
    client,
    monkeypatch,
):
    response = make_response(
        status_code=200,
    )

    response.raise_for_status = Mock()

    get = AsyncMock(
        side_effect=[
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            response,
        ]
    )

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

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.carrefour.httpx.AsyncClient",
        async_client_class,
    )

    monkeypatch.setattr(
        "clients.carrefour.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/test"
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
    response = make_response(
        status_code=200,
    )

    response.raise_for_status = Mock()

    get = AsyncMock(
        side_effect=[
            httpx.ConnectError("connection failed"),
            response,
        ]
    )

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

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.carrefour.httpx.AsyncClient",
        async_client_class,
    )

    monkeypatch.setattr(
        "clients.carrefour.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/test"
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

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.carrefour.httpx.AsyncClient",
        async_client_class,
    )

    monkeypatch.setattr(
        "clients.carrefour.asyncio.sleep",
        sleep,
    )

    with pytest.raises(
        httpx.TimeoutException,
        match="timeout",
    ):
        await client._get_with_retry(
            "https://example.com/test"
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

    http_error = httpx.HTTPStatusError(
        "404",
        request=Mock(),
        response=response,
    )

    response.raise_for_status = Mock(
        side_effect=http_error
    )

    get = AsyncMock(
        return_value=response
    )

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

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.carrefour.httpx.AsyncClient",
        async_client_class,
    )

    monkeypatch.setattr(
        "clients.carrefour.asyncio.sleep",
        sleep,
    )

    with pytest.raises(
        httpx.HTTPStatusError,
        match="404",
    ):
        await client._get_with_retry(
            "https://example.com/test"
        )

    get.assert_awaited_once_with(
        "https://example.com/test"
    )

    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_files_without_date(
    client,
    monkeypatch,
):
    html = """
    <html>
    <script>
        const path = '/files/2026-09-21';
        const files = [
            "prices.xml",
            "promos.xml"
        ];
    </script>
    </html>
    """

    response = make_response(
        text=html,
    )

    get = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    result = await client.get_files()

    assert result == {
        "path": "/files/2026-09-21",
        "files": [
            "prices.xml",
            "promos.xml",
        ],
    }

    get.assert_awaited_once_with(
        "https://prices.carrefour.co.il"
    )


@pytest.mark.asyncio
async def test_get_files_with_date(
    client,
    monkeypatch,
):
    html = """
    <script>
        const path = '/files/2026-09-21';
        const files = ["prices.xml"];
    </script>
    """

    response = make_response(
        text=html,
    )

    get = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    result = await client.get_files(
        date="2026-09-21"
    )

    assert result == {
        "path": "/files/2026-09-21",
        "files": [
            "prices.xml",
        ],
    }

    get.assert_awaited_once_with(
        "https://prices.carrefour.co.il/"
        "?date=2026-09-21"
    )


@pytest.mark.asyncio
async def test_get_files_supports_double_quotes(
    client,
    monkeypatch,
):
    html = """
    <script>
        const path = "/files/test";
        const files = ["a.xml", "b.xml"];
    </script>
    """

    response = make_response(
        text=html,
    )

    get = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    result = await client.get_files()

    assert result == {
        "path": "/files/test",
        "files": [
            "a.xml",
            "b.xml",
        ],
    }


@pytest.mark.asyncio
async def test_get_files_raises_when_path_missing(
    client,
    monkeypatch,
):
    html = """
    <script>
        const files = ["prices.xml"];
    </script>
    """

    response = make_response(
        text=html,
    )

    get = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    with pytest.raises(
        ValueError,
        match="Could not find Carrefour 'path' in HTML",
    ):
        await client.get_files()


@pytest.mark.asyncio
async def test_get_files_raises_when_files_missing(
    client,
    monkeypatch,
):
    html = """
    <script>
        const path = '/files/test';
    </script>
    """

    response = make_response(
        text=html,
    )

    get = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    with pytest.raises(
        ValueError,
        match="Could not find Carrefour 'files' in HTML",
    ):
        await client.get_files()


@pytest.mark.asyncio
async def test_get_files_raises_when_files_json_invalid(
    client,
    monkeypatch,
):
    html = """
    <script>
        const path = '/files/test';
        const files = [invalid json];
    </script>
    """

    response = make_response(
        text=html,
    )

    get = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    with pytest.raises(ValueError):
        await client.get_files()


@pytest.mark.asyncio
async def test_download_file(
    client,
    monkeypatch,
):
    response = make_response(
        content=b"file contents",
    )

    get = AsyncMock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    result = await client.download_file(
        "https://files.example.com/test.xml"
    )

    assert result == b"file contents"

    get.assert_awaited_once_with(
        "https://files.example.com/test.xml"
    )