# tests/analytics/test_promo_changes.py
from analytics.log_parsers import promo_changes

CHAIN = "9999999999999"
OTHER_CHAIN = "8888888888888"
TEST_CHAINS = {CHAIN: {"name_en_normalized": "test chain 9999"}, OTHER_CHAIN: {"name_en_normalized": "test chain 8888"}}


def _patch_chains(monkeypatch):
    monkeypatch.setattr(promo_changes.common, "_chain_cache", None)
    monkeypatch.setattr(promo_changes.common, "load_chains", lambda *a, **kw: TEST_CHAINS)


def _log(*lines):
    return "\n".join(lines) + "\n"


def _many_stores(create_store, chain_id, n):
    store_ids = [str(i) for i in range(1, n + 1)]
    for sid in store_ids:
        create_store(chain_id, sid)
    return store_ids


def _seed_price(conn, chain_id, store_id, item_code, price):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prices (chain_id, store_id, item_code, price)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chain_id, store_id, item_code) DO UPDATE SET price = EXCLUDED.price
            """,
            (chain_id, store_id, item_code, price),
        )
    conn.commit()


def _seed_promotion(conn, chain_id, promotion_id, store_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO promotions (chain_id, promotion_id, store_id, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chain_id, promotion_id, store_id) DO NOTHING
            """,
            (chain_id, promotion_id, store_id, "test promo"),
        )
    conn.commit()


def _seed_product(conn, item_code):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO products (item_code, name) VALUES (%s, %s) ON CONFLICT (item_code) DO NOTHING",
            (item_code, "test product"),
        )
    conn.commit()


