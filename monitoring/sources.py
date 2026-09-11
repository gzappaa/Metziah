# monitoring/sources.py

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from logging_config import (
    setup_general_logging,
    setup_isolated_logging,
)


URL = (
    "https://openapi-gc.digital.gov.il/pub/cio/govil/rest/contentpage/v1/"
    "api/content-pages/cpfta_prices_regulations?culture=he"
)

HEADERS = {
    "Accept": "*/*",
    "Origin": "https://www.gov.il",
    "Referer": "https://www.gov.il/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "X-Client-Id": "9KFgciHHGDyNiqz5MdQS0eK2ApeJYMc6YnElUICpN1atirZc",
}

OUTPUT_FILE = Path(__file__).parent / "data" / "supermarket_sources.json"

CHAINS_FILE = Path(__file__).parent.parent / "data" / "reference" / "chains.json"


SOURCE_TYPES = {
    "publishedprices.co.il": "publishedprices",
    "laibcatalog.co.il": "laibcatalog",
    "binaprojects.com": "binaprojects",
}


HARDCODED_SOURCE_TYPES = {
    "https://shop.hazi-hinam.co.il/Prices": "html_filelink",
    "http://prices.super-pharm.co.il/": "html_filelink",
    "http://prices.shufersal.co.il/": "html_filelink",
    "https://www.citymarket-shops.co.il/": "html_filelink",
    "https://app.netiv-hesed.com/": "html_filelink",
}


setup_general_logging()

logger = logging.getLogger(__name__)

source_changes_logger = setup_isolated_logging(
    "source_changes"
)

chains_registry_logger = setup_isolated_logging(
    "chains_registry_changes"
)


def get_domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def get_source_type(url: str) -> str:

    if url in HARDCODED_SOURCE_TYPES:
        return HARDCODED_SOURCE_TYPES[url]

    hostname = get_domain(url)

    for domain, source_type in SOURCE_TYPES.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return source_type

    return "unclassified"


def get_laibcatalog_chain_id(url: str) -> str:
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    match = re.search(
        r"DEFAULT_EDI\s*=\s*[\"'](\d+)[\"']",
        response.text,
        re.IGNORECASE,
    )

    if match is None:
        raise RuntimeError(
            f"Could not find Laibcatalog chain ID in {url}"
        )

    chain_id = match.group(1)

    logger.info(
        "Found Laibcatalog chain ID %s for %s",
        chain_id,
        url,
    )

    return chain_id


def extract_credentials(info: str | None) -> list[dict]:
    """
    Extract username/password pairs from the government's
    free-form 'info' text.

    Examples handled:

        שם משתמש:doralon
        שם משתמש: TivTaam
        שם משתמש - SalachD
        שם משתמש- politzer

        User- yuda_ho
        Username: foo

        סיסמא: 12345
        סיסמא - abc
        Password- xyz

    A password is considered empty when the government says
    that no password is required.
    """

    if not info:
        return []

    text = re.sub(r"\s+", " ", info).strip()

    username_pattern = re.compile(
        r"(?:שם\s*משתמש|username|user)"
        r"\s*[:\-]?\s*"
        r"([^\s:;,]+)",
        re.IGNORECASE,
    )

    username_matches = list(
        username_pattern.finditer(text)
    )

    credentials = []

    for index, username_match in enumerate(username_matches):
        username = username_match.group(1)

        start = username_match.end()

        if index + 1 < len(username_matches):
            end = username_matches[index + 1].start()
        else:
            end = len(text)

        section = text[start:end]

        password_match = re.search(
            r"(?:סיסמא|סיסמה|password)"
            r"\s*[:\-]?\s*"
            r"(.+?)(?="
            r"\s+(?:שם\s*משתמש|username|user)\b"
            r"|$"
            r")",
            section,
            re.IGNORECASE,
        )

        password = ""

        if password_match:
            password_value = password_match.group(1).strip()

            if "אין צורך" not in password_value:
                password = password_value

        credentials.append(
            {
                "username": username,
                "password": password,
            }
        )

    return credentials


def merge_credentials(
    existing: list[dict],
    new: list[dict],
) -> list[dict]:
    """
    Merge credentials while removing duplicates.

    Credentials are considered identical when both username
    and password are identical.
    """

    merged = {}

    for credential in existing + new:
        username = credential.get("username", "")
        password = credential.get("password", "")

        if not username:
            continue

        merged[(username, password)] = {
            "username": username,
            "password": password,
        }

    return list(
        merged.values()
    )


