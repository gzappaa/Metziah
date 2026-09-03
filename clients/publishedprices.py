# clients/publishedprices.py

import re
import time
from datetime import datetime
import logging
import requests
from bs4 import BeautifulSoup

from database.repository import get_publishing_sources



logger = logging.getLogger(__name__)

class PublishedPricesClient:

    BASE_URL = "https://url.publishedprices.co.il"

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = 30

    FILE_RE = re.compile(
        r"^(?P<file_type>[A-Za-z]+)"
        r"(?P<chain_id>\d+)-"
        r"(?P<store_id>\d+)-"
        r"(?P<timestamp>\d{12})"
        r"\.gz$"
    )

    def __init__(
        self,
        supermarket_name: str,
    ):
        self.supermarket_name = supermarket_name

        self.username = None
        self.password = ""

        self.session = requests.Session()
        self.csrf_token = None

    def _get_credentials(self) -> None:

        sources = get_publishing_sources(
            "publishedprices"
        )

        source = next(
            (
                source
                for source in sources
                if source["name"] == self.supermarket_name
            ),
            None,
        )

        if source is None:
            raise ValueError(
                f"No publishedprices source found for "
                f"'{self.supermarket_name}'"
            )

        credentials = source.get(
            "credentials",
            []
        )

        if not credentials:
            raise ValueError(
                f"No credentials found for "
                f"'{self.supermarket_name}'"
            )

        credential = credentials[0]

        self.username = credential["username"]
        self.password = credential.get(
            "password",
            ""
        )

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

                return response

            except (
                requests.Timeout,
                requests.ConnectionError,
            ) as exc:

                last_exc = exc

                print(
                    f"Attempt "
                    f"{attempt + 1}/"
                    f"{self.MAX_RETRIES} "
                    f"failed for {url}: {exc}"
                )

                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(
                        self.BACKOFF_SECONDS[attempt]
                    )

            except requests.HTTPError:

                raise

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
            for keyword in ("invalid", "incorrect", "locked", "disabled", "error", "expired", "denied"):
                idx = response.text.lower().find(keyword)
                if idx != -1:
                    logger.warning(
                        "DEBUG found '%s' near: %s",
                        keyword,
                        response.text[max(0, idx-100):idx+200],
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

    def get_files(self, cd: str = "/") -> dict:

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
                "iDisplayLength": "1000",
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

    def find_latest_files(
        self,
        response_json: dict,
    ) -> list[dict]:

        latest_by_store_and_type = {}

        for file in response_json.get(
            "aaData",
            [],
        ):

            filename = file.get("fname")

            if not filename:
                continue

            match = self.FILE_RE.match(
                filename
            )

            if not match:
                continue

            timestamp = datetime.strptime(
                match.group("timestamp"),
                "%Y%m%d%H%M",
            )

            file_type = match.group(
                "file_type"
            )

            chain_id = match.group(
                "chain_id"
            )

            store_id = match.group(
                "store_id"
            )

            key = (
                file_type,
                chain_id,
                store_id,
            )

            existing = (
                latest_by_store_and_type.get(
                    key
                )
            )

            if (
                existing is None
                or timestamp > existing["timestamp"]
            ):
                latest_by_store_and_type[key] = {
                    "filename": filename,
                    "file_type": file_type,
                    "chain_id": chain_id,
                    "store_id": store_id,
                    "timestamp": timestamp,
                    "size": file.get("size"),
                    "url": (
                        f"{self.BASE_URL}"
                        f"/file/d/{filename}"
                    ),
                }

        return list(
            latest_by_store_and_type.values()
        )

    def check(self) -> list[dict]:

        self._get_credentials()

        self.login()

        response_json = self.get_files()

        return self.find_latest_files(
            response_json
        )