# clients/wolt.py

import asyncio
import logging

import httpx
from lxml import html as lxml_html


logger = logging.getLogger(__name__)


class WoltClient:

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = httpx.Timeout(30.0)

    BASE_URL = (
        "https://wm-gateway.wolt.com/"
        "isr-prices/public/v1"
    )

    def __init__(self):
        self.base_url = self.BASE_URL

    async def _get_with_retry(
        self,
        url: str,
    ) -> httpx.Response:

        last_exc = None

        for attempt in range(self.MAX_RETRIES):

            try:

                async with httpx.AsyncClient(
                    timeout=self.TIMEOUT
                ) as client:

                    response = await client.get(url)

                    response.raise_for_status()

                    logger.debug(
                        "GET %s -> HTTP %d",
                        response.url,
                        response.status_code,
                    )

                    return response

            except (
                httpx.TimeoutException,
                httpx.ConnectError,
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

                    await asyncio.sleep(
                        self.BACKOFF_SECONDS[attempt]
                    )

            except httpx.HTTPStatusError:

                raise

        logger.error(
            "All %d attempts failed for %s",
            self.MAX_RETRIES,
            url,
        )

        raise last_exc

    async def get_date_pages(self) -> list[str]:
        """
        Return the URLs of all available Wolt date pages.
        """

        response = await self._get_with_retry(
            f"{self.base_url}/index.html"
        )

        tree = lxml_html.fromstring(
            response.text
        )

        date_pages = []

        for anchor in tree.xpath("//a[@href]"):

            href = (
                anchor.get("href") or ""
            ).strip()

            if not href:
                continue

            if not href.endswith(".html"):
                continue

            date_pages.append(
                httpx.URL(
                    response.url
                ).join(href).__str__()
            )

        logger.info(
            "Wolt: found %d date pages",
            len(date_pages),
        )

        return date_pages

    async def get_files(
        self,
        date_page_url: str,
    ) -> list[str]:
        """
        Return the URLs of all files listed on a Wolt
        date page.
        """

        response = await self._get_with_retry(
            date_page_url
        )

        tree = lxml_html.fromstring(
            response.text
        )

        files = []

        for anchor in tree.xpath("//a[@href]"):

            href = (
                anchor.get("href") or ""
            ).strip()

            if not href:
                continue

            if not href.endswith(".gz"):
                continue

            files.append(
                httpx.URL(
                    response.url
                ).join(href).__str__()
            )

        logger.info(
            "Wolt: found %d files on %s",
            len(files),
            date_page_url,
        )

        return files

    async def download_file(
        self,
        url: str,
    ) -> bytes:

        response = await self._get_with_retry(
            url
        )

        return response.content

    async def check(self) -> dict:
        """
        Check Wolt connectivity and return discovered
        date pages and files from the latest date page.
        """

        date_pages = await self.get_date_pages()

        result = {
            "url": f"{self.base_url}/index.html",
            "date_pages": date_pages,
            "files": [],
        }

        if date_pages:

            result["files"] = await self.get_files(
                date_pages[0]
            )

        return result