# clients/laibcatalog.py

import asyncio
import logging

import httpx

from database.repository import get_publishing_sources


logger = logging.getLogger(__name__)


class LaibcatalogClient:

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = httpx.Timeout(30.0)

    def __init__(
        self,
        supermarket_name: str,
    ):
        self.supermarket_name = supermarket_name

        self.source_url = None
        self.chain_id = None

    def _get_source(self) -> dict:

        sources = get_publishing_sources(
            "laibcatalog"
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
                f"No laibcatalog source found for "
                f"'{self.supermarket_name}'"
            )

        return source

    def _configure(self) -> None:

        source = self._get_source()

        self.source_url = source["url"]
        self.chain_id = source["chain_id"]

        logger.info(
            "Configured Laibcatalog source: %s",
            self.supermarket_name,
        )

        logger.info(
            "Source URL: %s",
            self.source_url,
        )

        logger.info(
            "Chain ID: %s",
            self.chain_id,
        )

    async def _get_with_retry(
        self,
        url: str,
        params=None,
    ) -> httpx.Response:

        last_exc = None

        for attempt in range(self.MAX_RETRIES):

            try:

                async with httpx.AsyncClient(
                    timeout=self.TIMEOUT
                ) as client:

                    response = await client.get(
                        url,
                        params=params,
                    )

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
        branch_number=None,
    ) -> dict:

        if self.chain_id is None:
            self._configure()

        params = {
            "edi": self.chain_id,
        }

        if branch_number:
            params["branchNumber"] = branch_number

        logger.info(
            "Requesting file list (branch=%s)",
            branch_number or "all",
        )

        response = await self._get_with_retry(
            f"{self.source_url.rstrip('/')}/webapi/api/getfiles",
            params=params,
        )

        return response.json()

    def build_download_url(
        self,
        filename: str,
    ) -> str:

        if self.chain_id is None:
            self._configure()

        return (
            f"{self.source_url.rstrip('/')}"
            f"/webapi/{self.chain_id}/{filename}"
        )

    async def download_file(
        self,
        url: str,
    ) -> bytes:

        response = await self._get_with_retry(url)

        return response.content

    async def check(self) -> dict:

        self._configure()

        files = await self.get_files()

        return {
            "name": self.supermarket_name,
            "url": self.source_url,
            "chain_id": self.chain_id,
            "files": files,
        }