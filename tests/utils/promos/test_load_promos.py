# tests/utils/promos/test_load_promos.py

from pathlib import Path
from unittest.mock import Mock

import pytest

import utils.promos.load_promos as module


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHAIN_ID = "9999999999999"
STORE_ID = "1"

BASE_DIR = Path(__file__).resolve().parents[3]

FEEDS_DIR = BASE_DIR / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# find_promofull_files
# ---------------------------------------------------------------------------

def test_find_promofull_files_returns_latest_per_chain_subchain_store(
    tmp_path,
):
    feeds_dir = tmp_path

    old_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-000000.xml"
    )

    new_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260102-000000.xml"
    )

    old_file.parent.mkdir(parents=True)

    old_file.write_text("old")
    new_file.write_text("new")

    result = list(
        module.find_promofull_files(feeds_dir)
    )

    assert result == [
        (new_file, "PromoFull"),
    ]


def test_find_promofull_files_uses_timestamp_when_dates_match(
    tmp_path,
):
    feeds_dir = tmp_path

    earlier_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-100000.xml"
    )

    later_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-120000.xml"
    )

    earlier_file.parent.mkdir(parents=True)

    earlier_file.write_text("earlier")
    later_file.write_text("later")

    result = list(
        module.find_promofull_files(feeds_dir)
    )

    assert result == [
        (later_file, "PromoFull"),
    ]


def test_find_promofull_files_keeps_different_stores(
    tmp_path,
):
    feeds_dir = tmp_path

    store_1 = (
        feeds_dir
        / CHAIN_ID
        / "1"
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-000000.xml"
    )

    store_2 = (
        feeds_dir
        / CHAIN_ID
        / "2"
        / "promosfull"
        / "PromoFull9999999999999-001-002-20260101-000000.xml"
    )

    store_1.parent.mkdir(parents=True)
    store_2.parent.mkdir(parents=True)

    store_1.write_text("store 1")
    store_2.write_text("store 2")

    result = list(
        module.find_promofull_files(feeds_dir)
    )

    assert set(result) == {
        (store_1, "PromoFull"),
        (store_2, "PromoFull"),
    }


def test_find_promofull_files_keeps_different_subchains(
    tmp_path,
):
    feeds_dir = tmp_path

    subchain_1 = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-000000.xml"
    )

    subchain_2 = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-002-001-20260101-000000.xml"
    )

    subchain_1.parent.mkdir(parents=True)

    subchain_1.write_text("subchain 1")
    subchain_2.write_text("subchain 2")

    result = list(
        module.find_promofull_files(feeds_dir)
    )

    assert set(result) == {
        (subchain_1, "PromoFull"),
        (subchain_2, "PromoFull"),
    }


def test_find_promofull_files_ignores_non_promofull_files(
    tmp_path,
):
    feeds_dir = tmp_path

    promofull_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-000000.xml"
    )

    promo_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "Promo9999999999999-001-001-20260101-000001.xml"
    )

    promofull_file.parent.mkdir(parents=True)

    promofull_file.write_text("promofull")
    promo_file.write_text("promo")

    result = list(
        module.find_promofull_files(feeds_dir)
    )

    assert result == [
        (promofull_file, "PromoFull"),
    ]


def test_find_promofull_files_skips_invalid_filename(
    tmp_path,
):
    feeds_dir = tmp_path

    valid_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "PromoFull9999999999999-001-001-20260101-000000.xml"
    )

    invalid_file = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "promosfull"
        / "not-a-valid-feed.xml"
    )

    valid_file.parent.mkdir(parents=True)

    valid_file.write_text("valid")
    invalid_file.write_text("invalid")

    result = list(
        module.find_promofull_files(feeds_dir)
    )

    assert result == [
        (valid_file, "PromoFull"),
    ]


# ---------------------------------------------------------------------------
# main - environment safety
# ---------------------------------------------------------------------------

def test_main_rejects_dev_without_confirmation(
    monkeypatch,
):
    monkeypatch.setattr(
        module.settings,
        "ENV",
        "dev",
    )

    monkeypatch.setattr(
        module,
        "get_connection",
        Mock(),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["load_promos.py"],
    )

    with pytest.raises(
        RuntimeError,
        match="Development database selected",
    ):
        module.main()


def test_main_rejects_dev_flag_outside_dev(
    monkeypatch,
):
    monkeypatch.setattr(
        module.settings,
        "ENV",
        "test",
    )

    monkeypatch.setattr(
        "sys.argv",
        ["load_promos.py", "--dev"],
    )

    with pytest.raises(
        RuntimeError,
        match="--dev was provided",
    ):
        module.main()


def test_main_rejects_test_flag_outside_test(
    monkeypatch,
):
    monkeypatch.setattr(
        module.settings,
        "ENV",
        "prod",
    )

    monkeypatch.setattr(
        "sys.argv",
        ["load_promos.py", "--test"],
    )

    with pytest.raises(
        RuntimeError,
        match="--test was provided",
    ):
        module.main()


# ---------------------------------------------------------------------------
# main - feeds directory
# ---------------------------------------------------------------------------

def test_main_resolves_relative_feeds_dir(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        module.settings,
        "ENV",
        "prod",
    )

    monkeypatch.setattr(
        module,
        "find_promofull_files",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_promos.py",
            "--feeds-dir",
            "custom/feeds",
        ],
    )

    module.main()

    module.find_promofull_files.assert_called_once_with(
        (module.BASE_DIR / "custom/feeds").resolve()
    )


def test_main_uses_test_feeds_when_test_flag_is_given(
    monkeypatch,
):
    monkeypatch.setattr(
        module.settings,
        "ENV",
        "test",
    )

    monkeypatch.setattr(
        module,
        "find_promofull_files",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_promos.py",
            "--test",
        ],
    )

    module.main()

    module.find_promofull_files.assert_called_once_with(
        module.TEST_FEEDS_DIR.resolve()
    )


# ---------------------------------------------------------------------------
# main - loading
# ---------------------------------------------------------------------------

def test_main_loads_discovered_files(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        module.settings,
        "ENV",
        "prod",
    )

    feeds_dir = tmp_path / "feeds"

    files = [
        (
            feeds_dir
            / CHAIN_ID
            / STORE_ID
            / "promosfull"
            / "PromoFull9999999999999-001-001-20260101-000000.xml",
            "PromoFull",
        )
    ]

    monkeypatch.setattr(
        module,
        "find_promofull_files",
        Mock(return_value=files),
    )

    connection = Mock()

    get_connection = Mock()
    get_connection.return_value.__enter__ = Mock(
        return_value=connection
    )
    get_connection.return_value.__exit__ = Mock(
        return_value=False
    )

    monkeypatch.setattr(
        module,
        "get_connection",
        get_connection,
    )

    monkeypatch.setattr(
        module,
        "load_files",
        Mock(),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_promos.py",
            "--feeds-dir",
            str(feeds_dir),
        ],
    )

    module.main()

    module.find_promofull_files.assert_called_once_with(
        feeds_dir.resolve()
    )

    module.load_files.assert_called_once_with(
        connection,
        files,
        feeds_dir.resolve(),
        log_changes=False,
    )


def test_main_returns_when_no_files_found(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        module.settings,
        "ENV",
        "prod",
    )

    feeds_dir = tmp_path / "feeds"

    monkeypatch.setattr(
        module,
        "find_promofull_files",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        module,
        "load_files",
        Mock(),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_promos.py",
            "--feeds-dir",
            str(feeds_dir),
        ],
    )

    module.main()

    module.load_files.assert_not_called()