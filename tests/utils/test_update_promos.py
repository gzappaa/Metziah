# tests/utils/test_update_promos.py

import gzip
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.update_promos import (
    _fetch_existing_promotion_items,
    _fetch_existing_promotions,
    _log_changes,
    load_files,
    load_one_file,
)


CHAIN_ID = "TEST_CHAIN"
STORE_ID = "TEST_STORE"


def make_item(
    item_code="ITEM_001",
    discounted_price="5.00",
    discount_rate="40.00",
):
    return SimpleNamespace(
        item_code=item_code,
        discounted_price=Decimal(discounted_price),
        discount_rate=Decimal(discount_rate),
    )


def make_group(
    group_id="1",
    items=None,
):
    return SimpleNamespace(
        group_id=group_id,
        promotion_id="PROMO_001",
        items=items or [],
    )


def make_promotion(
    promotion_id="PROMO_001",
    description="Test Promotion",
    end_datetime=None,
    groups=None,
):
    return SimpleNamespace(
        promotion_id=promotion_id,
        description=description,
        end_datetime=end_datetime,
        groups=groups or [],
    )


# ---------------------------------------------------------------------------
# _log_changes
# ---------------------------------------------------------------------------


def test_promotion_added_logs(caplog):
    promotion = make_promotion(
        promotion_id="PROMO_001",
        description="2 for 20",
    )

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "Promo",
            [promotion],
            set(),
            {},
            {},
        )

    assert "PROMOTION ADDED" in caplog.text
    assert "PROMO_001" in caplog.text


def test_promotion_unchanged_does_not_log(caplog):
    promotion = make_promotion(
        promotion_id="PROMO_001",
        description="2 for 20",
        end_datetime=datetime(2026, 8, 21),
    )

    existing_promotions = {
        "PROMO_001": (
            "2 for 20",
            datetime(2026, 8, 21),
        )
    }

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "Promo",
            [promotion],
            set(),
            existing_promotions,
            {},
        )

    assert "PROMOTION ADDED" not in caplog.text
    assert "PROMOTION CHANGED" not in caplog.text


def test_promotion_changed_logs(caplog):
    promotion = make_promotion(
        promotion_id="PROMO_001",
        description="3 for 20",
        end_datetime=datetime(2026, 8, 22),
    )

    existing_promotions = {
        "PROMO_001": (
            "2 for 20",
            datetime(2026, 8, 21),
        )
    }

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "Promo",
            [promotion],
            set(),
            existing_promotions,
            {},
        )

    assert "PROMOTION CHANGED" in caplog.text
    assert "PROMO_001" in caplog.text


def test_promo_item_added_logs(caplog):
    item = make_item(
        item_code="ITEM_001",
        discounted_price="5.00",
        discount_rate="40.00",
    )

    group = make_group(
        group_id="1",
        items=[item],
    )

    promotion = make_promotion(
        promotion_id="PROMO_001",
        groups=[group],
    )

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "Promo",
            [promotion],
            set(),
            {},
            {},
        )

    assert "PROMO ITEM ADDED" in caplog.text
    assert "ITEM_001" in caplog.text


def test_promo_item_unchanged_does_not_log(caplog):
    item = make_item(
        item_code="ITEM_001",
        discounted_price="5.00",
        discount_rate="40.00",
    )

    group = make_group(
        group_id="1",
        items=[item],
    )

    promotion = make_promotion(
        promotion_id="PROMO_001",
        groups=[group],
    )

    existing_items = {
        ("PROMO_001", "1", "ITEM_001"): (
            Decimal("5.00"),
            Decimal("40.00"),
        )
    }

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "Promo",
            [promotion],
            {
                ("PROMO_001", "1", "ITEM_001"),
            },
            {},
            existing_items,
        )

    assert "PROMO ITEM ADDED" not in caplog.text
    assert "PROMO ITEM CHANGED" not in caplog.text


def test_promo_item_changed_logs(caplog):
    item = make_item(
        item_code="ITEM_001",
        discounted_price="6.00",
        discount_rate="30.00",
    )

    group = make_group(
        group_id="1",
        items=[item],
    )

    promotion = make_promotion(
        promotion_id="PROMO_001",
        groups=[group],
    )

    existing_items = {
        ("PROMO_001", "1", "ITEM_001"): (
            Decimal("5.00"),
            Decimal("40.00"),
        )
    }

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "Promo",
            [promotion],
            {
                ("PROMO_001", "1", "ITEM_001"),
            },
            {},
            existing_items,
        )

    assert "PROMO ITEM CHANGED" in caplog.text
    assert "ITEM_001" in caplog.text


def test_promofull_removed_item_logs(caplog):
    existing_items = {
        ("PROMO_001", "1", "ITEM_001"): (
            Decimal("5.00"),
            Decimal("40.00"),
        )
    }

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "PromoFull",
            [],
            set(),
            {},
            existing_items,
        )

    assert "PROMO ITEM REMOVED" in caplog.text
    assert "ITEM_001" in caplog.text


