import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from lxml import html as lxml_html


logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    text: str
    href: str


class HtmlFileLinkClient:
    """
    Generic client for publishers whose file discovery works by
    scanning a plain server-rendered HTML page for links to price
    feed files (no JSON API, no JS-embedded data).

    This client does NOT know what a valid filename looks like — it
    has no regex and applies no filtering. It just returns every
    candidate (link text + resolved URL) found on the page. The
    caller (e.g. stores.py's find_latest_stores_file_* functions,
    or the equivalent for price.py/promo.py later) is responsible
    for matching candidates against the filename pattern and
    deciding which one is "latest". This keeps the client reusable
    for Stores, Price, Promo, etc. without needing to change it.

    --------------------------------------------------------------
    Publishers using extraction_mode="anchor" (default):
    The filename appears directly in the <a href> or its link text,
    so scanning every <a> tag on the page is enough to find every
    file reference.

      - Wolt
          Two-level HTML: an index page lists date pages, each date
          page lists file links directly. Caller is responsible for
          first fetching the index, picking a date, then fetching
          that date's page with this client.
      - Hazi Hinam (שופ.חצי חינם)
          Server-rendered table, paginated (?p=, ?s=, ?d=, ?t=, ?f=).
          href is a direct Azure Blob Storage URL.
      - Netiv Hesed / Barchal / ברכלטוב / שירה מרקט
          Single filtered page (?BranchTypeNumber=, ?StoreNumber=,
          ?FileType=, ?Date=, ?Search=). href is this publisher's
          own /Prices/Download?fileName=... proxy endpoint.
      - Super-Pharm
          Server-rendered table, paginated (?page=). href is this
          publisher's own /Download/<filename>?bucketName=... proxy.
      - Shufersal
          Server-rendered table (ASP.NET MVC WebGrid), paginated
          (?page=). href is a complete Azure Blob SAS URL — must be
          used exactly as extracted, never reconstructed, since it
          contains an expiring auth token.

    --------------------------------------------------------------
    Publishers using extraction_mode="row":
    The filename is NOT in the href or link text at all — it only
    appears as plain text in a separate table cell. The download
    link itself is an opaque ID with no filename info
    (e.g. /downloadFile/<UUID>). So this mode scans each <tr>,
    collects all non-empty cell text as separate candidates, and
    pairs them with that row's single download href. The caller's
    regex then figures out which cell text was actually the
    filename.

      - City Market (סיטי מרקט)
          Server-rendered table, paginated (?p=, ?s=, ?d=, ?t=, ?f=).
          Filename is plain text in its own <td>; download href is
          /downloadFile/<UUID> with the real filename only exposed
          later via Content-Disposition on download, if needed.
          NOTE: City Market's filenames come in two formats (see
          stores.py regex notes) — one with a hyphenated date-time
          and a .gz/.xml extension, one with no extension and a
          concatenated 12-digit timestamp. Both must be matched.

    --------------------------------------------------------------
    NOT covered by this client (different protocols entirely,
    handled by their own clients):
      - Carrefour: file list is embedded in a JS variable in the
        HTML, not in anchors or table rows — needs its own parser.
      - K.T.M / Mishnat Yosef: JSON API (Cloudflare Worker) returning
        direct URLs — see clients/ktm.py (or similar).
      - Laibcatalog, BinaProjects, PublishedPrices: existing clients,
        unrelated protocols (JSON API / ASPX endpoints), unchanged.
    """

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [2, 4, 8]
    TIMEOUT = httpx.Timeout(30.0)

    def __init__(
        self,
        name: str,
        base_url: str,
        extraction_mode: str = "anchor",
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.extraction_mode = extraction_mode

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

    def _extract_anchor_mode(
        self,
        tree,
        page_url: str,
    ) -> list[Candidate]:
        """
        Scans every <a href> on the page. Used for publishers where
        the filename is discoverable directly from the link itself
        (href and/or visible link text) — see class docstring for
        which publishers this covers.
        """

        candidates = []

        for anchor in tree.xpath("//a[@href]"):

            href = anchor.get("href", "").strip()
            text = (anchor.text or "").strip()

            if not href:
                continue

            candidates.append(
                Candidate(
                    text=text,
                    href=urljoin(page_url, href),
                )
            )

        return candidates

    def _extract_row_mode(
        self,
        tree,
        page_url: str,
    ) -> list[Candidate]:
        """
        Scans every <tr>, pairing each non-empty cell's text with
        that row's download href. Needed specifically for City
        Market, where the filename lives in a plain-text table cell
        separate from the (opaque) download link — see class
        docstring.
        """

        candidates = []

        for row in tree.xpath("//tr"):

            cell_texts = [
                (cell.text_content() or "").strip()
                for cell in row.xpath(".//td")
            ]

            anchors = row.xpath(".//a[@href]")

            if not anchors:
                continue

            href = urljoin(
                page_url,
                anchors[0].get("href", "").strip(),
            )

            for text in cell_texts:

                if text:

                    candidates.append(
                        Candidate(
                            text=text,
                            href=href,
                        )
                    )

        return candidates

    async def get_candidates(
        self,
        params: dict | None = None,
    ) -> list[Candidate]:
        """
        Fetches self.base_url (with optional query params for
        pagination/filtering — see class docstring for each
        publisher's specific param names) and returns every raw
        candidate found via the configured extraction_mode.

        Returns NO filtering, NO regex matching — see class
        docstring for why.
        """

        response = await self._get_with_retry(
            self.base_url,
            params=params,
        )

        tree = lxml_html.fromstring(response.text)

        if self.extraction_mode == "row":
            candidates = self._extract_row_mode(tree, str(response.url))
        else:
            candidates = self._extract_anchor_mode(tree, str(response.url))

        logger.info(
            "%s: %d candidates on %s",
            self.name,
            len(candidates),
            response.url,
        )

        return candidates