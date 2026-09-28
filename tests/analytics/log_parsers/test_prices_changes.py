# tests/analytics/test_price_changes.py
from analytics.log_parsers import common, price_changes

CHAIN = "9999999999999"
OTHER_CHAIN = "8888888888888"
TEST_CHAINS = {CHAIN: {"name_en_normalized": "test chain 9999"}, OTHER_CHAIN: {"name_en_normalized": "test chain 8888"}}


def _patch_chains(monkeypatch):
    monkeypatch.setattr(price_changes.common, "_chain_cache", None)
    monkeypatch.setattr(price_changes.common, "load_chains", lambda *a, **kw: TEST_CHAINS)


def _log(*lines):
    return "\n".join(lines) + "\n"


def _many_stores(create_store, chain_id, n):
    store_ids = [str(i) for i in range(1, n + 1)]
    for sid in store_ids:
        create_store(chain_id, sid)
    return store_ids


def _seed_product(conn, item_code):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO products (item_code, name) VALUES (%s, %s) ON CONFLICT (item_code) DO NOTHING",
            (item_code, "test product"),
        )
    conn.commit()


def test_price_changes_per_chain_counts(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    text = _log(
        f"2026-09-26 02:21:14,639 [INFO] price_changes: PRICE ADDED chain_id={CHAIN} store_id=1 item_code=111 price=11.90",
        f"2026-09-26 02:21:15,000 [INFO] price_changes: PRICE CHANGED chain_id={CHAIN} store_id=1 item_code=222 old_price=6.00 new_price=6.50 old_unit_price=6.00 new_unit_price=6.50",
        f"2026-09-26 02:21:16,000 [INFO] price_changes: ITEM REMOVED chain_id={CHAIN} store_id=1 item_code=333 (was price=5.00)",
    )
    path = tmp_path / "price_changes.log"
    path.write_text(text, encoding="utf-8")
    data, txt_lines = price_changes.parse([path])

    assert data["counts"] == {"added": 1, "changed": 1, "removed": 1}
    assert data["per_chain"][CHAIN] == {"chain_name": "test chain 9999", "added": 1, "changed": 1, "removed": 1}
    assert any("Price changes report" in l for l in txt_lines)


def test_reintroduced_same_run_detected(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    text = _log(
        f"2026-09-26 02:20:00,000 [INFO] price_changes: ITEM REMOVED chain_id={CHAIN} store_id=1 item_code=111 (was price=11.90)",
        f"2026-09-26 02:21:14,639 [INFO] price_changes: PRICE ADDED chain_id={CHAIN} store_id=1 item_code=111 price=11.90",
    )
    path = tmp_path / "price_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = price_changes.parse([path])

    assert len(data["reintroduced_same_run"]) == 1
    assert data["reintroduced_same_run"][0]["item_code"] == "111"


def test_reintroduced_not_flagged_if_added_before_removed(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    text = _log(
        f"2026-09-26 02:10:00,000 [INFO] price_changes: PRICE ADDED chain_id={CHAIN} store_id=1 item_code=111 price=11.90",
        f"2026-09-26 02:20:00,000 [INFO] price_changes: ITEM REMOVED chain_id={CHAIN} store_id=1 item_code=111 (was price=11.90)",
    )
    path = tmp_path / "price_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = price_changes.parse([path])
    assert data["reintroduced_same_run"] == []


def test_duplicate_events_same_store(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    text = _log(
        f"2026-09-26 02:10:00,000 [INFO] price_changes: PRICE ADDED chain_id={CHAIN} store_id=1 item_code=111 price=11.90",
        f"2026-09-26 02:10:01,000 [INFO] price_changes: PRICE CHANGED chain_id={CHAIN} store_id=1 item_code=111 old_price=11.90 new_price=12.00 old_unit_price=11.90 new_unit_price=12.00",
    )
    path = tmp_path / "price_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = price_changes.parse([path])
    assert len(data["duplicate_events_same_store"]) == 1
    assert set(data["duplicate_events_same_store"][0]["events"]) == {"added", "changed"}


def test_substantial_price_change_threshold(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    text = _log(
        f"2026-09-26 02:10:00,000 [INFO] price_changes: PRICE CHANGED chain_id={CHAIN} store_id=1 item_code=111 old_price=12.00 new_price=13.00 old_unit_price=12.00 new_unit_price=13.00",
        f"2026-09-26 02:10:01,000 [INFO] price_changes: PRICE CHANGED chain_id={CHAIN} store_id=1 item_code=222 old_price=5.00 new_price=10.00 old_unit_price=5.00 new_unit_price=10.00",
    )
    path = tmp_path / "price_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = price_changes.parse([path])
    assert len(data["substantial_price_changes"]) == 1
    assert data["substantial_price_changes"][0]["item_code"] == "222"


def test_majority_removed_from_chain(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    store_ids = _many_stores(create_store, CHAIN, 4)

    monkeypatch.setattr(
        price_changes.common,
        "fetch_store_counts",
        lambda chain_ids: {CHAIN: 4},
    )

    lines = [
        f"2026-09-26 02:20:00,00{i} [INFO] price_changes: "
        f"ITEM REMOVED chain_id={CHAIN} store_id={sid} item_code=999 (was price=1.00)"
        for i, sid in enumerate(store_ids[:3])
    ]

    path = tmp_path / "price_changes.log"
    path.write_text(_log(*lines), encoding="utf-8")

    data, _ = price_changes.parse([path])

    assert data["db_unavailable"] is False
    assert data["counts"]["removed"] == 3
    assert len(data["majority_removed_from_chain"]) == 1

    result = data["majority_removed_from_chain"][0]
    assert result["chain_id"] == CHAIN
    assert result["item_code"] == "999"
    assert result["stores_affected"] == 3
    assert result["total_stores"] == 4
    assert result["pct"] == 75.0

def test_cross_chain_removed_only_for_universal_products(tmp_path, monkeypatch, conn, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    _many_stores(create_store, OTHER_CHAIN, 1)
    _seed_product(conn, "777")

    text = _log(
        f"2026-09-26 02:20:00,000 [INFO] price_changes: ITEM REMOVED chain_id={CHAIN} store_id=1 item_code=777 (was price=1.00)",
        f"2026-09-26 02:20:01,000 [INFO] price_changes: ITEM REMOVED chain_id={OTHER_CHAIN} store_id=1 item_code=777 (was price=1.00)",
        f"2026-09-26 02:20:02,000 [INFO] price_changes: ITEM REMOVED chain_id={CHAIN} store_id=1 item_code=888 (was price=1.00)",
        f"2026-09-26 02:20:03,000 [INFO] price_changes: ITEM REMOVED chain_id={OTHER_CHAIN} store_id=1 item_code=888 (was price=1.00)",
    )
    path = tmp_path / "price_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = price_changes.parse([path])

    assert len(data["cross_chain_removed"]) == 1
    assert data["cross_chain_removed"][0]["item_code"] == "777"


def test_db_unavailable_degrades_gracefully(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)

    def _boom(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(price_changes.common, "fetch_universal_product_codes", _boom)
    monkeypatch.setattr(price_changes.common, "fetch_store_counts", _boom)

    text = _log(
        f"2026-09-26 02:20:00,000 [INFO] price_changes: ITEM REMOVED chain_id={CHAIN} store_id=1 item_code=111 (was price=1.00)",
    )
    path = tmp_path / "price_changes.log"
    path.write_text(text, encoding="utf-8")
    data, txt_lines = price_changes.parse([path])

    assert data["db_unavailable"] is True
    assert data["counts"]["removed"] == 1
    assert any("DB unavailable" in l for l in txt_lines)