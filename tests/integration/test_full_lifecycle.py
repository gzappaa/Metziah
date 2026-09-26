from decimal import Decimal

from parsers.xml import StoreXmlParser
from utils.prices.update_prices import load_one_file as load_price_file
from utils.promos.update_promos import load_one_file as load_promo_file


def _prices(conn, chain_id, store_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_code, price FROM prices "
            "WHERE chain_id = %s AND store_id = %s",
            (chain_id, store_id),
        )
        return dict(cur.fetchall())


def _promotions(conn, chain_id, store_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT promotion_id FROM promotions "
            "WHERE chain_id = %s AND store_id = %s",
            (chain_id, store_id),
        )
        return {row[0] for row in cur.fetchall()}


def test_full_store_lifecycle_prices_and_promos(
    conn,
    feeds_dir,
    mock_chain_metadata,
    create_store,
    test_price_partitions,
    test_promo_partitions,
    cleanup_test_chains,
):
    """
    Real fixture feeds, real parser, real repository functions.

    1. PriceFull + PromoFull seed the baseline (5 items, 2 promos).
    2. Price + Promo deltas: one item/promo changes, one item/promo is
       added, everything else survives untouched -- prices and promos
       reconcile independently of each other.
    3. The same delta payloads, reinterpreted as *Full snapshots, prove
       real reconciliation: whatever they omit gets removed, in both
       prices and promotions.
    """
    chain_id = "9999999999999"
    store_id = "1"
    create_store(chain_id, store_id)

    price_parser = StoreXmlParser()
    promo_parser = StoreXmlParser()

    pricefull_path = (
        feeds_dir / chain_id / store_id / "pricesfull"
        / "PriceFull9999999999999-001-001-20260101-000000.xml"
    )
    price_delta_path = (
        feeds_dir / chain_id / store_id / "prices"
        / "Price9999999999999-001-001-20260101-000001.xml"
    )
    promofull_path = (
        feeds_dir / chain_id / store_id / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-000000.xml"
    )
    promo_delta_path = (
        feeds_dir / chain_id / store_id / "promos"
        / "Promo9999999999999-001-001-20260101-000001.xml"
    )

    # --- 1. baseline ---
    load_price_file(
        conn, price_parser, pricefull_path, feeds_dir,
        mock_chain_metadata, "PriceFull", log_changes=False,
    )
    load_promo_file(
        conn, promo_parser, promofull_path, feeds_dir,
        "PromoFull", mock_chain_metadata, log_changes=False,
    )

    assert len(_prices(conn, chain_id, store_id)) == 5
    assert _promotions(conn, chain_id, store_id) == {"0000000001", "0000000002"}

    # --- 2. deltas: change + add, nothing removed ---
    load_price_file(
        conn, price_parser, price_delta_path, feeds_dir,
        mock_chain_metadata, "Price", snapshot=False, log_changes=False,
    )
    load_promo_file(
        conn, promo_parser, promo_delta_path, feeds_dir,
        "Promo", mock_chain_metadata, log_changes=False,
    )

    prices = _prices(conn, chain_id, store_id)
    assert len(prices) == 6
    assert prices["7290000000001"] == Decimal("11.00")
    assert prices["7290000000010"] == Decimal("9.90")

    promos = _promotions(conn, chain_id, store_id)
    assert promos == {"0000000001", "0000000002", "0000000003"}

    # --- 3. same payloads, reinterpreted as full snapshots: real removal ---
    load_price_file(
        conn, price_parser, price_delta_path, feeds_dir,
        mock_chain_metadata, "PriceFull", log_changes=False,
    )
    load_promo_file(
        conn, promo_parser, promo_delta_path, feeds_dir,
        "PromoFull", mock_chain_metadata, log_changes=False,
    )

    prices = _prices(conn, chain_id, store_id)
    assert set(prices) == {"7290000000001", "7290000000010"}

    promos = _promotions(conn, chain_id, store_id)
    assert promos == {"0000000001", "0000000003"}  # 0000000002 removed