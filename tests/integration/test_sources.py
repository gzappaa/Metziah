import pytest

from monitoring.sources import (
    CHAINS_FILE,
    OUTPUT_FILE,
    check_chain_credentials,
    check_chains_registry,
    compare_sources,
    load_chains,
    load_chain_gov_names,
    load_existing,
    scrape_supermarket_sources,
)


@pytest.mark.integration
def test_government_sources_are_unchanged():
    old_sources = load_existing(OUTPUT_FILE)

    current_sources = scrape_supermarket_sources(old_sources)

    source_changes = compare_sources(
        old_sources,
        current_sources,
    )

    chains = load_chains(CHAINS_FILE)
    chain_names = load_chain_gov_names(chains)

    registry_changes = check_chains_registry(
        current_sources,
        chain_names,
    )

    credential_changes = check_chain_credentials(
        current_sources,
        chains,
    )

    assert not source_changes, (
        "Government source changes detected:\n"
        + "\n".join(map(str, source_changes))
    )

    assert not registry_changes, (
        "Government chain registry changes detected:\n"
        + "\n".join(map(str, registry_changes))
    )

    assert not credential_changes, (
        "Government credential changes detected:\n"
        + "\n".join(map(str, credential_changes))
    )