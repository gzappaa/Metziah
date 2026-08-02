import asyncio
import logging

import httpx


logger = logging.getLogger(__name__)


class LaibcatalogClient:

    BASE_URL = "https://laibcatalog.co.il"

    TIMEOUT = httpx.Timeout(30.0)

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]


    def __init__(self, chain_id):
        self.chain_id = chain_id


    async def _get_with_retry(self, url, params=None):

        last_exc = None

        for attempt in range(self.MAX_RETRIES):

            try:

                async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:

                    response = await client.get(url, params=params)

                    response.raise_for_status()

                    return response

            except (httpx.TimeoutException, httpx.ConnectError) as e:

                last_exc = e

                logger.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    url,
                    e,
                )

                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.BACKOFF_SECONDS[attempt])

            except httpx.HTTPStatusError as e:

                logger.error(
                    "HTTP error for %s: %s",
                    url,
                    e,
                )

                raise

        logger.error(
            "All %d attempts failed for %s",
            self.MAX_RETRIES,
            url,
        )

        raise last_exc


    async def get_files(self, branch_number=None):

        params = {
            "edi": self.chain_id
        }

        if branch_number:
            params["branchNumber"] = branch_number

        logger.info(
            "Requesting file list (branch=%s)",
            branch_number or "all",
        )

        response = await self._get_with_retry(
            f"{self.BASE_URL}/webapi/api/getfiles",
            params=params
        )

        return response.json()


    def build_download_url(self, filename):

        return (
            f"{self.BASE_URL}"
            f"/webapi/{self.chain_id}/{filename}"
        )


    async def download_file(self, url):

        response = await self._get_with_retry(url)

        return response.content