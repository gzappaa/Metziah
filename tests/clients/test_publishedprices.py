from unittest.mock import Mock, call

import pytest
import requests

from clients.publishedprices import PublishedPricesClient


@pytest.fixture
def client():
    return PublishedPricesClient(
        username="test_user",
        password="test_password",
    )


def _http_response(
    *,
    text="",
    url="https://url.publishedprices.co.il/login",
    status_code=200,
):
    response = Mock()
    response.text = text
    response.url = url
    response.status_code = status_code
    return response


def test_init(client):
    assert client.username == "test_user"
    assert client.password == "test_password"
    assert client.csrf_token is None
    assert client.BASE_URL == (
        "https://url.publishedprices.co.il"
    )


def test_get_with_retry_success(
    client,
    monkeypatch,
):
    response = _http_response(
        url="https://example.com/test",
    )

    get = Mock(
        return_value=response
    )

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
    response = _http_response(
        url="https://example.com/test",
    )

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
        "clients.publishedprices.time.sleep",
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
    response = _http_response(
        url="https://example.com/test",
    )

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
        "clients.publishedprices.time.sleep",
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
        "clients.publishedprices.time.sleep",
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
    response = _http_response(
        url="https://example.com/test",
    )

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
        "clients.publishedprices.time.sleep",
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


def test_login_success(
    client,
    monkeypatch,
):
    login_page = _http_response(
        text="""
            <html>
                <head>
                    <meta
                        name="csrftoken"
                        content="initial-token"
                    >
                </head>
            </html>
        """,
    )

    post_response = _http_response(
        text="""
            <html>
                <body>
                    Logged in as 'test_user'
                    <meta
                        name="csrftoken"
                        content="logged-in-token"
                    >
                </body>
            </html>
        """,
        url="https://url.publishedprices.co.il/login/user",
    )

    get = Mock(
        return_value=login_page
    )

    post = Mock(
        return_value=post_response
    )

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    client.login()

    get.assert_called_once_with(
        "https://url.publishedprices.co.il/login",
        timeout=client.TIMEOUT,
    )

    post.assert_called_once_with(
        "https://url.publishedprices.co.il/login/user",
        data={
            "r": "",
            "username": "test_user",
            "password": "test_password",
            "Submit": "Sign in",
            "csrftoken": "initial-token",
        },
        timeout=client.TIMEOUT,
    )

    assert client.csrf_token == "logged-in-token"


def test_login_fails_when_initial_csrf_missing(
    client,
    monkeypatch,
):
    response = _http_response(
        text="""
            <html>
                <head></head>
            </html>
        """
    )

    get = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    with pytest.raises(
        RuntimeError,
        match="Could not find CSRF token",
    ):
        client.login()


def test_login_fails_when_initial_csrf_empty(
    client,
    monkeypatch,
):
    response = _http_response(
        text="""
            <meta
                name="csrftoken"
                content=""
            >
        """
    )

    get = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    with pytest.raises(
        RuntimeError,
        match="CSRF token is empty",
    ):
        client.login()


@pytest.mark.parametrize(
    "login_text",
    [
        "invalid username",
        "incorrect password",
        "account locked",
        "account disabled",
        "login error",
        "password expired",
        "access denied",
    ],
)
def test_login_fails_when_not_logged_in(
    client,
    monkeypatch,
    login_text,
):
    login_page = _http_response(
        text="""
            <meta
                name="csrftoken"
                content="initial-token"
            >
        """
    )

    post_response = Mock()
    post_response.text = login_text

    get = Mock(
        return_value=login_page
    )

    post = Mock(
        return_value=post_response
    )

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    with pytest.raises(
        RuntimeError,
        match="Login failed for user 'test_user'",
    ):
        client.login()

    assert client.csrf_token is None


def test_login_fails_when_post_response_missing_csrf(
    client,
    monkeypatch,
):
    login_page = _http_response(
        text="""
            <meta
                name="csrftoken"
                content="initial-token"
            >
        """
    )

    post_response = Mock()
    post_response.text = """
        Logged in as 'test_user'
    """

    get = Mock(
        return_value=login_page
    )

    post = Mock(
        return_value=post_response
    )

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    with pytest.raises(
        RuntimeError,
        match="Could not find CSRF token after login",
    ):
        client.login()


