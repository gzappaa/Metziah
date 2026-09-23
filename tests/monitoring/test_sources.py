import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from monitoring.sources import (
    HARDCODED_SOURCE_TYPES,
    SOURCE_TYPES,
    check_chain_credentials,
    check_chains_registry,
    compare_sources,
    credential_signature,
    extract_credentials,
    get_domain,
    get_laibcatalog_chain_id,
    get_source_type,
    load_chain_gov_names,
    load_chains,
    load_existing,
    merge_credentials,
    source_identity,
    source_signature,
)


# ---------------------------------------------------------------------------
# get_domain / get_source_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://publishedprices.co.il/",
            "publishedprices.co.il",
        ),
        (
            "https://www.publishedprices.co.il/",
            "www.publishedprices.co.il",
        ),
        (
            "https://foo.laibcatalog.co.il/test",
            "foo.laibcatalog.co.il",
        ),
        (
            "https://BINAprojects.com/",
            "binaprojects.com",
        ),
        (
            "https://example.com/path",
            "example.com",
        ),
    ],
)
def test_get_domain(url, expected):
    assert get_domain(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://publishedprices.co.il/",
            "publishedprices",
        ),
        (
            "https://foo.publishedprices.co.il/",
            "publishedprices",
        ),
        (
            "https://laibcatalog.co.il/",
            "laibcatalog",
        ),
        (
            "https://branch.laibcatalog.co.il/",
            "laibcatalog",
        ),
        (
            "https://binaprojects.com/",
            "binaprojects",
        ),
        (
            "https://www.binaprojects.com/",
            "binaprojects",
        ),
        (
            "https://example.com/",
            "unclassified",
        ),
    ],
)
def test_get_source_type(url, expected):
    assert get_source_type(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://shop.hazi-hinam.co.il/Prices",
        "http://prices.super-pharm.co.il/",
        "http://prices.shufersal.co.il/",
        "https://www.citymarket-shops.co.il/",
        "https://app.netiv-hesed.com/",
    ],
)
def test_hardcoded_html_sources(url):
    assert (
        get_source_type(url)
        == "html_filelink"
    )


def test_unknown_subdomain_is_not_classified_as_source():
    assert (
        get_source_type(
            "https://publishedprices.co.il.example.com/"
        )
        == "unclassified"
    )


# ---------------------------------------------------------------------------
# Laibcatalog chain ID
# ---------------------------------------------------------------------------


def test_get_laibcatalog_chain_id():
    response = Mock()
    response.status_code = 200
    response.text = """
        <html>
            <script>
                const DEFAULT_EDI = "7290661400001";
            </script>
        </html>
    """
    response.raise_for_status.return_value = None

    requests_get = Mock(
        return_value=response
    )

    original_get = requests.get

    try:
        requests.get = requests_get

        result = get_laibcatalog_chain_id(
            "https://example.com"
        )

    finally:
        requests.get = original_get

    assert result == "7290661400001"

    requests_get.assert_called_once()


def test_get_laibcatalog_chain_id_single_quotes():
    response = Mock()
    response.status_code = 200
    response.text = """
        DEFAULT_EDI = '7290661400001'
    """
    response.raise_for_status.return_value = None

    original_get = requests.get

    try:
        requests.get = Mock(
            return_value=response
        )

        result = get_laibcatalog_chain_id(
            "https://example.com"
        )

    finally:
        requests.get = original_get

    assert result == "7290661400001"


def test_get_laibcatalog_chain_id_missing():
    response = Mock()
    response.text = """
        <html>
            No chain ID here.
        </html>
    """
    response.raise_for_status.return_value = None

    original_get = requests.get

    try:
        requests.get = Mock(
            return_value=response
        )

        with pytest.raises(
            RuntimeError,
            match="Could not find Laibcatalog chain ID",
        ):
            get_laibcatalog_chain_id(
                "https://example.com"
            )

    finally:
        requests.get = original_get


