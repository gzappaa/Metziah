"""Integration test for queries.get_catalog_stats (needs the test DB)."""

from api import queries


def test_catalog_stats_shape(seed):
    stats = queries.get_catalog_stats()

    assert set(stats) == {"total_stores", "total_brands", "total_fresh_products"}
    assert all(isinstance(value, int) and value >= 0 for value in stats.values())
    assert stats["total_stores"] >= 2  # the seed fixture's stores