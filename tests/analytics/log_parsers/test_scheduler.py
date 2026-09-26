# tests/analytics/test_scheduler.py
from analytics.log_parsers import scheduler

TEST_CHAINS = {"9999999999999": {"name_en_normalized": "test chain 9999"}}


def _patch_chains(monkeypatch):
    monkeypatch.setattr(scheduler.common, "_chain_cache", None)
    monkeypatch.setattr(scheduler.common, "load_chains", lambda *a, **kw: TEST_CHAINS)


SAMPLE_LOG = """\
2026-09-26 02:06:02,380 [INFO] root: Updating file tracking
2026-09-26 02:06:09,483 [INFO] utils.file_tracking.load_file_tracking: PublishedPrices: 1445 today's file(s) total
2026-09-26 02:06:18,479 [INFO] utils.file_tracking.load_file_tracking: Carrefour: 7 today's file(s) total
2026-09-26 02:08:40,974 [INFO] utils.file_tracking.load_file_tracking: Inserted 2126 new file(s) out of 2126 discovered
2026-09-26 02:08:40,974 [INFO] root: File tracking updated: 2126 new file(s)
2026-09-26 02:08:40,975 [INFO] root: Starting pricesfull download
2026-09-26 02:08:41,678 [WARNING] downloaders.pricesfull: No PriceFull files found for אושר עד
2026-09-26 02:09:52,360 [WARNING] downloaders.pricesfull: No PriceFull files found for שוק העיר
2026-09-26 02:10:24,458 [INFO] root: PriceFull download finished: 810 new file(s)
2026-09-26 02:12:46,043 [WARNING] utils.prices.update_prices: No items parsed from /home/dmin/metziah/data/feeds/9999999999999/41/pricesfull/PriceFull9999999999999-000-041-20260922-000014.gz
2026-09-26 02:12:46,043 [WARNING] utils.prices.update_prices: No prices found in /home/dmin/metziah/data/feeds/9999999999999/41/pricesfull/PriceFull9999999999999-000-041-20260922-000014.gz
2026-09-26 02:12:46,396 [ERROR] utils.prices.update_prices: Failed to load /path/foo.gz
2026-09-26 02:25:19,001 [INFO] utils.prices.update_prices: Price9999999999999-002-002-20260926-011701.GZ: type=Price snapshot=False chain_id=9999999999999 store_id=2 items=156 removed=0
2026-09-26 02:25:22,887 [INFO] utils.products.update_products: New-product discovery: 3 new product(s), 9775 store_product record(s) from 59 file(s) (157 candidate item_code(s) already existed)
2026-09-26 02:30:50,980 [INFO] utils.promos.update_promos: PromoFull9999999999999-001-011-20260926-001111.gz: file_type=PromoFull chain_id=9999999999999 store_id=11 promotions=2875 items=14862 removed_promotions=30 removed_groups=0 removed_items=0
2026-09-26 02:34:14,372 [WARNING] utils.promos.update_promos: No valid promotions with promotion_id found in /home/dmin/metziah/data/feeds/9999999999999/2/promosfull/PromoFull9999999999999-000-002-20260926-000035.gz
2026-09-26 02:59:51,317 [WARNING] utils.file_tracking.data_enrichment.populate_file_sizes: File not found: id=70343 path=/some/path.gz
2026-09-26 02:59:51,853 [INFO] utils.file_tracking.data_enrichment.populate_file_sizes: Finished: updated=2004 missing=231
2026-09-26 03:00:00,000 [INFO] root: some brand new line format we've never seen
"""


def test_scheduler_parse_full_sample(tmp_path, monkeypatch):
    _patch_chains(monkeypatch)
    path = tmp_path / "scheduler.log"
    path.write_text(SAMPLE_LOG, encoding="utf-8")
    data, txt_lines = scheduler.parse([path])

    assert data["run_date"] == "2026-09-26"

    ft_phase = next(p for p in data["phase_timings"] if p["phase"] == "file_tracking_update")
    assert ft_phase["new_files"] == "2126"
    assert ft_phase["elapsed_seconds"] == 158.594

    pf_phase = next(p for p in data["phase_timings"] if p["phase"] == "pricesfull_download")
    assert pf_phase["new_files"] == "810"

    assert data["source_file_counts"] == {"PublishedPrices": 1445, "Carrefour": 7}
    assert data["file_tracking_inserted"] == {"inserted": 2126, "discovered": 2126}

    assert data["pricefull_missing_count"] == 2
    assert "אושר עד" in data["pricefull_missing"]

    assert data["no_items_parsed_by_chain"]["9999999999999"]["count"] == 1
    assert data["no_items_parsed_by_chain"]["9999999999999"]["chain_name"] == "test chain 9999"
    assert data["no_prices_found_by_chain"]["9999999999999"]["count"] == 1
    assert data["no_valid_promotions_by_chain"]["9999999999999"]["count"] == 1

    assert data["unmatched_line_count"] == 1
    assert "some brand new line format" in data["unmatched_samples"][0]

    discovery = data["product_discovery_events"][0]
    assert discovery["new_products"] == 3
    assert discovery["store_product_records"] == 9775

    price_agg = data["price_file_loads_by_chain"]["9999999999999"]
    assert price_agg["files"] == 1
    assert price_agg["items"] == 156

    promo_agg = data["promo_file_loads_by_chain"]["9999999999999"]
    assert promo_agg["promotions"] == 2875
    assert promo_agg["removed_promotions"] == 30

    assert data["file_sizes_finished"] == {"updated": 2004, "missing": 231}
    assert any("Scheduler report" in line for line in txt_lines)


def test_scheduler_multiple_files_merged_and_sorted(tmp_path, monkeypatch):
    _patch_chains(monkeypatch)
    p1 = tmp_path / "scheduler.log.1"
    p1.write_text("2026-09-26 02:06:02,380 [INFO] root: Updating file tracking\n", encoding="utf-8")
    p2 = tmp_path / "scheduler.log.2"
    p2.write_text("2026-09-26 02:08:40,974 [INFO] root: File tracking updated: 5 new file(s)\n", encoding="utf-8")

    data, _ = scheduler.parse([p1, p2])
    assert len(data["phase_timings"]) == 1
    assert data["phase_timings"][0]["new_files"] == "5"


def test_scheduler_ignores_file_not_found_line(tmp_path, monkeypatch):
    _patch_chains(monkeypatch)
    text = (
        "2026-09-26 02:59:51,317 [WARNING] utils.file_tracking.data_enrichment.populate_file_sizes: "
        "File not found: id=1 path=/x.gz\n"
    )
    path = tmp_path / "scheduler.log"
    path.write_text(text, encoding="utf-8")
    data, _ = scheduler.parse([path])
    assert data["unmatched_line_count"] == 0
    assert data["file_sizes_finished"] is None