def test_promo_removed_item_does_not_log(caplog):
    existing_items = {
        ("PROMO_001", "1", "ITEM_001"): (
            Decimal("5.00"),
            Decimal("40.00"),
        )
    }

    with caplog.at_level("INFO", logger="promo_changes"):
        _log_changes(
            CHAIN_ID,
            STORE_ID,
            "Promo",
            [],
            set(),
            {},
            existing_items,
        )

    assert "PROMO ITEM REMOVED" not in caplog.text


# ---------------------------------------------------------------------------
# _fetch_existing_promotions
# ---------------------------------------------------------------------------


def test_fetch_existing_promotions_empty_ids_returns_empty_without_query():
    class FakeConnection:
        def cursor(self):
            raise AssertionError("cursor should not be called")

    result = _fetch_existing_promotions(
        FakeConnection(),
        CHAIN_ID,
        STORE_ID,
        set(),
    )

    assert result == {}


def test_fetch_existing_promotions_returns_mapping():
    class FakeCursor:
        def execute(self, query, params):
            self.params = params

        def fetchall(self):
            return [
                (
                    "PROMO_001",
                    "2 for 20",
                    datetime(2026, 8, 21),
                ),
                (
                    "PROMO_002",
                    "3 for 30",
                    datetime(2026, 8, 22),
                ),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    result = _fetch_existing_promotions(
        FakeConnection(),
        CHAIN_ID,
        STORE_ID,
        {"PROMO_001", "PROMO_002"},
    )

    assert result == {
        "PROMO_001": (
            "2 for 20",
            datetime(2026, 8, 21),
        ),
        "PROMO_002": (
            "3 for 30",
            datetime(2026, 8, 22),
        ),
    }


# ---------------------------------------------------------------------------
# _fetch_existing_promotion_items
# ---------------------------------------------------------------------------


def test_fetch_existing_promotion_items_returns_mapping():
    class FakeCursor:
        def execute(self, query, params):
            self.params = params

        def fetchall(self):
            return [
                (
                    "PROMO_001",
                    "1",
                    "ITEM_001",
                    Decimal("5.00"),
                    Decimal("40.00"),
                ),
                (
                    "PROMO_002",
                    "2",
                    "ITEM_002",
                    Decimal("7.50"),
                    Decimal("25.00"),
                ),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    result = _fetch_existing_promotion_items(
        FakeConnection(),
        CHAIN_ID,
        STORE_ID,
    )

    assert result == {
        ("PROMO_001", "1", "ITEM_001"): (
            Decimal("5.00"),
            Decimal("40.00"),
        ),
        ("PROMO_002", "2", "ITEM_002"): (
            Decimal("7.50"),
            Decimal("25.00"),
        ),
    }


# ---------------------------------------------------------------------------
# load_one_file -- mocked dependencies
# ---------------------------------------------------------------------------


def test_load_one_file_invalid_type_raises():
    with pytest.raises(ValueError, match="Unsupported promo file type"):
        load_one_file(
            None,
            None,
            Path("test.gz"),
            Path("."),
            "INVALID",
        )


def test_load_one_file_empty_xml_does_nothing(
    monkeypatch,
    tmp_path,
):
    filepath = (
        tmp_path
        / CHAIN_ID
        / "003"
        / STORE_ID
        / "promos"
        / "test.gz"
    )
    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    class FakeParser:
        def parse_promo_file(self, xml_content):
            return []

    load_one_file(
        None,
        FakeParser(),
        filepath,
        tmp_path,
        "Promo",
        log_changes=False,
    )


def test_load_one_file_log_changes_false_skips_snapshots(
    monkeypatch,
    tmp_path,
):
    filepath = (
        tmp_path
        / CHAIN_ID
        / "003"
        / STORE_ID
        / "promos"
        / "test.gz"
    )
    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    promotion = make_promotion()

    class FakeParser:
        def parse_promo_file(self, xml_content):
            return [promotion]

    def fail(*args, **kwargs):
        raise AssertionError("snapshot query should not be called")

    monkeypatch.setattr(
        "utils.update_promos._fetch_existing_promotions",
        fail,
    )
    monkeypatch.setattr(
        "utils.update_promos._fetch_existing_promotion_items",
        fail,
    )

    monkeypatch.setattr(
        "utils.update_promos.ensure_chain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.update_store_subchain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotions",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotion_groups",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotion_items",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotions",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotion_groups",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotion_items",
        lambda *args, **kwargs: 0,
    )

    monkeypatch.setattr(
        "utils.update_promos.split_promotion",
        lambda promotion: (promotion, [], []),
    )

    class FakeConnection:
        def commit(self):
            pass

    load_one_file(
        FakeConnection(),
        FakeParser(),
        filepath,
        tmp_path,
        "Promo",
        log_changes=False,
    )


# ---------------------------------------------------------------------------
# Promo vs PromoFull reconciliation
# ---------------------------------------------------------------------------


def test_promo_does_not_reconcile(
    monkeypatch,
    tmp_path,
):
    filepath = (
        tmp_path
        / CHAIN_ID
        / "003"
        / STORE_ID
        / "promos"
        / "test.gz"
    )
    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    promotion = make_promotion()

    class FakeParser:
        def parse_promo_file(self, xml_content):
            return [promotion]

    calls = []

    monkeypatch.setattr(
        "utils.update_promos.split_promotion",
        lambda promotion: (promotion, [], []),
    )
    monkeypatch.setattr(
        "utils.update_promos.ensure_chain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.update_store_subchain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotions",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotion_groups",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotion_items",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotions",
        lambda *args, **kwargs: calls.append("promotions"),
    )
    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotion_groups",
        lambda *args, **kwargs: calls.append("groups"),
    )
    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotion_items",
        lambda *args, **kwargs: calls.append("items"),
    )

    class FakeConnection:
        def commit(self):
            pass

    load_one_file(
        FakeConnection(),
        FakeParser(),
        filepath,
        tmp_path,
        "Promo",
        log_changes=False,
    )

    assert calls == []


