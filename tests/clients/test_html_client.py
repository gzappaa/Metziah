import pytest
import httpx
from unittest.mock import AsyncMock, Mock, call

from clients.html_client import Candidate, HtmlFileLinkClient
from clients.html_config import SOURCES


@pytest.fixture
def client():
    return HtmlFileLinkClient(
        name="test publisher",
        base_url="https://example.com/files/",
    )


def make_response(
    *,
    status_code=200,
    url="https://example.com/files/",
    text="",
):
    response = Mock()
    response.status_code = status_code
    response.url = httpx.URL(url)
    response.text = text
    response.content = text.encode()

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

    constructor = Mock(
        return_value=context_manager
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        constructor,
    )

    return mock_client


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_defaults():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com/files/",
    )

    assert client.name == "test"
    assert client.base_url == "https://example.com/files"
    assert client.extraction_mode == "anchor"
    assert client.filename_column is None
    assert client.filename_source == "path"
    assert client.filename_param is None
    assert client.file_size_column is None


def test_init_all_options():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com/",
        extraction_mode="row",
        filename_column="Filename",
        filename_source="row",
        filename_param="fileName",
        file_size_column=2,
    )

    assert client.name == "test"
    assert client.base_url == "https://example.com"
    assert client.extraction_mode == "row"
    assert client.filename_column == "Filename"
    assert client.filename_source == "row"
    assert client.filename_param == "fileName"
    assert client.file_size_column == 2


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_with_retry_success(
    client,
    monkeypatch,
):
    response = make_response(
        url="https://example.com/files/"
    )

    mock_client = setup_async_client(
        monkeypatch,
        [response],
    )

    result = await client._get_with_retry(
        "https://example.com/files/"
    )

    assert result is response

    mock_client.get.assert_awaited_once_with(
        "https://example.com/files/",
        params=None,
    )


@pytest.mark.asyncio
async def test_get_with_retry_passes_params(
    client,
    monkeypatch,
):
    response = make_response()

    mock_client = setup_async_client(
        monkeypatch,
        [response],
    )

    params = {
        "page": "2",
        "type": "Price",
    }

    await client._get_with_retry(
        "https://example.com/files/",
        params=params,
    )

    mock_client.get.assert_awaited_once_with(
        "https://example.com/files/",
        params=params,
    )


@pytest.mark.asyncio
async def test_get_with_retry_timeout_retries(
    client,
    monkeypatch,
):
    response = make_response()

    mock_client = setup_async_client(
        monkeypatch,
        [
            httpx.TimeoutException("timeout"),
            response,
        ],
    )

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.html_client.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/files/"
    )

    assert result is response
    assert mock_client.get.await_count == 2

    sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_get_with_retry_connection_error_retries(
    client,
    monkeypatch,
):
    response = make_response()

    mock_client = setup_async_client(
        monkeypatch,
        [
            httpx.ConnectError("connection failed"),
            response,
        ],
    )

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.html_client.asyncio.sleep",
        sleep,
    )

    result = await client._get_with_retry(
        "https://example.com/files/"
    )

    assert result is response
    assert mock_client.get.await_count == 2

    sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_get_with_retry_exhausts_retries(
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
        "clients.html_client.asyncio.sleep",
        sleep,
    )

    with pytest.raises(httpx.TimeoutException):
        await client._get_with_retry(
            "https://example.com/files/"
        )

    assert mock_client.get.await_count == 3

    assert sleep.await_args_list == [
        call(2),
        call(4),
    ]


@pytest.mark.asyncio
async def test_get_with_retry_http_error_is_not_retried(
    client,
    monkeypatch,
):
    response = make_response(
        status_code=404,
    )

    mock_client = setup_async_client(
        monkeypatch,
        [response],
    )

    sleep = AsyncMock()

    monkeypatch.setattr(
        "clients.html_client.asyncio.sleep",
        sleep,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client._get_with_retry(
            "https://example.com/files/"
        )

    mock_client.get.assert_awaited_once()

    sleep.assert_not_awaited()


# ---------------------------------------------------------------------------
# Filename extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href,expected",
    [
        (
            "https://example.com/files/Prices001.xml",
            "Prices001.xml",
        ),
        (
            "https://example.com/files/Prices001.xml?x=1",
            "Prices001.xml",
        ),
        (
            "https://example.com/files/",
            None,
        ),
        (
            "/files/Prices001.xml",
            "Prices001.xml",
        ),
    ],
)
def test_extract_filename_path(
    client,
    href,
    expected,
):
    assert (
        client._extract_filename(href, "ignored")
        == expected
    )


