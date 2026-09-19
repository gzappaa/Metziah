# clients/binaprojects.py

import logging
import time
from urllib.parse import urlparse, urlunparse

import requests


logger = logging.getLogger(__name__)


class BinaProjectsClient:

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = 30

    def __init__(
        self,
        source_url: str,
    ):
        self.source_url = source_url.rstrip("/")

        parsed = urlparse(self.source_url)

        self.base_url = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                "",
                "",
                "",
                "",
            )
        )

        self.session = requests.Session()

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

                logger.info(
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

    # WFileType:
    # 1 = stores
    # 2 = prices
    # 3 = promo
    # 4 = pricefull
    # 5 = promofull

    def get_hok_files(
        self,
        store: str = "",
        date: str = "",
        file_type: int = 0,
    ) -> list[dict]:

        response = self._get_with_retry(
            f"{self.base_url}/MainIO_Hok.aspx",
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

        return response.json()

    def get_download_url(
        self,
        filename: str,
    ) -> str:

        response = self._get_with_retry(
            f"{self.base_url}/Download.aspx",
            params={
                "FileNm": filename,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        data = response.json()

        if not data or not data[0].get("SPath"):
            raise RuntimeError(
                f"No download URL returned for {filename}"
            )

        return data[0]["SPath"]

    def download_file(
        self,
        filename: str,
    ) -> bytes:

        direct_url = f"{self.base_url}/Download/{filename}"

        try:

            response = self._get_with_retry(
                direct_url,
            )

            return response.content

        except requests.HTTPError:

            logger.warning(
                "Direct Bina download failed for %s, "
                "falling back to Download.aspx",
                filename,
            )

            download_url = self.get_download_url(
                filename,
            )

            return self._get_with_retry(
                download_url,
            ).content