def test_get_laibcatalog_chain_id_http_error():
    response = Mock()

    response.raise_for_status.side_effect = (
        requests.HTTPError("HTTP 500")
    )

    original_get = requests.get

    try:
        requests.get = Mock(
            return_value=response
        )

        with pytest.raises(
            requests.HTTPError
        ):
            get_laibcatalog_chain_id(
                "https://example.com"
            )

    finally:
        requests.get = original_get


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "info,expected",
    [
        (
            "שם משתמש:doralon סיסמא:12345",
            [
                {
                    "username": "doralon",
                    "password": "12345",
                }
            ],
        ),
        (
            "שם משתמש: TivTaam סיסמא: abc",
            [
                {
                    "username": "TivTaam",
                    "password": "abc",
                }
            ],
        ),
        (
            "שם משתמש - SalachD סיסמא - xyz",
            [
                {
                    "username": "SalachD",
                    "password": "xyz",
                }
            ],
        ),
        (
            "Username: foo Password: bar",
            [
                {
                    "username": "foo",
                    "password": "bar",
                }
            ],
        ),
        (
            "User- yuda_ho Password- xyz",
            [
                {
                    "username": "yuda_ho",
                    "password": "xyz",
                }
            ],
        ),
    ],
)
def test_extract_credentials(
    info,
    expected,
):
    assert extract_credentials(info) == expected


def test_extract_credentials_password_not_required():
    result = extract_credentials(
        "שם משתמש: test סיסמא: אין צורך"
    )

    assert result == [
        {
            "username": "test",
            "password": "",
        }
    ]


def test_extract_credentials_multiple_users():
    result = extract_credentials(
        """
        שם משתמש: user1 סיסמא: pass1
        שם משתמש: user2 סיסמא: pass2
        """
    )

    assert result == [
        {
            "username": "user1",
            "password": "pass1",
        },
        {
            "username": "user2",
            "password": "pass2",
        },
    ]


@pytest.mark.parametrize(
    "info",
    [
        None,
        "",
        "   ",
    ],
)
def test_extract_credentials_empty(info):
    assert extract_credentials(info) == []


def test_merge_credentials_removes_duplicates():
    existing = [
        {
            "username": "user1",
            "password": "pass1",
        },
        {
            "username": "user2",
            "password": "pass2",
        },
    ]

    new = [
        {
            "username": "user1",
            "password": "pass1",
        },
        {
            "username": "user3",
            "password": "pass3",
        },
    ]

    result = merge_credentials(
        existing,
        new,
    )

    assert result == [
        {
            "username": "user1",
            "password": "pass1",
        },
        {
            "username": "user2",
            "password": "pass2",
        },
        {
            "username": "user3",
            "password": "pass3",
        },
    ]


def test_merge_credentials_ignores_empty_username():
    result = merge_credentials(
        [
            {
                "username": "",
                "password": "secret",
            }
        ],
        [
            {
                "username": "valid",
                "password": "secret",
            }
        ],
    )

    assert result == [
        {
            "username": "valid",
            "password": "secret",
        }
    ]


# ---------------------------------------------------------------------------
# Source identity
# ---------------------------------------------------------------------------


def test_source_identity_publishedprices_is_canonical():
    assert source_identity(
        "publishedprices",
        "https://foo.publishedprices.co.il/",
    ) == (
        "publishedprices",
        "publishedprices.co.il",
    )


def test_source_identity_publishedprices_subdomains_match():
    first = source_identity(
        "publishedprices",
        "https://a.publishedprices.co.il/",
    )

    second = source_identity(
        "publishedprices",
        "https://b.publishedprices.co.il/",
    )

    assert first == second


def test_source_identity_laibcatalog_uses_hostname():
    assert source_identity(
        "laibcatalog",
        "https://foo.laibcatalog.co.il/",
    ) == (
        "laibcatalog",
        "foo.laibcatalog.co.il",
    )


def test_source_identity_bina_uses_hostname():
    assert source_identity(
        "binaprojects",
        "https://foo.binaprojects.com/",
    ) == (
        "binaprojects",
        "foo.binaprojects.com",
    )


