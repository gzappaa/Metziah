import pytest
import httpx
from unittest.mock import AsyncMock, Mock, call

from clients.wolt import WoltClient


@pytest.fixture
def client():
    return WoltClient()


def make_response(
    *,
    status_code=200,
    url="https://example.com",
    text="",
    content=b"",
):
    response = Mock()
    response.status_code = status_code
    response.url = httpx.URL(url)
    response.text = text
    response.content = content

    if status_code >= 400:
        response.raise_for_status.side_effect = (
            httpx.HTTPStatusError(
                "HTTP error",
                request=Mock(),
                response=response,
            )
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
    client = WoltClient()

    assert client.base_url == WoltClient.BASE_URL


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
        "clients.wolt.asyncio.sleep",
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
        "clients.wolt.asyncio.sleep",
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
        "clients.wolt.asyncio.sleep",
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
        "clients.wolt.asyncio.sleep",
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
        "clients.wolt.asyncio.sleep",
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
async def test_get_date_pages(
    client,
):
    html = """
    <html>
        <body>
            <a href="2026-09-20.html">September 20</a>
            <a href="2026-09-21.html">September 21</a>
            <a href="about.html">About</a>
            <a href="prices.json">JSON</a>
            <a href="">Empty</a>
            <a>No href</a>
        </body>
    </html>
    """

    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/index.html"
        ),
        text=html,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_date_pages()

    assert result == [
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/2026-09-20.html"
        ),
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/2026-09-21.html"
        ),
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/about.html"
        ),
    ]

    client._get_with_retry.assert_awaited_once_with(
        f"{client.base_url}/index.html"
    )


@pytest.mark.asyncio
async def test_get_date_pages_handles_relative_paths(
    client,
):
    html = """
    <html>
        <body>
            <a href="./2026-09-21.html">Today</a>
            <a href="../2026-09-20.html">Yesterday</a>
        </body>
    </html>
    """

    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/index.html"
        ),
        text=html,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_date_pages()

    assert result == [
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/2026-09-21.html"
        ),
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/2026-09-20.html"
        ),
    ]


@pytest.mark.asyncio
async def test_get_date_pages_ignores_non_html_links(
    client,
):
    html = """
    <html>
        <body>
            <a href="file.gz">File</a>
            <a href="prices.json">JSON</a>
            <a href="/download/">Download</a>
            <a href="2026-09-21.html">Date</a>
        </body>
    </html>
    """

    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/index.html"
        ),
        text=html,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_date_pages()

    assert result == [
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/2026-09-21.html"
        )
    ]


@pytest.mark.asyncio
async def test_get_date_pages_empty(
    client,
):
    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/index.html"
        ),
        text="<html><body></body></html>",
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_date_pages()

    assert result == []


@pytest.mark.asyncio
async def test_get_files(
    client,
):
    html = """
    <html>
        <body>
            <a href="prices_001.gz">Price 1</a>
            <a href="prices_002.gz">Price 2</a>
            <a href="promos_001.gz">Promo</a>
            <a href="readme.txt">Readme</a>
            <a href="2026-09-21.html">Other page</a>
            <a href="">Empty</a>
        </body>
    </html>
    """

    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/2026-09-21.html"
        ),
        text=html,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    date_page_url = (
        "https://wm-gateway.wolt.com/"
        "isr-prices/public/v1/2026-09-21.html"
    )

    result = await client.get_files(
        date_page_url
    )

    assert result == [
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/prices_001.gz"
        ),
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/prices_002.gz"
        ),
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/promos_001.gz"
        ),
    ]

    client._get_with_retry.assert_awaited_once_with(
        date_page_url
    )


@pytest.mark.asyncio
async def test_get_files_handles_relative_paths(
    client,
):
    html = """
    <html>
        <body>
            <a href="./prices.gz">Current</a>
            <a href="../prices_old.gz">Parent</a>
        </body>
    </html>
    """

    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/"
            "2026-09-21.html"
        ),
        text=html,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_files(
        response.url.__str__()
    )

    assert result == [
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/prices.gz"
        ),
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/prices_old.gz"
        ),
    ]


@pytest.mark.asyncio
async def test_get_files_ignores_non_gz_links(
    client,
):
    html = """
    <html>
        <body>
            <a href="prices.gz">Valid</a>
            <a href="prices.zip">Wrong</a>
            <a href="prices.csv">Wrong</a>
            <a href="index.html">Wrong</a>
        </body>
    </html>
    """

    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/"
            "2026-09-21.html"
        ),
        text=html,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_files(
        "https://example.com/2026-09-21.html"
    )

    assert result == [
        (
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/prices.gz"
        )
    ]


@pytest.mark.asyncio
async def test_get_files_empty(
    client,
):
    response = make_response(
        url=(
            "https://wm-gateway.wolt.com/"
            "isr-prices/public/v1/"
            "2026-09-21.html"
        ),
        text="<html><body></body></html>",
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_files(
        "https://example.com/2026-09-21.html"
    )

    assert result == []


@pytest.mark.asyncio
async def test_download_file(
    client,
):
    response = make_response(
        url="https://example.com/file.gz",
        content=b"gzip file contents",
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.download_file(
        "https://example.com/file.gz"
    )

    assert result == b"gzip file contents"

    client._get_with_retry.assert_awaited_once_with(
        "https://example.com/file.gz"
    )


@pytest.mark.asyncio
async def test_download_file_empty(
    client,
):
    response = make_response(
        url="https://example.com/empty.gz",
        content=b"",
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.download_file(
        "https://example.com/empty.gz"
    )

    assert result == b""


@pytest.mark.asyncio
async def test_check_with_date_pages(
    client,
):
    date_pages = [
        "https://example.com/2026-09-21.html",
        "https://example.com/2026-09-20.html",
    ]

    files = [
        "https://example.com/prices_001.gz",
        "https://example.com/prices_002.gz",
    ]

    get_date_pages = AsyncMock(
        return_value=date_pages
    )

    get_files = AsyncMock(
        return_value=files
    )

    client.get_date_pages = get_date_pages
    client.get_files = get_files

    result = await client.check()

    assert result == {
        "url": f"{client.base_url}/index.html",
        "date_pages": date_pages,
        "files": files,
    }

    get_date_pages.assert_awaited_once_with()

    get_files.assert_awaited_once_with(
        date_pages[0]
    )


@pytest.mark.asyncio
async def test_check_with_no_date_pages(
    client,
):
    get_date_pages = AsyncMock(
        return_value=[]
    )

    get_files = AsyncMock()

    client.get_date_pages = get_date_pages
    client.get_files = get_files

    result = await client.check()

    assert result == {
        "url": f"{client.base_url}/index.html",
        "date_pages": [],
        "files": [],
    }

    get_date_pages.assert_awaited_once_with()

    get_files.assert_not_awaited()