def source_identity(
    source_type: str,
    url: str,
) -> tuple[str, str]:
    """
    Return the identity used to deduplicate sources.

    PublishedPrices may expose multiple subdomains that represent
    the same publishing source, so all PublishedPrices URLs use
    the canonical publishedprices.co.il identity.

    Laibcatalog and BinaProjects sources are identified by their
    actual hostname, allowing genuinely different subdomains to
    remain separate.
    """

    hostname = get_domain(url)

    if source_type == "publishedprices":
        return (
            source_type,
            "publishedprices.co.il",
        )

    if source_type in {
        "laibcatalog",
        "binaprojects",
    }:
        return (
            source_type,
            hostname,
        )

    return (
        source_type,
        url,
    )


def scrape_supermarket_sources(
    existing: dict | None = None,
) -> list[dict]:

    logger.info("Starting supermarket sources scrape")

    logger.info("Getting supermarket sources page")

    response = requests.get(
        URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    logger.info(
        "Government API request successful: HTTP %s",
        response.status_code,
    )

    page = response.json()

    html = page["contentMain"]["htmlContents"][0]["sectionData"]

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    table = soup.find("table")

    if table is None:
        logger.error(
            "Could not find the supermarket table"
        )

        raise RuntimeError(
            "Could not find the supermarket table"
        )

    supermarkets = []

    for row in table.find("tbody").find_all("tr"):
        cells = row.find_all("td")

        if len(cells) != 3:
            continue

        name = cells[0].get_text(
            " ",
            strip=True,
        )

        links = [
            {
                "label": link.get_text(
                    " ",
                    strip=True,
                ),
                "url": link["href"],
            }
            for link in cells[1].find_all(
                "a",
                href=True,
            )
        ]

        info = cells[2].get_text(
            " ",
            strip=True,
        ) or None

        credentials = extract_credentials(info)

        sources_by_identity = {}

        for link in links:
            url = link["url"]

            source_type = get_source_type(
                url
            )

            identity = source_identity(
                source_type,
                url,
            )

            source = sources_by_identity.get(
                identity
            )

            if source is None:
                source = {
                    "type": source_type,
                    "url": url,
                }

                if source_type == "laibcatalog":

                    existing_supermarket = (
                        (existing or {}).get(name)
                    )

                    existing_source = None

                    if existing_supermarket:
                        existing_source = next(
                            (
                                old_source
                                for old_source
                                in existing_supermarket.get(
                                    "sources",
                                    [],
                                )
                                if old_source.get("type")
                                == "laibcatalog"
                            ),
                            None,
                        )

                    if (
                        existing_source
                        and existing_source.get("chain_id")
                    ):
                        source["chain_id"] = (
                            existing_source["chain_id"]
                        )
                    else:
                        source["chain_id"] = (
                            get_laibcatalog_chain_id(url)
                        )

                sources_by_identity[identity] = source

            if credentials:
                source["credentials"] = merge_credentials(
                    source.get(
                        "credentials",
                        [],
                    ),
                    credentials,
                )

        supermarkets.append(
            {
                "name": name,
                "sources": list(
                    sources_by_identity.values()
                ),
            }
        )

    logger.info(
        "Scraped %d supermarket entries",
        len(supermarkets),
    )

    source_counts = {}
    credential_count = 0

    for supermarket in supermarkets:
        for source in supermarket["sources"]:
            source_type = source["type"]

            source_counts[source_type] = (
                source_counts.get(
                    source_type,
                    0,
                )
                + 1
            )

            credential_count += len(
                source.get(
                    "credentials",
                    [],
                )
            )

    logger.info(
        "Found sources by type: %s",
        source_counts,
    )

    logger.info(
        "Extracted %d credentials",
        credential_count,
    )

    return supermarkets


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        supermarkets = json.load(file)

    return {
        supermarket["name"]: supermarket
        for supermarket in supermarkets
    }

def load_chains(path: Path) -> dict[str, dict]:
    if not path.exists():
        logger.warning(
            "chains.json not found at %s",
            path,
        )
        return {}

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)



def load_chain_gov_names(
    chains: dict[str, dict],
) -> set[str]:
    """
    Load the set of Chain_name_gov_page values currently
    present in the manually-curated chains.json registry.
    """

    return {
        entry.get("Chain_name_gov_page", "")
        for entry in chains.values()
        if entry.get("Chain_name_gov_page")
    }

