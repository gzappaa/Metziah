# clients/publishedprices.py

import logging
import time

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


class PublishedPricesClient:

    BASE_URL = "https://url.publishedprices.co.il"

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = 30


    def __init__(
        self,
        username: str,
        password: str,
    ):
        self.username = username
        self.password = password

        self.session = requests.Session()
        self.csrf_token = None


    def _get_with_retry(
        self,
        url: str,
        **kwargs,
    ) -> requests.Response:

        last_exc = None

        for attempt in range(self.MAX_RETRIES):

            try:

                response = self.session.get(
                    url,
                    timeout=self.TIMEOUT,
                    **kwargs,
                )

                response.raise_for_status()

                logger.debug(
                    "GET %s -> HTTP %d",
                    response.url,
                    response.status_code,
                )

                return response

            except (
                requests.Timeout,
                requests.ConnectionError,
            ) as exc:

                last_exc = exc

                logger.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    url,
                    exc,
                )

                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(
                        self.BACKOFF_SECONDS[attempt]
                    )

            except requests.HTTPError:

                raise

        logger.error(
            "All %d attempts failed for %s",
            self.MAX_RETRIES,
            url,
        )

        raise last_exc


    def login(self) -> None:

        response = self._get_with_retry(
            f"{self.BASE_URL}/login"
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        csrf_meta = soup.find(
            "meta",
            {"name": "csrftoken"},
        )

        if csrf_meta is None:
            raise RuntimeError(
                "Could not find CSRF token"
            )

        csrf_token = csrf_meta.get("content")

        if not csrf_token:
            raise RuntimeError(
                "CSRF token is empty"
            )

        response = self.session.post(
            f"{self.BASE_URL}/login/user",
            data={
                "r": "",
                "username": self.username,
                "password": self.password,
                "Submit": "Sign in",
                "csrftoken": csrf_token,
            },
            timeout=self.TIMEOUT,
        )

        response.raise_for_status()

        if (
            f"Logged in as '{self.username}'"
            not in response.text
        ):
            for keyword in (
                "invalid",
                "incorrect",
                "locked",
                "disabled",
                "error",
                "expired",
                "denied",
            ):
                idx = response.text.lower().find(
                    keyword
                )

                if idx != -1:
                    logger.warning(
                        "Login response contains '%s' near: %s",
                        keyword,
                        response.text[
                            max(0, idx - 100):
                            idx + 200
                        ],
                    )

            raise RuntimeError(
                f"Login failed for user "
                f"'{self.username}'"
            )

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        csrf_meta = soup.find(
            "meta",
            {"name": "csrftoken"},
        )

        if csrf_meta is None:
            raise RuntimeError(
                "Could not find CSRF token after login"
            )

        self.csrf_token = csrf_meta.get(
            "content"
        )

        if not self.csrf_token:
            raise RuntimeError(
                "CSRF token after login is empty"
            )


    def get_files(
        self,
        cd: str = "/",
    ) -> dict:

        if self.csrf_token is None:
            raise RuntimeError(
                "Client is not logged in"
            )

        response = self.session.post(
            f"{self.BASE_URL}/file/json/dir",
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
                "cd": cd,
                "csrftoken": self.csrf_token,
            },
            timeout=self.TIMEOUT,
        )

        response.raise_for_status()

        return response.json()


    def build_download_url(
        self,
        filename: str,
    ) -> str:

        return (
            f"{self.BASE_URL}"
            f"/file/d/{filename}"
        )


    def download_file(
        self,
        url: str,
    ) -> bytes:

        response = self._get_with_retry(url)

        return response.content