def test_promo_changes_per_chain_counts(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    text = _log(
        f"2026-09-26 02:33:59,063 [INFO] promo_changes: PROMOTION ADDED chain_id={CHAIN} store_id=1 promotion_id=P1 description=test promo",
        f"2026-09-26 02:59:22,814 [INFO] promo_changes: PROMO ITEM ADDED chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code=111 name=test item discounted_price=5.00",
        f"2026-09-26 02:38:32,570 [INFO] promo_changes: PROMO ITEM CHANGED chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code=222 name=other item old=(Decimal('10.00'), None) new=(Decimal('20.00'), None)",
        f"2026-09-26 02:39:23,541 [INFO] promo_changes: PROMO ITEM REMOVED chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code=333 name=removed item",
    )
    path = tmp_path / "promo_changes.log"
    path.write_text(text, encoding="utf-8")
    data, txt_lines = promo_changes.parse([path])

    assert data["counts"]["promotions_added"] == 1
    assert data["counts"]["items_added"] == 1
    assert data["counts"]["items_changed"] == 1
    assert data["counts"]["items_removed"] == 1
    assert data["per_chain"][CHAIN]["chain_name"] == "test chain 9999"
    assert any("Promo changes report" in l for l in txt_lines)


def test_promotion_coverage_percentage(tmp_path, monkeypatch, conn, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    store_ids = _many_stores(create_store, CHAIN, 4)
    for sid in store_ids[:3]:
        _seed_promotion(conn, CHAIN, "P1", sid)

    text = _log(
        f"2026-09-26 02:33:59,063 [INFO] promo_changes: PROMOTION ADDED chain_id={CHAIN} store_id={store_ids[0]} promotion_id=P1 description=test promo",
    )
    path = tmp_path / "promo_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = promo_changes.parse([path])

    assert data["db_unavailable"] is False
    cov = data["promotion_coverage"][0]
    assert cov["promotion_id"] == "P1"
    assert cov["stores_with_promotion"] == 3
    assert cov["total_stores"] == 4
    assert cov["pct"] == 75.0


def test_discount_lookup_against_prices_table(tmp_path, monkeypatch, conn, create_store, cleanup_test_chains, test_price_partitions):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    _seed_price(conn, CHAIN, "1", "111", 20.00)

    text = _log(
        f"2026-09-26 02:59:22,814 [INFO] promo_changes: PROMO ITEM ADDED chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code=111 name=test item discounted_price=15.00",
        f"2026-09-26 02:59:23,000 [INFO] promo_changes: PROMO ITEM ADDED chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code=999 name=no price on file discounted_price=1.00",
    )
    path = tmp_path / "promo_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = promo_changes.parse([path])

    assert len(data["discounts"]) == 1
    d = data["discounts"][0]
    assert d["item_code"] == "111"
    assert d["normal_price"] == 20.00
    assert d["discounted_price"] == 15.00
    assert d["discount_pct"] == 25.0


def test_discount_lookup_batches_many_items_in_one_query(tmp_path, monkeypatch, conn, create_store, cleanup_test_chains, test_price_partitions):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    lines = []
    for i in range(50):
        code = f"{1000 + i}"
        _seed_price(conn, CHAIN, "1", code, 10.00 + i)
        lines.append(
            f"2026-09-26 02:59:{i % 60:02d},000 [INFO] promo_changes: PROMO ITEM ADDED "
            f"chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code={code} "
            f"name=item{i} discounted_price={5.00 + i}"
        )
    path = tmp_path / "promo_changes.log"
    path.write_text(_log(*lines), encoding="utf-8")
    data, _ = promo_changes.parse([path])

    assert len(data["discounts"]) == 50
    by_code = {d["item_code"]: d for d in data["discounts"]}
    assert by_code["1000"]["normal_price"] == 10.00
    assert by_code["1049"]["normal_price"] == 59.00


def test_substantial_promo_item_change_threshold(tmp_path, monkeypatch, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    _many_stores(create_store, CHAIN, 1)
    text = _log(
        f"2026-09-26 02:38:32,570 [INFO] promo_changes: PROMO ITEM CHANGED chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code=111 name=a old=(Decimal('10.00'), None) new=(Decimal('11.00'), None)",
        f"2026-09-26 02:38:33,000 [INFO] promo_changes: PROMO ITEM CHANGED chain_id={CHAIN} store_id=1 promotion_id=P1 group_id=1 item_code=222 name=b old=(Decimal('19.90'), None) new=(Decimal('49.90'), None)",
    )
    path = tmp_path / "promo_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = promo_changes.parse([path])
    assert len(data["substantial_promo_item_changes"]) == 1
    assert data["substantial_promo_item_changes"][0]["item_code"] == "222"


def test_inter_store_and_inter_chain_removed(tmp_path, monkeypatch, conn, create_store, cleanup_test_chains):
    _patch_chains(monkeypatch)
    store_ids = _many_stores(create_store, CHAIN, 2)
    _many_stores(create_store, OTHER_CHAIN, 1)
    _seed_product(conn, "777")

    text = _log(
        f"2026-09-26 02:39:23,541 [INFO] promo_changes: PROMO ITEM REMOVED chain_id={CHAIN} store_id={store_ids[0]} promotion_id=P1 group_id=1 item_code=777 name=x",
        f"2026-09-26 02:39:24,000 [INFO] promo_changes: PROMO ITEM REMOVED chain_id={CHAIN} store_id={store_ids[1]} promotion_id=P2 group_id=1 item_code=777 name=x",
        f"2026-09-26 02:39:25,000 [INFO] promo_changes: PROMO ITEM REMOVED chain_id={OTHER_CHAIN} store_id=1 promotion_id=P3 group_id=1 item_code=777 name=x",
    )
    path = tmp_path / "promo_changes.log"
    path.write_text(text, encoding="utf-8")
    data, _ = promo_changes.parse([path])

    assert len(data["inter_store_items_removed"]) == 1
    assert data["inter_store_items_removed"][0]["store_count"] == 2

    assert len(data["inter_chain_items_removed"]) == 1
    assert set(data["inter_chain_items_removed"][0]["chains"]) == {CHAIN, OTHER_CHAIN}