def test_source_identity_unclassified_uses_url():
    url = "https://example.com/source"

    assert source_identity(
        "unclassified",
        url,
    ) == (
        "unclassified",
        url,
    )


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------


def test_credential_signature_is_order_independent():
    first = [
        {
            "username": "user1",
            "password": "pass1",
        },
        {
            "username": "user2",
            "password": "pass2",
        },
    ]

    second = [
        {
            "username": "user2",
            "password": "pass2",
        },
        {
            "username": "user1",
            "password": "pass1",
        },
    ]

    assert credential_signature(
        first
    ) == credential_signature(
        second
    )


def test_credential_signature_detects_password_change():
    first = [
        {
            "username": "user1",
            "password": "old",
        }
    ]

    second = [
        {
            "username": "user1",
            "password": "new",
        }
    ]

    assert credential_signature(
        first
    ) != credential_signature(
        second
    )


def test_source_signature():
    source = {
        "type": "publishedprices",
        "url": "https://example.com",
        "credentials": [
            {
                "username": "user",
                "password": "pass",
            }
        ],
    }

    assert source_signature(source) == (
        "publishedprices",
        "https://example.com",
        (
            ("user", "pass"),
        ),
    )


# ---------------------------------------------------------------------------
# Registry comparison
# ---------------------------------------------------------------------------


def test_check_chains_registry_new_chain():
    supermarkets = [
        {"name": "Chain A"},
        {"name": "Chain B"},
    ]

    chain_names = {
        "Chain A",
    }

    result = check_chains_registry(
        supermarkets,
        chain_names,
    )

    assert result == [
        "MISSING FROM chains.json: Chain B"
    ]


def test_check_chains_registry_stale_chain():
    supermarkets = [
        {"name": "Chain A"},
    ]

    chain_names = {
        "Chain A",
        "Old Chain",
    }

    result = check_chains_registry(
        supermarkets,
        chain_names,
    )

    assert result == [
        "STALE IN chains.json (no longer in gov scrape): Old Chain"
    ]


def test_check_chains_registry_both_directions():
    supermarkets = [
        {"name": "Current Chain"},
        {"name": "New Chain"},
    ]

    chain_names = {
        "Current Chain",
        "Old Chain",
    }

    result = check_chains_registry(
        supermarkets,
        chain_names,
    )

    assert result == [
        "MISSING FROM chains.json: New Chain",
        "STALE IN chains.json (no longer in gov scrape): Old Chain",
    ]


def test_check_chains_registry_no_changes():
    supermarkets = [
        {"name": "Chain A"},
        {"name": "Chain B"},
    ]

    chain_names = {
        "Chain A",
        "Chain B",
    }

    assert check_chains_registry(
        supermarkets,
        chain_names,
    ) == []


# ---------------------------------------------------------------------------
# Credential validation against registry
# ---------------------------------------------------------------------------


def test_check_chain_credentials_matching():
    supermarkets = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                    "credentials": [
                        {
                            "username": "user1",
                            "password": "pass1",
                        }
                    ],
                }
            ],
        }
    ]

    chains = {
        "7290000000001": {
            "Chain_name_gov_page": "Chain A",
            "credentials": {
                "username": "user1",
                "password": "pass1",
            },
        }
    }

    assert check_chain_credentials(
        supermarkets,
        chains,
    ) == []


def test_check_chain_credentials_missing_user():
    supermarkets = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                    "credentials": [
                        {
                            "username": "missing_user",
                            "password": "pass1",
                        }
                    ],
                }
            ],
        }
    ]

    chains = {
        "7290000000001": {
            "Chain_name_gov_page": "Chain A",
            "credentials": {
                "username": "different_user",
                "password": "pass1",
            },
        }
    }

    result = check_chain_credentials(
        supermarkets,
        chains,
    )

    assert result == [
        "CREDENTIAL MISSING FROM chains.json: "
        "Chain A | user: missing_user"
    ]