def check_chain_credentials(
    supermarkets: list[dict],
    chains: dict[str, dict],
) -> list[str]:
    """
    Validate credentials scraped from the government page
    against credentials stored in chains.json.

    For each government username:
        - the username must exist in chains.json under the
          same Chain_name_gov_page
        - the password must match

    Passwords are never included in logs.
    """

    changes = []

    for supermarket in supermarkets:
        gov_name = supermarket["name"]

        # Credentials are currently attached to every source
        # belonging to the supermarket, so take them from the
        # first source that contains them.
        government_credentials = next(
            (
                source.get("credentials", [])
                for source in supermarket.get("sources", [])
                if source.get("credentials")
            ),
            [],
        )

        if not government_credentials:
            continue

        registry_credentials = []

        for chain in chains.values():
            if chain.get("Chain_name_gov_page") != gov_name:
                continue

            credential = chain.get("credentials")

            if credential:
                registry_credentials.append(credential)

        registry_by_username = {
            credential.get("username"): credential
            for credential in registry_credentials
            if credential.get("username")
        }

        for credential in government_credentials:
            username = credential.get("username")
            password = credential.get("password", "")

            if not username:
                continue

            registry_credential = registry_by_username.get(
                username
            )

            if registry_credential is None:
                changes.append(
                    f"CREDENTIAL MISSING FROM chains.json: "
                    f"{gov_name} | user: {username}"
                )
                continue

            if (
                registry_credential.get("password", "")
                != password
            ):
                changes.append(
                    f"CHANGED PASSWORD: "
                    f"{gov_name} | user: {username}"
                )

    return changes


def check_chains_registry(
    supermarkets: list[dict],
    chain_names: set[str],
) -> list[str]:
    """
    Compare the freshly scraped gov-page supermarket names
    against the manually-curated chains.json registry.

    This does not modify chains.json. It only reports:
        - gov-page names with no matching chains.json entry
          (a new chain needs to be added manually)
        - chains.json entries whose gov-page name no longer
          appears in the current gov scrape (possibly renamed
          or delisted upstream)

    Credential-level drift is checked separately by
    check_chain_credentials().
    """

    scraped_names = {
        supermarket["name"]
        for supermarket in supermarkets
    }

    changes = []

    for name in sorted(scraped_names - chain_names):
        changes.append(
            f"MISSING FROM chains.json: {name}"
        )

    for name in sorted(chain_names - scraped_names):
        changes.append(
            f"STALE IN chains.json (no longer in gov scrape): {name}"
        )

    return changes


def credential_signature(
    credentials: list[dict],
) -> tuple:
    """
    Create a comparable representation of credentials.

    Passwords are included for comparison but never logged.
    """

    return tuple(
        sorted(
            (
                credential.get("username", ""),
                credential.get("password", ""),
            )
            for credential in credentials
        )
    )


def source_signature(source: dict) -> tuple:
    """
    Create a comparable representation of a source.

    This allows us to detect changes to:
        - source type
        - URL
        - credentials
    """

    credentials = source.get(
        "credentials",
        [],
    )

    return (
        source.get("type"),
        source.get("url"),
        credential_signature(credentials),
    )


