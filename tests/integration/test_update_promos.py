from decimal import Decimal

import pytest

from models.promo import Promotion
from parsers.xml import StoreXmlParser
from utils.promos.update_promos import load_files, load_one_file


def _promotions(conn, chain_id, store_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT promotion_id, description FROM promotions "
            "WHERE chain_id = %s AND store_id = %s",
            (chain_id, store_id),
        )
        return dict(cur.fetchall())


def _promo_item_discounted_price(conn, chain_id, store_id, promotion_id, item_code):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT discounted_price FROM promotion_items "
            "WHERE chain_id = %s AND store_id = %s "
            "AND promotion_id = %s AND item_code = %s",
            (chain_id, store_id, promotion_id, item_code),
        )
        row = cur.fetchone()
        return row[0] if row else None


def test_promofull_then_delta_never_reconciles(
    conn, feeds_dir, mock_chain_metadata, create_store, test_promo_partitions,
):
    chain_id = "9999999999999"
    store_id = "1"
    create_store(chain_id, store_id)

    files = [
        (
            feeds_dir / chain_id / store_id / "promosfull"
            / "PromoFull9999999999999-001-001-20260101-000000.xml",
            "PromoFull",
        ),
        (
            feeds_dir / chain_id / store_id / "promos"
            / "Promo9999999999999-001-001-20260101-000001.xml",
            "Promo",
        ),
    ]

    loaded = load_files(conn, files, feeds_dir, log_changes=False)
    assert len(loaded) == 2

    assert _promotions(conn, chain_id, store_id) == {
        "0000000001": "חלב ב - 5.90",     # changed
        "0000000002": "לחם ב - 7.90",     # absent from delta, Promo never reconciles
        "0000000003": "ביצים ב - 11.90",  # added
    }

    assert _promo_item_discounted_price(
        conn, chain_id, store_id, "0000000001", "7290000000001",
    ) == Decimal("5.90")


def test_promofull_reinterpretation_reconciles_missing(
    conn, feeds_dir, mock_chain_metadata, create_store, test_promo_partitions,
):
    """
    Same delta payload as above, loaded as PromoFull instead of Promo, to
    directly contrast the two: only PromoFull removes what's missing.
    """
    chain_id = "9999999999999"
    store_id = "1"
    create_store(chain_id, store_id)
    parser = StoreXmlParser()

    load_one_file(
        conn, parser,
        feeds_dir / chain_id / store_id / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-000000.xml",
        feeds_dir, "PromoFull", mock_chain_metadata,
        log_changes=False,
    )

    load_one_file(
        conn, parser,
        feeds_dir / chain_id / store_id / "promos"
        / "Promo9999999999999-001-001-20260101-000001.xml",
        feeds_dir, "PromoFull", mock_chain_metadata,
        log_changes=False,
    )

    assert set(_promotions(conn, chain_id, store_id)) == {
        "0000000001", "0000000003",
    }


def test_promotion_with_null_id_is_skipped(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    test_promo_partitions,
):
    chain_id = "9999999999999"
    store_id = "1"

    valid_promo = Promotion(
        chain_id=chain_id, promotion_id="OK_PROMO", store_id=store_id,
        description="valid", start_datetime=None, end_datetime=None,
        start_hour=None, end_hour=None, promotion_days=None, update_time=None,
        club_id=None, is_gift_item=None, additional_is_coupon=False,
        allow_multiple_discounts=False, redemption_limit=None,
        min_no_of_items_offered=None, additional_restrictions=None,
        remarks=None, groups=[],
    )
    broken_promo = Promotion(
        chain_id=chain_id, promotion_id=None, store_id=store_id,
        description="should be skipped", start_datetime=None, end_datetime=None,
        start_hour=None, end_hour=None, promotion_days=None, update_time=None,
        club_id=None, is_gift_item=None, additional_is_coupon=False,
        allow_multiple_discounts=False, redemption_limit=None,
        min_no_of_items_offered=None, additional_restrictions=None,
        remarks=None, groups=[],
    )

    create_store(chain_id, store_id)

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM promotions WHERE chain_id = %s AND store_id = %s",
            (chain_id, store_id),
        )
    conn.commit()

    monkeypatch.setattr(
        StoreXmlParser, "parse_promo_file",
        lambda self, xml_content: [valid_promo, broken_promo],
    )
    monkeypatch.setattr(
        "utils.promos.update_promos.iter_xml_from_path",
        lambda path: [b"<Root/>"],
    )

    filepath = (
        tmp_path / chain_id / store_id / "promos"
        / f"Promo{chain_id}-001-001-20260101-000000.xml"
    )
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<Root/>")

    loaded = load_files(
        conn, [(filepath, "Promo")], tmp_path, log_changes=False,
    )

    assert loaded == [filepath]
    assert set(_promotions(conn, chain_id, store_id)) == {"OK_PROMO"}


def test_unknown_chain_is_skipped(
    conn, mock_chain_metadata, monkeypatch, tmp_path,
):
    chain_id = "1231231231231"
    store_id = "1"

    promotion = Promotion(
        chain_id=chain_id,
        promotion_id="UNKNOWN_CHAIN_PROMO",
        store_id=store_id,
        description="test",
        start_datetime=None,
        end_datetime=None,
        start_hour=None,
        end_hour=None,
        promotion_days=None,
        update_time=None,
        club_id=None,
        is_gift_item=None,
        additional_is_coupon=False,
        allow_multiple_discounts=False,
        redemption_limit=None,
        min_no_of_items_offered=None,
        additional_restrictions=None,
        remarks=None,
        groups=[],
    )

    monkeypatch.setattr(
        StoreXmlParser,
        "parse_promo_file",
        lambda self, xml_content: [promotion],
    )

    monkeypatch.setattr(
        "utils.promos.update_promos.iter_xml_from_path",
        lambda path: [b"<Root/>"],
    )

    filepath = (
        tmp_path / chain_id / store_id / "promos"
        / f"Promo{chain_id}-001-001-20260101-000000.xml"
    )
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<Root/>")

    loaded = load_files(
        conn,
        [(filepath, "PromoFull")],
        tmp_path,
        log_changes=False,
    )

    assert loaded == []