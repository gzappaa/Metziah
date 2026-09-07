import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from lxml import html as lxml_html


logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    """
    One possible downloadable file.

    The client only extracts HTML structure and the filename
    according to the configured filename source.

    It does NOT decide whether the candidate is a Stores file.
    """

    text: str
    href: str
    filename: str | None = None


class HtmlFileLinkClient:
    """
    Generic client for publishers whose file discovery works through
    server-rendered HTML pages.

    Extraction modes:

    anchor:
        Extracts one Candidate per <a href>.

    row:
        Extracts one Candidate per table row containing a download
        link. The filename is taken from the configured filename
        column when available.

    Filename sources:

    path:
        Filename comes from the URL path.

    query:
        Filename comes from a URL query parameter.

    row:
        Filename comes from the table row/cell.

    This client contains NO publisher-specific filename regex,
    Stores matching, chain ID parsing, date parsing, latest-file
    logic, or pagination.
    """

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = httpx.Timeout(30.0)

    def __init__(
        self,
        name: str,
        base_url: str,
        extraction_mode: str = "anchor",
        filename_column: str | None = None,
        filename_source: str = "path",
        filename_param: str | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.extraction_mode = extraction_mode
        self.filename_column = filename_column
        self.filename_source = filename_source
        self.filename_param = filename_param

    async def _get_with_retry(
        self,
        url: str,
        params: dict | None = None,
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

    def _extract_filename(
        self,
        href: str,
        text: str,
    ) -> str | None:
        """
        Extract a filename from an anchor according to
        filename_source.

        Used for anchor-based publishers.
        """

        if self.filename_source == "path":

            path = urlparse(href).path

            filename = path.rsplit("/", 1)[-1]

            return filename or None

        if self.filename_source == "query":

            if not self.filename_param:
                raise ValueError(
                    "filename_param is required when "
                    "filename_source='query'"
                )

            query = parse_qs(
                urlparse(href).query
            )

            values = query.get(
                self.filename_param
            )

            if not values:
                return None

            return values[0].strip() or None

        if self.filename_source == "row":
            return text or None

        raise ValueError(
            f"Unsupported filename source: "
            f"{self.filename_source!r}. "
            f"Expected 'path', 'query', or 'row'."
        )

    def _extract_anchor_mode(
        self,
        tree,
        page_url: str,
    ) -> list[Candidate]:

        candidates = []

        for anchor in tree.xpath("//a[@href]"):

            href = (
                anchor.get("href") or ""
            ).strip()

            if not href:
                continue

            absolute_href = urljoin(
                page_url,
                href,
            )

            text = (
                anchor.text_content() or ""
            ).strip()

            filename = self._extract_filename(
                absolute_href,
                text,
            )

            candidates.append(
                Candidate(
                    text=text,
                    href=absolute_href,
                    filename=filename,
                )
            )

        return candidates

    def _extract_row_mode(
        self,
        tree,
        page_url: str,
    ) -> list[Candidate]:

        candidates = []

        for table in tree.xpath("//table"):

            headers = [
                (
                    header.text_content() or ""
                ).strip()
                for header in table.xpath(
                    ".//thead//th"
                )
            ]

            filename_index = None

            if self.filename_column:
                for index, header in enumerate(headers):

                    if header == self.filename_column:
                        filename_index = index
                        break

            for row in table.xpath(".//tr"):

                cells = row.xpath("./td")

                if not cells:
                    continue

                anchors = row.xpath(
                    ".//a[@href]"
                )

                if not anchors:
                    continue

                href = (
                    anchors[0].get("href") or ""
                ).strip()

                if not href:
                    continue

                absolute_href = urljoin(
                    page_url,
                    href,
                )

                if (
                    filename_index is not None
                    and filename_index < len(cells)
                ):
                    filename = (
                        cells[filename_index]
                        .text_content()
                        .strip()
                    )
                else:
                    filename = None

                    for cell in cells:
                        cell_text = (
                            cell.text_content()
                            or ""
                        ).strip()

                        if cell_text.startswith(
                            ("Price", "Promo", "Stores")
                        ):
                            filename = cell_text
                            break

                candidates.append(
                    Candidate(
                        text=filename,
                        href=absolute_href,
                        filename=filename or None,
                    )
                )

        return candidates

    async def get_candidates(
        self,
        params: dict | None = None,
    ) -> list[Candidate]:

        response = await self._get_with_retry(
            self.base_url,
            params=params,
        )

        tree = lxml_html.fromstring(
            response.text
        )

        if self.extraction_mode == "anchor":

            candidates = self._extract_anchor_mode(
                tree,
                str(response.url),
            )

        elif self.extraction_mode == "row":

            candidates = self._extract_row_mode(
                tree,
                str(response.url),
            )

        else:

            raise ValueError(
                f"Unsupported extraction mode: "
                f"{self.extraction_mode!r}. "
                f"Expected 'anchor' or 'row'."
            )

        logger.info(
            "%s: %d candidates on %s",
            self.name,
            len(candidates),
            response.url,
        )

        return candidates