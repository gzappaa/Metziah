import json

from database.repository import CHAINS_FILE, get_publishing_sources


def test_get_publishing_sources_filters_by_client():
    sources = get_publishing_sources("PublishedPricesClient")

    assert sources
    assert all(
        set(source) >= {
            "chain_id",
            "name",
            "name_normalized",
            "url",
            "credentials",
        }
        for source in sources
    )


def test_get_publishing_sources_non_published_client_has_no_credentials():
    sources = get_publishing_sources("BinaProjectsClient")

    assert sources
    assert all("credentials" not in source for source in sources)


def test_get_publishing_sources_unknown_client_returns_empty():
    assert get_publishing_sources("DefinitelyNotARealClient") == []


def test_get_publishing_sources_falls_back_to_chain_name():
    with CHAINS_FILE.open(encoding="utf-8") as file:
        chains = json.load(file)

    expected = [
        chain["Chain_name_store_file"]
        for chain in chains.values()
        if chain.get("client") == "BinaProjectsClient"
        and "name_en_normalized" not in chain
    ]

    sources = get_publishing_sources("BinaProjectsClient")

    if expected:
        assert any(
            source["name_normalized"] == source["name"]
            for source in sources
        )