def test_login_fails_when_post_csrf_empty(
    client,
    monkeypatch,
):
    login_page = _http_response(
        text="""
            <meta
                name="csrftoken"
                content="initial-token"
            >
        """
    )

    post_response = Mock()
    post_response.text = """
        Logged in as 'test_user'
        <meta
            name="csrftoken"
            content=""
        >
    """

    get = Mock(
        return_value=login_page
    )

    post = Mock(
        return_value=post_response
    )

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    with pytest.raises(
        RuntimeError,
        match="CSRF token after login is empty",
    ):
        client.login()


def test_login_raises_http_error_from_post(
    client,
    monkeypatch,
):
    login_page = _http_response(
        text="""
            <meta
                name="csrftoken"
                content="initial-token"
            >
        """
    )

    post_response = Mock()
    post_response.text = "error"
    post_response.raise_for_status.side_effect = (
        requests.HTTPError("500")
    )

    get = Mock(
        return_value=login_page
    )

    post = Mock(
        return_value=post_response
    )

    monkeypatch.setattr(
        client.session,
        "get",
        get,
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    with pytest.raises(
        requests.HTTPError,
        match="500",
    ):
        client.login()


def test_get_files_requires_login(client):
    with pytest.raises(
        RuntimeError,
        match="Client is not logged in",
    ):
        client.get_files()


def test_get_files_success(
    client,
    monkeypatch,
):
    client.csrf_token = "csrf-token"

    expected = {
        "aaData": [
            {
                "fname": "prices.xml",
                "size": 123,
            }
        ],
        "iTotalRecords": 1,
    }

    response = Mock()

    response.json.return_value = expected

    post = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    result = client.get_files()

    assert result == expected

    post.assert_called_once_with(
        "https://url.publishedprices.co.il/file/json/dir",
        data={
            "sEcho": "1",
            "iColumns": "5",
            "sColumns": ",,,,",
            "iDisplayStart": "0",
            "iDisplayLength": "10000",
            "mDataProp_0": "fname",
            "sSearch_0": "",
            "bRegex_0": "false",
            "bSearchable_0": "true",
            "bSortable_0": "true",
            "mDataProp_1": "typeLabel",
            "sSearch_1": "",
            "bRegex_1": "false",
            "bSearchable_1": "true",
            "bSortable_1": "false",
            "mDataProp_2": "size",
            "sSearch_2": "",
            "bRegex_2": "false",
            "bSearchable_2": "true",
            "bSortable_2": "true",
            "mDataProp_3": "ftime",
            "sSearch_3": "",
            "bRegex_3": "false",
            "bSearchable_3": "true",
            "bSortable_3": "true",
            "mDataProp_4": "",
            "sSearch_4": "",
            "bRegex_4": "false",
            "bSearchable_4": "true",
            "bSortable_4": "false",
            "sSearch": "",
            "bRegex": "false",
            "iSortingCols": "0",
            "cd": "/",
            "csrftoken": "csrf-token",
        },
        timeout=client.TIMEOUT,
    )

    response.raise_for_status.assert_called_once()


def test_get_files_custom_directory(
    client,
    monkeypatch,
):
    client.csrf_token = "csrf-token"

    response = Mock()
    response.json.return_value = {
        "aaData": []
    }

    post = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    result = client.get_files(
        cd="/some/directory"
    )

    assert result == {
        "aaData": []
    }

    data = post.call_args.kwargs["data"]

    assert data["cd"] == "/some/directory"
    assert data["csrftoken"] == "csrf-token"


def test_get_files_raises_http_error(
    client,
    monkeypatch,
):
    client.csrf_token = "csrf-token"

    response = Mock()

    response.raise_for_status.side_effect = (
        requests.HTTPError("500")
    )

    post = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client.session,
        "post",
        post,
    )

    with pytest.raises(
        requests.HTTPError,
        match="500",
    ):
        client.get_files()


def test_build_download_url(client):
    result = client.build_download_url(
        "prices.xml"
    )

    assert result == (
        "https://url.publishedprices.co.il"
        "/file/d/prices.xml"
    )


def test_download_file(
    client,
    monkeypatch,
):
    response = Mock()

    response.content = b"file contents"

    get_with_retry = Mock(
        return_value=response
    )

    monkeypatch.setattr(
        client,
        "_get_with_retry",
        get_with_retry,
    )

    url = (
        "https://url.publishedprices.co.il"
        "/file/d/prices.xml"
    )

    result = client.download_file(url)

    assert result == b"file contents"

    get_with_retry.assert_called_once_with(
        url
    )