def test_extract_filename_query():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        filename_source="query",
        filename_param="fileName",
    )

    assert client._extract_filename(
        "https://example.com/download?id=123&fileName=Price001.xml",
        "ignored",
    ) == "Price001.xml"


def test_extract_filename_query_missing_parameter():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        filename_source="query",
        filename_param="fileName",
    )

    assert client._extract_filename(
        "https://example.com/download?id=123",
        "ignored",
    ) is None


def test_extract_filename_query_empty_parameter():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        filename_source="query",
        filename_param="fileName",
    )

    assert client._extract_filename(
        "https://example.com/download?fileName=",
        "ignored",
    ) is None


def test_extract_filename_query_requires_parameter():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        filename_source="query",
    )

    with pytest.raises(
        ValueError,
        match="filename_param is required",
    ):
        client._extract_filename(
            "https://example.com/download",
            "ignored",
        )


def test_extract_filename_row():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        filename_source="row",
    )

    assert client._extract_filename(
        "https://example.com/download",
        "Price001.xml",
    ) == "Price001.xml"


def test_extract_filename_row_empty_text():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        filename_source="row",
    )

    assert client._extract_filename(
        "https://example.com/download",
        "",
    ) is None


def test_extract_filename_unsupported_source():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        filename_source="something_else",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported filename source",
    ):
        client._extract_filename(
            "https://example.com/file.xml",
            "file.xml",
        )


# ---------------------------------------------------------------------------
# Anchor extraction
# ---------------------------------------------------------------------------


def test_extract_anchor_mode():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com/files",
        extraction_mode="anchor",
        filename_source="path",
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <html>
            <body>
                <a href="Price001.xml">Price 001</a>
                <a href="/files/Price002.xml">Price 002</a>
                <a href="">Ignore</a>
                <a>No href</a>
            </body>
        </html>
        """
    )

    result = client._extract_anchor_mode(
        tree,
        "https://example.com/files/index.html",
    )

    assert result == [
        Candidate(
            text="Price 001",
            href="https://example.com/files/Price001.xml",
            filename="Price001.xml",
            file_size=None,
        ),
        Candidate(
            text="Price 002",
            href="https://example.com/files/Price002.xml",
            filename="Price002.xml",
            file_size=None,
        ),
    ]


def test_extract_anchor_mode_query_filename():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="anchor",
        filename_source="query",
        filename_param="fileName",
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <html>
            <body>
                <a href="/download?id=1&fileName=Price001.xml">
                    Download
                </a>
            </body>
        </html>
        """
    )

    result = client._extract_anchor_mode(
        tree,
        "https://example.com/index.html",
    )

    assert result[0].filename == "Price001.xml"
    assert result[0].href == (
        "https://example.com/download"
        "?id=1&fileName=Price001.xml"
    )


def test_extract_anchor_mode_file_size():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="anchor",
        filename_source="path",
        file_size_column=2,
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <tbody>
                <tr>
                    <td>Price</td>
                    <td>21/09/2026</td>
                    <td>15 KB</td>
                    <td>
                        <a href="Price001.xml">
                            Download
                        </a>
                    </td>
                </tr>
            </tbody>
        </table>
        """
    )

    result = client._extract_anchor_mode(
        tree,
        "https://example.com/files/index.html",
    )

    assert len(result) == 1
    assert result[0].filename == "Price001.xml"
    assert result[0].file_size == "15 KB"


def test_extract_anchor_mode_empty_file_size():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="anchor",
        filename_source="path",
        file_size_column=2,
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <tr>
                <td>Price</td>
                <td>Date</td>
                <td></td>
                <td>
                    <a href="Price001.xml">Download</a>
                </td>
            </tr>
        </table>
        """
    )

    result = client._extract_anchor_mode(
        tree,
        "https://example.com/files/index.html",
    )

    assert result[0].file_size is None


def test_extract_anchor_mode_file_size_out_of_range():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="anchor",
        filename_source="path",
        file_size_column=10,
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <tr>
                <td>Price</td>
                <td>
                    <a href="Price001.xml">Download</a>
                </td>
            </tr>
        </table>
        """
    )

    result = client._extract_anchor_mode(
        tree,
        "https://example.com/files/index.html",
    )

    assert result[0].file_size is None


# ---------------------------------------------------------------------------
# Row extraction
# ---------------------------------------------------------------------------


def test_extract_row_mode_with_filename_column():
    client = HtmlFileLinkClient(
        name="city market 2",
        base_url="https://example.com",
        extraction_mode="row",
        filename_source="row",
        filename_column="File Name",
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>File Name</th>
                    <th>Size</th>
                    <th>Download</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>21/09/2026</td>
                    <td>Price001.xml</td>
                    <td>20 KB</td>
                    <td>
                        <a href="/download/1">Download</a>
                    </td>
                </tr>
            </tbody>
        </table>
        """
    )

    result = client._extract_row_mode(
        tree,
        "https://example.com/index.html",
    )

    assert result == [
        Candidate(
            text="Price001.xml",
            href="https://example.com/download/1",
            filename="Price001.xml",
            file_size=None,
        )
    ]


