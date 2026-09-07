# clients/mishnatyosef.py

import asyncio
import logging

import httpx


logger = logging.getLogger(__name__)


class MishnatYosefClient:

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = httpx.Timeout(30.0)

    LIST_URL = (
        "https://list-files.w5871031-kt.workers.dev/"
    )

    def __init__(self):
        self.list_url = self.LIST_URL

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

                    logger.info(
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

    async def get_files(self) -> list[dict]:
        """
        Return the file metadata from the Mishnat Yosef
        listing endpoint.
        """

        response = await self._get_with_retry(
            self.list_url
        )

        files = response.json()

        if not isinstance(files, list):
            raise ValueError(
                "Mishnat Yosef file listing response "
                "is not a JSON array"
            )

        logger.info(
            "Mishnat Yosef: found %d files",
            len(files),
        )

        return files

    async def download_file(
        self,
        url: str,
    ) -> bytes:
        """
        Download a file using the direct URL returned
        by the listing endpoint.
        """

        response = await self._get_with_retry(url)

        return response.content