def test_check_chain_credentials_changed_password():
    supermarkets = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                    "credentials": [
                        {
                            "username": "user1",
                            "password": "new_password",
                        }
                    ],
                }
            ],
        }
    ]

    chains = {
        "7290000000001": {
            "Chain_name_gov_page": "Chain A",
            "credentials": {
                "username": "user1",
                "password": "old_password",
            },
        }
    }

    result = check_chain_credentials(
        supermarkets,
        chains,
    )

    assert result == [
        "CHANGED PASSWORD: Chain A | user: user1"
    ]


def test_check_chain_credentials_skips_without_credentials():
    supermarkets = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                }
            ],
        }
    ]

    assert check_chain_credentials(
        supermarkets,
        {},
    ) == []


# ---------------------------------------------------------------------------
# compare_sources
# ---------------------------------------------------------------------------


def test_compare_sources_new_supermarket():
    old = {}

    new = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                }
            ],
        }
    ]

    result = compare_sources(
        old,
        new,
    )

    assert result == [
        "NEW SUPERMARKET: Chain A",
        "NEW SOURCE: Chain A | publishedprices | https://example.com",
    ]


def test_compare_sources_removed_supermarket():
    old = {
        "Chain A": {
            "name": "Chain A",
            "sources": [],
        }
    }

    new = []

    assert compare_sources(
        old,
        new,
    ) == [
        "REMOVED SUPERMARKET: Chain A"
    ]


def test_compare_sources_new_source():
    old = {
        "Chain A": {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://publishedprices.co.il/",
                }
            ],
        }
    }

    new = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://publishedprices.co.il/",
                },
                {
                    "type": "laibcatalog",
                    "url": "https://laibcatalog.co.il/",
                },
            ],
        }
    ]

    result = compare_sources(
        old,
        new,
    )

    assert result == [
        "NEW SOURCE: Chain A | laibcatalog | https://laibcatalog.co.il/",
    ]


def test_compare_sources_removed_source():
    old = {
        "Chain A": {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://publishedprices.co.il/",
                },
                {
                    "type": "laibcatalog",
                    "url": "https://laibcatalog.co.il/",
                },
            ],
        }
    }

    new = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://publishedprices.co.il/",
                },
            ],
        }
    ]

    result = compare_sources(
        old,
        new,
    )

    assert result == [
        "REMOVED SOURCE: Chain A | "
        "laibcatalog | https://laibcatalog.co.il/"
    ]


def test_compare_sources_password_change():
    old = {
        "Chain A": {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                    "credentials": [
                        {
                            "username": "user1",
                            "password": "old",
                        }
                    ],
                }
            ],
        }
    }

    new = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                    "credentials": [
                        {
                            "username": "user1",
                            "password": "new",
                        }
                    ],
                }
            ],
        }
    ]

    result = compare_sources(
        old,
        new,
    )

    assert result == [
        "CHANGED PASSWORD: Chain A | "
        "publishedprices | users: ['user1']"
    ]


def test_compare_sources_changed_users():
    old = {
        "Chain A": {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                    "credentials": [
                        {
                            "username": "old_user",
                            "password": "same",
                        }
                    ],
                }
            ],
        }
    }

    new = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://example.com",
                    "credentials": [
                        {
                            "username": "new_user",
                            "password": "same",
                        }
                    ],
                }
            ],
        }
    ]

    result = compare_sources(
        old,
        new,
    )

    assert result == [
        "CHANGED CREDENTIALS: Chain A | "
        "publishedprices | users: ['old_user'] -> ['new_user']"
    ]


def test_compare_sources_publishedprices_subdomains_are_same_source():
    old = {
        "Chain A": {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://old.publishedprices.co.il/",
                }
            ],
        }
    }

    new = [
        {
            "name": "Chain A",
            "sources": [
                {
                    "type": "publishedprices",
                    "url": "https://new.publishedprices.co.il/",
                }
            ],
        }
    ]

    assert compare_sources(
        old,
        new,
    ) == []


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


def test_load_existing_missing_file(tmp_path):
    path = tmp_path / "missing.json"

    assert load_existing(path) == {}