def compare_sources(
    old: dict,
    new: list[dict],
) -> list[str]:

    changes = []

    old_names = set(old.keys())

    new_by_name = {
        supermarket["name"]: supermarket
        for supermarket in new
    }

    new_names = set(new_by_name.keys())

    # --------------------------------------------------
    # New supermarkets
    # --------------------------------------------------

    for name in sorted(new_names - old_names):
        changes.append(
            f"NEW SUPERMARKET: {name}"
        )

        for source in new_by_name[name]["sources"]:
            changes.append(
                f"NEW SOURCE: {name} | "
                f"{source['type']} | "
                f"{source['url']}"
            )

    # --------------------------------------------------
    # Removed supermarkets
    # --------------------------------------------------

    for name in sorted(old_names - new_names):
        changes.append(
            f"REMOVED SUPERMARKET: {name}"
        )

    # --------------------------------------------------
    # Existing supermarkets
    # --------------------------------------------------

    for name in sorted(
        new_names & old_names
    ):
        old_sources = old[name].get(
            "sources",
            [],
        )

        new_sources = new_by_name[name].get(
            "sources",
            [],
        )

        old_source_map = {
            source_identity(
                source.get("type", "unclassified"),
                source.get("url", ""),
            ): source
            for source in old_sources
        }

        new_source_map = {
            source_identity(
                source.get("type", "unclassified"),
                source.get("url", ""),
            ): source
            for source in new_sources
        }

        old_keys = set(
            old_source_map.keys()
        )

        new_keys = set(
            new_source_map.keys()
        )

        # --------------------------------------------------
        # New sources
        # --------------------------------------------------

        for key in sorted(
            new_keys - old_keys
        ):
            source = new_source_map[key]

            changes.append(
                f"NEW SOURCE: {name} | "
                f"{source['type']} | "
                f"{source['url']}"
            )

        # --------------------------------------------------
        # Removed sources
        # --------------------------------------------------

        for key in sorted(
            old_keys - new_keys
        ):
            source = old_source_map[key]

            changes.append(
                f"REMOVED SOURCE: {name} | "
                f"{source['type']} | "
                f"{source['url']}"
            )

        # --------------------------------------------------
        # Existing sources
        # --------------------------------------------------

        for key in sorted(
            new_keys & old_keys
        ):
            old_source = old_source_map[key]
            new_source = new_source_map[key]

            old_credentials = credential_signature(
                old_source.get(
                    "credentials",
                    [],
                )
            )

            new_credentials = credential_signature(
                new_source.get(
                    "credentials",
                    [],
                )
            )

            if old_credentials != new_credentials:

                old_users = sorted(
                    username
                    for username, _ in old_credentials
                )

                new_users = sorted(
                    username
                    for username, _ in new_credentials
                )

                if old_users != new_users:
                    changes.append(
                        f"CHANGED CREDENTIALS: {name} | "
                        f"{new_source['type']} | "
                        f"users: "
                        f"{old_users} -> {new_users}"
                    )
                else:
                    changes.append(
                        f"CHANGED PASSWORD: {name} | "
                        f"{new_source['type']} | "
                        f"users: {new_users}"
                    )

    return changes


def save_changes_log(
    changes: list[str],
) -> None:

    if not changes:
        logger.info(
            "No source changes detected"
        )
        return

    source_changes_logger.info(
        "%d source change(s) detected",
        len(changes),
    )

    for change in changes:
        source_changes_logger.info(
            change
        )


def save_chains_registry_changes_log(
    changes: list[str],
) -> None:

    if not changes:
        logger.info(
            "chains.json is up to date with gov scrape"
        )
        return

    chains_registry_logger.info(
        "%d chains.json discrepancy(ies) detected",
        len(changes),
    )

    for change in changes:
        chains_registry_logger.info(
            change
        )


def save_supermarket_sources(
    supermarkets: list[dict],
) -> None:

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            supermarkets,
            file,
            ensure_ascii=False,
            indent=2,
        )

    logger.info(
        "Saved supermarket sources to %s",
        OUTPUT_FILE,
    )


def main() -> None:

    logger.info(
        "Starting supermarket sources update"
    )

    old_sources = load_existing(
        OUTPUT_FILE
    )

    logger.info(
        "Loaded %d existing supermarket entries",
        len(old_sources),
    )

    supermarkets = scrape_supermarket_sources(
        old_sources
    )

    changes = compare_sources(
        old_sources,
        supermarkets,
    )

    save_changes_log(changes)

    chains = load_chains(
        CHAINS_FILE
    )

    chain_names = load_chain_gov_names(
        chains
    )

    registry_changes = check_chains_registry(
        supermarkets,
        chain_names,
    )

    credential_changes = check_chain_credentials(
        supermarkets,
        chains,
    )

    save_chains_registry_changes_log(
        registry_changes
    )

    save_chains_registry_changes_log(
    credential_changes
)

    save_supermarket_sources(
        supermarkets
    )

    if changes:
        logger.info(
            "Found %d source changes",
            len(changes),
        )
    else:
        logger.info(
            "No source changes"
        )

    if registry_changes:
        logger.info(
            "Found %d chains.json discrepancies",
            len(registry_changes),
        )
    else:
        logger.info(
            "No chains.json discrepancies"
        )

    logger.info(
        "Supermarket sources update finished"
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:
        logger.exception(
            "Supermarket sources update crashed"
        )
        raise