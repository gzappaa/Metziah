# clients/binaprojects.py

import logging
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

from database.repository import get_publishing_sources


logger = logging.getLogger(__name__)


class BinaProjectsClient:

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = 30

    def __init__(
        self,
        supermarket_name: str,
    ):
        self.supermarket_name = supermarket_name

        self.source_url = None
        self.base_url = None

        self.session = requests.Session()

    def _get_source(self) -> dict:

        sources = get_publishing_sources(
            "binaprojects"
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
                f"No binaprojects source found for "
                f"'{self.supermarket_name}'"
            )

        return source

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

        raise last_exc

    def get_main_page(self) -> str:

        response = self._get_with_retry(
            self.source_url
        )

        logger.info(
            "GET %s -> %d",
            response.url,
            response.status_code,
        )

        return response.text

    def get_hok_files(
        self,
        store: str = "",
        date: str = "",
        file_type: int = 0,
    ) -> list[dict]:

        hok_url = (
            f"{self.base_url}/MainIO_Hok.aspx"
        )

        response = self._get_with_retry(
            hok_url,
            params={
                "wReshet": "",
                "WStore": store,
                "WDate": date,
                "WFileType": file_type,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        logger.info(
            "GET %s -> HTTP %d",
            response.url,
            response.status_code,
        )

        return response.json()

    def get_latest_store_files(
        self,
    ) -> list[dict]:

        files = self.get_hok_files()

        latest = {}

        for file in files:

            store = file["Store"].strip()

            if not store:
                continue

            date = datetime.strptime(
                file["DateFile"].strip(),
                "%H:%M %d/%m/%Y",
            )

            key = (
                store,
                file["TypeFile"],
            )

            if (
                key not in latest
                or date > latest[key]["datetime"]
            ):
                latest[key] = {
                    "store": store,
                    "file_name": file["FileNm"],
                    "file_type": file["TypeFile"],
                    "file_extension": file["TypeExpFile"],
                    "date": file["DateFile"].strip(),
                    "datetime": date,
                }

        return list(latest.values())

    def check(self) -> dict:

        source = self._get_source()

        self.source_url = source["url"]

        parsed = urlparse(
            self.source_url
        )

        self.base_url = (
            f"{parsed.scheme}://"
            f"{parsed.netloc}"
        )

        logger.info(
            "Checking BinaProjects source: %s",
            self.supermarket_name,
        )

        logger.info(
            "Source URL: %s",
            self.source_url,
        )

        logger.info(
            "Base URL: %s",
            self.base_url,
        )

        main_page = self.get_main_page()

        files = self.get_latest_store_files()

        return {
            "name": self.supermarket_name,
            "url": self.source_url,
            "base_url": self.base_url,
            "main_page": main_page,
            "latest_store_files": files,
        }