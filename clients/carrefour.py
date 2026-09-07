# clients/carrefour.py

import asyncio
import logging
import re
import json

import httpx


logger = logging.getLogger(__name__)


class CarrefourClient:

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = httpx.Timeout(30.0)

    BASE_URL = "https://prices.carrefour.co.il"

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

    async def get_files(
        self,
        date: str | None = None,
    ) -> dict:

        url = self.base_url

        if date:
            url = f"{url}/?date={date}"

        response = await self._get_with_retry(url)

        html = response.text

        path_match = re.search(
            r"const\s+path\s*=\s*['\"]([^'\"]+)['\"]",
            html,
        )

        files_match = re.search(
            r"const\s+files\s*=\s*(\[[\s\S]*?\])\s*;",
            html,
        )

        if not path_match:
            raise ValueError(
                "Could not find Carrefour 'path' in HTML"
            )

        if not files_match:
            raise ValueError(
                "Could not find Carrefour 'files' in HTML"
            )

        path = path_match.group(1)

        files = json.loads(
            files_match.group(1)
        )

        logger.info(
            "Carrefour: found %d files for path %s",
            len(files),
            path,
        )

        return {
            "path": path,
            "files": files,
        }

    async def download_file(
        self,
        url: str,
    ) -> bytes:

        response = await self._get_with_retry(url)

        return response.content