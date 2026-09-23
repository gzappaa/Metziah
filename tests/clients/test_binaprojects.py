from unittest.mock import Mock, call

import pytest
import requests

from clients.binaprojects import BinaProjectsClient


@pytest.fixture
def client():
    return BinaProjectsClient(
        "https://example.com/Main.aspx"
    )


def test_init_normalizes_source_url():
    client = BinaProjectsClient(
        "https://example.com/Main.aspx/"
    )

    assert client.source_url == "https://example.com/Main.aspx"
    assert client.base_url == "https://example.com"


def test_get_with_retry_success(client, monkeypatch):
    response = Mock()
    response.url = "https://example.com/test"
    response.status_code = 200

    get = Mock(return_value=response)

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    result = client._get_with_retry(
        "https://example.com/test"
    )

    assert result is response

    get.assert_called_once_with(
        "https://example.com/test",
        timeout=client.TIMEOUT,
    )

    response.raise_for_status.assert_called_once()


def test_get_with_retry_retries_timeout(
    client,
    monkeypatch,
):
    response = Mock()
    response.url = "https://example.com/test"
    response.status_code = 200

    get = Mock(
        side_effect=[
            requests.Timeout("timeout"),
            requests.Timeout("timeout"),
            response,
        ]
    )

    sleep = Mock()

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        "clients.binaprojects.time.sleep",
        sleep,
    )

    result = client._get_with_retry(
        "https://example.com/test"
    )

    assert result is response
    assert get.call_count == 3

    assert sleep.call_args_list == [
        call(2),
        call(4),
    ]


def test_get_with_retry_retries_connection_error(
    client,
    monkeypatch,
):
    response = Mock()
    response.url = "https://example.com/test"
    response.status_code = 200

    get = Mock(
        side_effect=[
            requests.ConnectionError(
                "connection failed"
            ),
            response,
        ]
    )

    sleep = Mock()

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        "clients.binaprojects.time.sleep",
        sleep,
    )

    result = client._get_with_retry(
        "https://example.com/test"
    )

    assert result is response
    assert get.call_count == 2

    sleep.assert_called_once_with(2)


def test_get_with_retry_raises_after_all_retries(
    client,
    monkeypatch,
):
    error = requests.Timeout("timeout")

    get = Mock(
        side_effect=error
    )

    sleep = Mock()

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        "clients.binaprojects.time.sleep",
        sleep,
    )

    with pytest.raises(
        requests.Timeout,
        match="timeout",
    ):
        client._get_with_retry(
            "https://example.com/test"
        )

    assert get.call_count == 3

    assert sleep.call_args_list == [
        call(2),
        call(4),
    ]


def test_get_with_retry_does_not_retry_http_error(
    client,
    monkeypatch,
):
    response = Mock()

    response.raise_for_status.side_effect = (
        requests.HTTPError("404")
    )

    get = Mock(
        return_value=response
    )

    sleep = Mock()

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        "clients.binaprojects.time.sleep",
        sleep,
    )

    with pytest.raises(
        requests.HTTPError,
        match="404",
    ):
        client._get_with_retry(
            "https://example.com/test"
        )

    get.assert_called_once_with(
        "https://example.com/test",
        timeout=client.TIMEOUT,
    )

    sleep.assert_not_called()


def test_get_hok_files(client, monkeypatch):
    response = Mock()

    expected = [
        {
            "FileNm": "price.xml",
            "WFileType": 2,
        }
    ]

    response.json.return_value = expected

    get = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    result = client.get_hok_files(
        store="123",
        date="2026-09-21",
        file_type=2,
    )

    assert result == expected

    get.assert_called_once_with(
        "https://example.com/MainIO_Hok.aspx",
        params={
            "wReshet": "",
            "WStore": "123",
            "WDate": "2026-09-21",
            "WFileType": 2,
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
        },
    )


def test_get_download_url(client, monkeypatch):
    response = Mock()

    response.json.return_value = [
        {
            "SPath": (
                "https://files.example.com/price.xml"
            )
        }
    ]

    get = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    result = client.get_download_url(
        "price.xml"
    )

    assert result == (
        "https://files.example.com/price.xml"
    )

    get.assert_called_once_with(
        "https://example.com/Download.aspx",
        params={
            "FileNm": "price.xml",
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
        },
    )


@pytest.mark.parametrize(
    "data",
    [
        [],
        [{}],
        [{"SPath": ""}],
        [{"SPath": None}],
    ],
)
def test_get_download_url_raises_when_no_path(
    client,
    monkeypatch,
    data,
):
    response = Mock()
    response.json.return_value = data

    get = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    with pytest.raises(
        RuntimeError,
        match="No download URL returned for price.xml",
    ):
        client.get_download_url(
            "price.xml"
        )


def test_download_file_direct_success(
    client,
    monkeypatch,
):
    response = Mock()
    response.content = b"file contents"

    get = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    result = client.download_file(
        "price.xml"
    )

    assert result == b"file contents"

    get.assert_called_once_with(
        "https://example.com/Download/price.xml"
    )


def test_download_file_falls_back_after_http_error(
    client,
    monkeypatch,
):
    direct_error = requests.HTTPError(
        "direct download failed"
    )

    fallback_response = Mock()
    fallback_response.content = b"fallback contents"

    get = Mock(
        side_effect=[
            direct_error,
            fallback_response,
        ]
    )

    get_download_url = Mock(
        return_value=(
            "https://files.example.com/price.xml"
        )
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    monkeypatch.setattr(
        client,
        "get_download_url",
        get_download_url,
    )

    result = client.download_file(
        "price.xml"
    )

    assert result == b"fallback contents"

    assert get.call_args_list == [
        call(
            "https://example.com/Download/price.xml"
        ),
        call(
            "https://files.example.com/price.xml"
        ),
    ]

    get_download_url.assert_called_once_with(
        "price.xml"
    )


def test_download_file_fallback_error_propagates(
    client,
    monkeypatch,
):
    direct_error = requests.HTTPError(
        "direct failed"
    )

    fallback_error = requests.ConnectionError(
        "fallback failed"
    )

    get = Mock(
        side_effect=[
            direct_error,
            fallback_error,
        ]
    )

    get_download_url = Mock(
        return_value=(
            "https://files.example.com/price.xml"
        )
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get,
    )

    monkeypatch.setattr(
        client,
        "get_download_url",
        get_download_url,
    )

    with pytest.raises(
        requests.ConnectionError,
        match="fallback failed",
    ):
        client.download_file(
            "price.xml"
        )

    assert get.call_count == 2

    get_download_url.assert_called_once_with(
        "price.xml"
    )