def test_load_existing(tmp_path):
    path = tmp_path / "sources.json"

    data = [
        {
            "name": "Chain A",
            "sources": [],
        },
        {
            "name": "Chain B",
            "sources": [],
        },
    ]

    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    result = load_existing(path)

    assert result == {
        "Chain A": data[0],
        "Chain B": data[1],
    }


def test_load_chains_missing_file(tmp_path):
    path = tmp_path / "chains.json"

    assert load_chains(path) == {}


def test_load_chains(tmp_path):
    path = tmp_path / "chains.json"

    data = {
        "7290000000001": {
            "Chain_name_gov_page": "Chain A",
        }
    }

    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    assert load_chains(path) == data


def test_load_chain_gov_names():
    chains = {
        "1": {
            "Chain_name_gov_page": "Chain A",
        },
        "2": {
            "Chain_name_gov_page": "Chain B",
        },
        "3": {
            "name_he_normalized": "No government name",
        },
        "4": {
            "Chain_name_gov_page": "",
        },
    }

    assert load_chain_gov_names(chains) == {
        "Chain A",
        "Chain B",
    }


# ---------------------------------------------------------------------------
# REAL chains.json validation
# ---------------------------------------------------------------------------


def test_real_chains_json_loads():
    """
    Make sure the actual manually maintained chains.json
    remains valid JSON and can be loaded by monitoring.
    """

    from monitoring.sources import CHAINS_FILE

    chains = load_chains(CHAINS_FILE)

    assert chains
    assert isinstance(chains, dict)


def test_real_chains_json_has_valid_chain_ids():
    """
    Chain IDs are the dictionary keys and should be numeric.
    """

    from monitoring.sources import CHAINS_FILE

    chains = load_chains(CHAINS_FILE)

    assert chains

    for chain_id in chains:
        assert isinstance(chain_id, str)
        assert chain_id.isdigit()


def test_real_chains_json_has_required_fields():
    """
    Validate the fields needed by the monitoring / pipeline
    without hardcoding individual supermarkets.
    """

    from monitoring.sources import CHAINS_FILE

    chains = load_chains(CHAINS_FILE)

    required_fields = {
        "Chain_name_store_file",
        "Chain_name_gov_page",
        "name_he_normalized",
        "name_en_normalized",
    }

    for chain_id, chain in chains.items():

        missing = required_fields - set(chain)

        assert not missing, (
            f"Chain {chain_id} is missing fields: "
            f"{sorted(missing)}"
        )


def test_real_chains_json_government_names_are_nonempty():
    from monitoring.sources import CHAINS_FILE

    chains = load_chains(CHAINS_FILE)

    for chain_id, chain in chains.items():
        gov_name = chain.get(
            "Chain_name_gov_page"
        )

        assert isinstance(gov_name, str), (
            f"Chain {chain_id} has invalid "
            "Chain_name_gov_page"
        )

        assert gov_name.strip(), (
            f"Chain {chain_id} has empty "
            "Chain_name_gov_page"
        )


def test_real_chains_json_credentials_have_valid_shape():
    """
    If a chain has credentials, they must contain
    username and password fields.

    This intentionally does not assert specific passwords.
    """

    from monitoring.sources import CHAINS_FILE

    chains = load_chains(CHAINS_FILE)

    for chain_id, chain in chains.items():

        credentials = chain.get("credentials")

        if credentials is None:
            continue

        assert isinstance(credentials, dict), (
            f"Chain {chain_id} credentials must be a dict"
        )

        assert isinstance(
            credentials.get("username"),
            str,
        ), (
            f"Chain {chain_id} has invalid credential username"
        )

        assert credentials["username"].strip(), (
            f"Chain {chain_id} has empty credential username"
        )

        assert isinstance(
            credentials.get("password"),
            str,
        ), (
            f"Chain {chain_id} has invalid credential password"
        )


def test_real_chains_json_government_names_are_nonempty():
    from monitoring.sources import CHAINS_FILE

    chains = load_chains(CHAINS_FILE)

    for chain_id, chain in chains.items():
        assert chain["Chain_name_gov_page"].strip(), (
            f"Chain {chain_id} has an empty Chain_name_gov_page"
        )