def test_extract_row_mode_fallback_filename():
    client = HtmlFileLinkClient(
        name="city market 2",
        base_url="https://example.com",
        extraction_mode="row",
        filename_source="row",
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <tbody>
                <tr>
                    <td>21/09/2026</td>
                    <td>Price001.xml</td>
                    <td>
                        <a href="/download/1">Download</a>
                    </td>
                </tr>
            </tbody>
        </table>
        """
    )

    result = client._extract_row_mode(
        tree,
        "https://example.com/index.html",
    )

    assert result[0].filename == "Price001.xml"
    assert result[0].text == "Price001.xml"


@pytest.mark.parametrize(
    "filename",
    [
        "Price001.xml",
        "Promo001.xml",
        "Stores001.xml",
    ],
)
def test_extract_row_mode_fallback_recognizes_known_prefixes(
    filename,
):
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="row",
        filename_source="row",
    )

    tree = __import__("lxml.html").html.fromstring(
        f"""
        <table>
            <tr>
                <td>Something</td>
                <td>{filename}</td>
                <td>
                    <a href="/download/1">Download</a>
                </td>
            </tr>
        </table>
        """
    )

    result = client._extract_row_mode(
        tree,
        "https://example.com/index.html",
    )

    assert result[0].filename == filename


def test_extract_row_mode_ignores_rows_without_cells():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="row",
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <tr>
                <th>Header</th>
            </tr>
            <tr>
                <td>Price001.xml</td>
                <td>
                    <a href="/download/1">Download</a>
                </td>
            </tr>
        </table>
        """
    )

    result = client._extract_row_mode(
        tree,
        "https://example.com/index.html",
    )

    assert len(result) == 1


