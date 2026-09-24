# tests/utils/promos/test_update_promos.py

from pathlib import Path
from unittest.mock import Mock

import pytest

import utils.promos.update_promos as module
from parsers.xml import StoreXmlParser


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHAIN_ID = "9999999999999"
STORE_ID = "1"

BASE_DIR = Path(__file__).resolve().parents[3]

FEEDS_DIR = BASE_DIR / "tests" / "fixtures"

PROMO_FILE = (
    FEEDS_DIR
    / CHAIN_ID
    / STORE_ID
    / "promos"
    / "Promo9999999999999-001-001-20260101-000001.xml"
)

PROMOFULL_FILE = (
    FEEDS_DIR
    / CHAIN_ID
    / STORE_ID
    / "promosfull"
    / "PromoFull9999999999999-001-001-20260101-000000.xml"
)

CHAIN_METADATA = {
    CHAIN_ID: {
        "name_he_normalized": "Test",
        "name_en_normalized": "Test",
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def patch_common(monkeypatch):
    monkeypatch.setattr(
        module,
        "ensure_chain",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "update_store_subchain",
        Mock(),
    )


def patch_upserts(monkeypatch):
    monkeypatch.setattr(
        module,
        "upsert_promotions",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "upsert_promotion_groups",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "upsert_promotion_items",
        Mock(),
    )


def patch_reconciliation(monkeypatch):
    monkeypatch.setattr(
        module,
        "reconcile_removed_promotions",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "reconcile_removed_promotion_groups",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "reconcile_removed_promotion_items",
        Mock(),
    )


# ---------------------------------------------------------------------------
# load_one_file - validation
# ---------------------------------------------------------------------------

def test_load_one_file_rejects_invalid_file_type(
    tmp_path,
):
    conn = Mock()

    with pytest.raises(
        ValueError,
        match="Unsupported promo file type",
    ):
        module.load_one_file(
            conn=conn,
            parser=Mock(),
            filepath=tmp_path / "test.xml",
            feeds_dir=tmp_path,
            file_type="Price",
            chain_metadata=CHAIN_METADATA,
        )


# ---------------------------------------------------------------------------
# Promo
# ---------------------------------------------------------------------------

def test_promo_upserts_without_reconciliation(
    monkeypatch,
):
    conn = Mock()

    patch_common(monkeypatch)
    patch_upserts(monkeypatch)
    patch_reconciliation(monkeypatch)

    parser = StoreXmlParser()

    module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=PROMO_FILE,
        feeds_dir=FEEDS_DIR,
        file_type="Promo",
        chain_metadata=CHAIN_METADATA,
        log_changes=False,
    )

    # Upserts happen.
    module.upsert_promotions.assert_called_once()
    module.upsert_promotion_groups.assert_called_once()
    module.upsert_promotion_items.assert_called_once()

    promotions = (
        module.upsert_promotions.call_args.args[1]
    )

    groups = (
        module.upsert_promotion_groups.call_args.args[1]
    )

    items = (
        module.upsert_promotion_items.call_args.args[1]
    )

    assert len(promotions) == 2
    assert len(groups) == 2
    assert len(items) == 2

    assert {
        promotion.promotion_id
        for promotion in promotions
    } == {
        "0000000001",
        "0000000003",
    }

    assert {
        (group.promotion_id, group.group_id)
        for group in groups
    } == {
        ("0000000001", "1"),
        ("0000000003", "1"),
    }

    assert {
        (
            item.promotion_id,
            item.group_id,
            item.item_code,
        )
        for item in items
    } == {
        ("0000000001", "1", "7290000000001"),
        ("0000000003", "1", "7290000000003"),
    }

    # Promo is incremental: NEVER reconcile.
    module.reconcile_removed_promotions.assert_not_called()
    module.reconcile_removed_promotion_groups.assert_not_called()
    module.reconcile_removed_promotion_items.assert_not_called()

    conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# PromoFull
# ---------------------------------------------------------------------------

def test_promofull_upserts_and_reconciles(
    monkeypatch,
):
    conn = Mock()

    patch_common(monkeypatch)
    patch_upserts(monkeypatch)
    patch_reconciliation(monkeypatch)

    parser = StoreXmlParser()

    module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=PROMOFULL_FILE,
        feeds_dir=FEEDS_DIR,
        file_type="PromoFull",
        chain_metadata=CHAIN_METADATA,
        log_changes=False,
    )

    # Upserts happen.
    module.upsert_promotions.assert_called_once()
    module.upsert_promotion_groups.assert_called_once()
    module.upsert_promotion_items.assert_called_once()

    # PromoFull reconciles promotions.
    module.reconcile_removed_promotions.assert_called_once_with(
        conn,
        CHAIN_ID,
        STORE_ID,
        {
            "0000000001",
            "0000000002",
        },
    )

    # PromoFull reconciles groups.
    module.reconcile_removed_promotion_groups.assert_called_once_with(
        conn,
        CHAIN_ID,
        STORE_ID,
        {
            ("0000000001", "1"),
            ("0000000002", "1"),
        },
    )

    # PromoFull reconciles items.
    module.reconcile_removed_promotion_items.assert_called_once_with(
        conn,
        CHAIN_ID,
        STORE_ID,
        {
            ("0000000001", "1", "7290000000001"),
            ("0000000002", "1", "7290000000002"),
        },
    )

    conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Path / identity
# ---------------------------------------------------------------------------

def test_path_chain_and_store_are_authoritative(
    monkeypatch,
    tmp_path,
):
    conn = Mock()

    feeds_dir = tmp_path / "feeds"

    filepath = (
        feeds_dir
        / CHAIN_ID
        / "004"
        / "promos"
        / "Promo9999999999999-001-001-20260101-000001.xml"
    )

    filepath.parent.mkdir(parents=True)

    # Use the real fixture content.
    fixture_content = PROMO_FILE.read_bytes()

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda _: [fixture_content],
    )

    patch_common(monkeypatch)
    patch_upserts(monkeypatch)
    patch_reconciliation(monkeypatch)

    parser = StoreXmlParser()

    module.load_one_file(
        conn=conn,
        parser=parser,
        filepath=filepath,
        feeds_dir=feeds_dir,
        file_type="Promo",
        chain_metadata=CHAIN_METADATA,
        log_changes=False,
    )

    module.ensure_chain.assert_called_once_with(
        conn,
        CHAIN_ID,
        "Test",
        "Test",
    )

    module.update_store_subchain.assert_called_once_with(
        conn,
        CHAIN_ID,
        "004",
        "001",
    )

    promotions = (
        module.upsert_promotions.call_args.args[1]
    )

    assert all(
        promotion.chain_id == CHAIN_ID
        for promotion in promotions
    )

    assert all(
        promotion.store_id == "004"
        for promotion in promotions
    )