def test_promofull_reconciles_promotions_groups_and_items(
    monkeypatch,
    tmp_path,
):
    filepath = (
        tmp_path
        / CHAIN_ID
        / "003"
        / STORE_ID
        / "promosfull"
        / "test.gz"
    )
    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    promotion = make_promotion()

    class FakeParser:
        def parse_promo_file(self, xml_content):
            return [promotion]

    calls = []

    monkeypatch.setattr(
        "utils.update_promos.split_promotion",
        lambda promotion: (promotion, [], []),
    )
    monkeypatch.setattr(
        "utils.update_promos.ensure_chain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.update_store_subchain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotions",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotion_groups",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "utils.update_promos.upsert_promotion_items",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotions",
        lambda *args, **kwargs: calls.append("promotions") or 1,
    )
    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotion_groups",
        lambda *args, **kwargs: calls.append("groups") or 2,
    )
    monkeypatch.setattr(
        "utils.update_promos.reconcile_removed_promotion_items",
        lambda *args, **kwargs: calls.append("items") or 3,
    )

    class FakeConnection:
        def commit(self):
            pass

    load_one_file(
        FakeConnection(),
        FakeParser(),
        filepath,
        tmp_path,
        "PromoFull",
        log_changes=False,
    )

    assert calls == [
        "promotions",
        "groups",
        "items",
    ]


# ---------------------------------------------------------------------------
# load_files
# ---------------------------------------------------------------------------


def test_load_files_continues_after_failure(monkeypatch):
    files = [
        (Path("file1.gz"), "Promo"),
        (Path("file2.gz"), "PromoFull"),
    ]

    processed = []

    def fake_load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
        file_type,
        log_changes=True,
    ):
        processed.append((filepath, file_type))

        if filepath == files[0][0]:
            raise RuntimeError("test failure")

    monkeypatch.setattr(
        "utils.update_promos.load_one_file",
        fake_load_one_file,
    )

    monkeypatch.setattr(
        "utils.update_promos.mark_files_loaded",
        lambda conn, filenames: None,
    )

    class FakeConnection:
        def rollback(self):
            pass

        def commit(self):
            pass

    loaded = load_files(
        FakeConnection(),
        files,
        Path("data/test_feeds"),
    )

    assert processed == files
    assert loaded == [files[1][0]]


def test_load_files_rolls_back_on_failure(monkeypatch):
    filepath = Path("file.gz")

    def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(
        "utils.update_promos.load_one_file",
        fail,
    )

    monkeypatch.setattr(
        "utils.update_promos.mark_files_loaded",
        lambda conn, filenames: None,
    )

    class FakeConnection:
        def __init__(self):
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            pass

    conn = FakeConnection()

    loaded = load_files(
        conn,
        [(filepath, "Promo")],
        Path("data/test_feeds"),
    )

    assert conn.rolled_back is True
    assert loaded == []


def test_load_files_marks_only_successful_files_loaded(monkeypatch):
    files = [
        (Path("good.gz"), "Promo"),
        (Path("bad.gz"), "Promo"),
    ]

    marked = []

    def fake_load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
        file_type,
        log_changes=True,
    ):
        if filepath == files[1][0]:
            raise RuntimeError("failure")

    monkeypatch.setattr(
        "utils.update_promos.load_one_file",
        fake_load_one_file,
    )

    monkeypatch.setattr(
        "utils.update_promos.mark_files_loaded",
        lambda conn, filenames: marked.extend(filenames),
    )

    class FakeConnection:
        def rollback(self):
            pass

        def commit(self):
            pass

    loaded = load_files(
        FakeConnection(),
        files,
        Path("data/test_feeds"),
    )

    assert loaded == [files[0][0]]
    assert marked == ["good.gz"]