def test_extract_row_mode_ignores_rows_without_links():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="row",
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <tr>
                <td>Price001.xml</td>
                <td>No download</td>
            </tr>
        </table>
        """
    )

    result = client._extract_row_mode(
        tree,
        "https://example.com/index.html",
    )

    assert result == []


def test_extract_row_mode_file_size():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="row",
        filename_source="row",
        file_size_column=2,
    )

    tree = __import__("lxml.html").html.fromstring(
        """
        <table>
            <tr>
                <td>Price001.xml</td>
                <td>21/09/2026</td>
                <td>25 KB</td>
                <td>
                    <a href="/download/1">Download</a>
                </td>
            </tr>
        </table>
        """
    )

    result = client._extract_row_mode(
        tree,
        "https://example.com/index.html",
    )

    assert result[0].file_size == "25 KB"


# ---------------------------------------------------------------------------
# get_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_candidates_anchor_mode(
    client,
):
    html = """
    <html>
        <body>
            <a href="Price001.xml">Price 001</a>
            <a href="Promo001.xml">Promo 001</a>
        </body>
    </html>
    """

    response = make_response(
        url="https://example.com/files/",
        text=html,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_candidates()

    assert result == [
        Candidate(
            text="Price 001",
            href="https://example.com/files/Price001.xml",
            filename="Price001.xml",
            file_size=None,
        ),
        Candidate(
            text="Promo 001",
            href="https://example.com/files/Promo001.xml",
            filename="Promo001.xml",
            file_size=None,
        ),
    ]

    client._get_with_retry.assert_awaited_once_with(
        client.base_url,
        params=None,
    )


@pytest.mark.asyncio
async def test_get_candidates_passes_params(
    client,
):
    response = make_response(
        url="https://example.com/files/",
        text="<html></html>",
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    params = {
        "page": "2",
        "type": "Price",
    }

    result = await client.get_candidates(
        params=params
    )

    assert result == []

    client._get_with_retry.assert_awaited_once_with(
        client.base_url,
        params=params,
    )


@pytest.mark.asyncio
async def test_get_candidates_row_mode():
    client = HtmlFileLinkClient(
        name="city market 2",
        base_url="https://example.com",
        extraction_mode="row",
        filename_source="row",
    )

    response = make_response(
        url="https://example.com/",
        text="""
        <table>
            <tr>
                <td>Price001.xml</td>
                <td>
                    <a href="/download/1">Download</a>
                </td>
            </tr>
        </table>
        """,
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    result = await client.get_candidates()

    assert len(result) == 1
    assert result[0].filename == "Price001.xml"
    assert result[0].href == (
        "https://example.com/download/1"
    )


@pytest.mark.asyncio
async def test_get_candidates_invalid_extraction_mode():
    client = HtmlFileLinkClient(
        name="test",
        base_url="https://example.com",
        extraction_mode="invalid",
    )

    response = make_response(
        text="<html></html>",
    )

    client._get_with_retry = AsyncMock(
        return_value=response
    )

    with pytest.raises(
        ValueError,
        match="Unsupported extraction mode",
    ):
        await client.get_candidates()


# ---------------------------------------------------------------------------
# Real html_config.py validation
# ---------------------------------------------------------------------------


def test_html_sources_exist():
    assert len(SOURCES) == 5


def test_html_source_names():
    assert [
        source["name"]
        for source in SOURCES
    ] == [
        "hazi hinam",
        "super pharm",
        "shufersal",
        "city market 2",
        "netiv hesed",
    ]


def test_html_sources_have_required_configuration():
    for source in SOURCES:
        assert "name" in source
        assert "listing" in source
        assert "categories" in source
        assert "extraction_mode" in source
        assert "filename_source" in source

        assert source["listing"]["base_url"]

        assert source["extraction_mode"] in {
            "anchor",
            "row",
        }

        assert source["filename_source"] in {
            "path",
            "query",
            "row",
        }


def test_hazi_hinam_config():
    source = next(
        source
        for source in SOURCES
        if source["name"] == "hazi hinam"
    )

    assert source["extraction_mode"] == "anchor"
    assert source["filename_source"] == "path"

    assert source["listing"]["pagination"] == "numeric"
    assert source["listing"]["page_param"] == "p"

    assert source["categories"]["store_param"] == "s"
    assert source["categories"]["date_param"] == "d"
    assert source["categories"]["full_param"] == "f"


def test_super_pharm_config():
    source = next(
        source
        for source in SOURCES
        if source["name"] == "super pharm"
    )

    assert source["extraction_mode"] == "anchor"
    assert source["filename_source"] == "path"

    assert source["categories"]["date_param"] == "Date-equals"

    assert source["categories"]["file_types"]["Price"] == {
        "Category-equals": "Price"
    }

    assert source["categories"]["file_types"]["PriceFull"] == {
        "Category-equals": "PriceFull"
    }


def test_shufersal_config():
    source = next(
        source
        for source in SOURCES
        if source["name"] == "shufersal"
    )

    assert source["extraction_mode"] == "anchor"
    assert source["filename_source"] == "path"

    assert source["file_size_column"] == 2

    assert (
        source["categories"]["endpoint"]
        == "https://prices.shufersal.co.il/FileObject/UpdateCategory"
    )

    assert (
        source["categories"]["all_stores_value"]
        == "0"
    )

    assert source["categories"]["file_types"]["Price"] == {
        "catID": "1"
    }


def test_city_market_config():
    source = next(
        source
        for source in SOURCES
        if source["name"] == "city market 2"
    )

    assert source["extraction_mode"] == "row"
    assert source["filename_source"] == "row"

    assert source["listing"]["page_param"] == "p"

    assert source["categories"]["store_param"] == "s"
    assert source["categories"]["date_param"] == "d"
    assert source["categories"]["full_param"] == "f"


def test_netiv_hesed_config():
    source = next(
        source
        for source in SOURCES
        if source["name"] == "netiv hesed"
    )

    assert source["extraction_mode"] == "anchor"
    assert source["filename_source"] == "query"
    assert source["filename_param"] == "fileName"

    assert source["listing"]["pagination"] is None
    assert source["categories"]["date_param"] == "Date"

    assert source["categories"]["file_types"]["Price"] == {
        "FileType": "Price"
    }


# ---------------------------------------------------------------------------
# Configuration compatibility checks
# ---------------------------------------------------------------------------


def test_query_filename_sources_define_parameter():
    for source in SOURCES:
        if source["filename_source"] == "query":
            assert source.get("filename_param")


def test_row_sources_have_row_extraction():
    for source in SOURCES:
        if source["filename_source"] == "row":
            assert source["extraction_mode"] == "row"


def test_all_sources_define_all_file_types():
    expected_types = {
        "Price",
        "PriceFull",
        "Promo",
        "PromoFull",
        "Stores",
    }

    for source in SOURCES:
        actual_types = set(
            source["categories"]["file_types"]
        )

        assert actual_types == expected_types