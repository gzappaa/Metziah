from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import utils.prices.load_prices as module


CHAIN_ID = "7290000000001"
SUB_CHAIN_ID = "1"
STORE_ID = "42"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_pricefull(tmp_path, filename, chain_id=CHAIN_ID, store_id=STORE_ID):
    path = (
        tmp_path
        / chain_id
        / store_id
        / "pricesfull"
        / filename
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


# ---------------------------------------------------------------------------
# find_pricefull_files
# ---------------------------------------------------------------------------


def test_find_pricefull_files_returns_latest_per_chain_subchain_store(
    tmp_path,
    monkeypatch,
):
    old = make_pricefull(tmp_path, "old.xml")
    new = make_pricefull(tmp_path, "new.xml")

    parse_results = {
        "old.xml": {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": SUB_CHAIN_ID,
            "store_id": STORE_ID,
            "file_date": "2026-09-23",
        },
        "new.xml": {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": SUB_CHAIN_ID,
            "store_id": STORE_ID,
            "file_date": "2026-09-24",
        },
    }

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: parse_results[filename],
    )

    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: "120000",
    )

    result = list(module.find_pricefull_files(tmp_path))

    assert result == [
        (new, "PriceFull", True),
    ]


def test_find_pricefull_files_uses_timestamp_when_date_is_same(
    tmp_path,
    monkeypatch,
):
    old = make_pricefull(tmp_path, "old.xml")
    new = make_pricefull(tmp_path, "new.xml")

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": SUB_CHAIN_ID,
            "store_id": STORE_ID,
            "file_date": "2026-09-24",
        },
    )

    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: {
            "old.xml": "100000",
            "new.xml": "120000",
        }[filename],
    )

    result = list(module.find_pricefull_files(tmp_path))

    assert result == [
        (new, "PriceFull", True),
    ]


def test_find_pricefull_files_keeps_different_stores(
    tmp_path,
    monkeypatch,
):
    store_1 = make_pricefull(
        tmp_path,
        "store1.xml",
        store_id="1",
    )
    store_2 = make_pricefull(
        tmp_path,
        "store2.xml",
        store_id="2",
    )

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": SUB_CHAIN_ID,
            "store_id": "1" if filename == "store1.xml" else "2",
            "file_date": "2026-09-24",
        },
    )

    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: "120000",
    )

    result = list(module.find_pricefull_files(tmp_path))

    assert set(result) == {
        (store_1, "PriceFull", True),
        (store_2, "PriceFull", True),
    }


def test_find_pricefull_files_keeps_different_subchains(
    tmp_path,
    monkeypatch,
):
    subchain_1 = make_pricefull(tmp_path, "sub1.xml")
    subchain_2 = make_pricefull(tmp_path, "sub2.xml")

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": "1" if filename == "sub1.xml" else "2",
            "store_id": STORE_ID,
            "file_date": "2026-09-24",
        },
    )

    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: "120000",
    )

    result = list(module.find_pricefull_files(tmp_path))

    assert set(result) == {
        (subchain_1, "PriceFull", True),
        (subchain_2, "PriceFull", True),
    }


def test_find_pricefull_files_ignores_non_pricefull(
    tmp_path,
    monkeypatch,
):
    path = make_pricefull(tmp_path, "price.xml")

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: {
            "file_type": "Price",
            "chain_id": CHAIN_ID,
            "sub_chain_id": SUB_CHAIN_ID,
            "store_id": STORE_ID,
            "file_date": "2026-09-24",
        },
    )

    result = list(module.find_pricefull_files(tmp_path))

    assert result == []


def test_find_pricefull_files_skips_invalid_filename(
    tmp_path,
    monkeypatch,
):
    path = make_pricefull(tmp_path, "invalid.xml")

    def raise_value_error(filename):
        raise ValueError("invalid filename")

    monkeypatch.setattr(
        module,
        "parse_filename",
        raise_value_error,
    )

    result = list(module.find_pricefull_files(tmp_path))

    assert result == []


def test_find_pricefull_files_returns_pricefull_metadata(
    tmp_path,
    monkeypatch,
):
    path = make_pricefull(tmp_path, "snapshot.xml")

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": SUB_CHAIN_ID,
            "store_id": STORE_ID,
            "file_date": "2026-09-24",
        },
    )

    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: "120000",
    )

    result = list(module.find_pricefull_files(tmp_path))

    assert result == [
        (path, "PriceFull", True),
    ]


# ---------------------------------------------------------------------------
# main - environment safety
# ---------------------------------------------------------------------------


def test_main_requires_dev_flag_for_dev_environment(monkeypatch):
    monkeypatch.setattr(module.settings, "ENV", "dev")
    monkeypatch.setattr(
        module,
        "get_connection",
        Mock(),
    )

    monkeypatch.setattr(
        module,
        "BASE_DIR",
        Path("/repo"),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["load_prices.py"],
    )

    with pytest.raises(
        RuntimeError,
        match="Development database selected",
    ):
        module.main()


def test_main_rejects_dev_flag_outside_dev(monkeypatch):
    monkeypatch.setattr(module.settings, "ENV", "test")

    monkeypatch.setattr(
        "sys.argv",
        ["load_prices.py", "--dev"],
    )

    with pytest.raises(
        RuntimeError,
        match="--dev was provided",
    ):
        module.main()


def test_main_rejects_test_flag_outside_test(monkeypatch):
    monkeypatch.setattr(module.settings, "ENV", "prod")

    monkeypatch.setattr(
        "sys.argv",
        ["load_prices.py", "--test"],
    )

    with pytest.raises(
        RuntimeError,
        match="--test was provided",
    ):
        module.main()


# ---------------------------------------------------------------------------
# main - feeds directory
# ---------------------------------------------------------------------------


def test_main_test_flag_uses_test_feeds_dir(monkeypatch):
    monkeypatch.setattr(module.settings, "ENV", "test")

    monkeypatch.setattr(
        module,
        "TEST_FEEDS_DIR",
        Path("/repo/data/test_feeds"),
    )

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["load_prices.py", "--test"],
    )

    module.main()

    module.find_pricefull_files.assert_called_once_with(
        Path("/repo/data/test_feeds").resolve(),
    )


def test_main_resolves_relative_feeds_dir_from_base_dir(monkeypatch):
    monkeypatch.setattr(module.settings, "ENV", "test")

    monkeypatch.setattr(
        module,
        "BASE_DIR",
        Path("/repo"),
    )

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["load_prices.py", "--feeds-dir", "custom/feeds"],
    )

    module.main()

    module.find_pricefull_files.assert_called_once_with(
        Path("/repo/custom/feeds").resolve(),
    )


def test_main_keeps_absolute_feeds_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(module.settings, "ENV", "test")

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_prices.py",
            "--feeds-dir",
            str(tmp_path),
        ],
    )

    module.main()

    module.find_pricefull_files.assert_called_once_with(
        tmp_path.resolve(),
    )


# ---------------------------------------------------------------------------
# main - no files
# ---------------------------------------------------------------------------


def test_main_returns_without_connecting_when_no_files(monkeypatch, tmp_path):
    monkeypatch.setattr(module.settings, "ENV", "test")

    find_files = Mock(return_value=[])

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        find_files,
    )

    get_connection = Mock()

    monkeypatch.setattr(
        module,
        "get_connection",
        get_connection,
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_prices.py",
            "--feeds-dir",
            str(tmp_path),
        ],
    )

    module.main()

    find_files.assert_called_once_with(tmp_path.resolve())
    get_connection.assert_not_called()


# ---------------------------------------------------------------------------
# main - loading
# ---------------------------------------------------------------------------


def test_main_loads_discovered_files(monkeypatch, tmp_path):
    monkeypatch.setattr(module.settings, "ENV", "test")

    filepath = tmp_path / "snapshot.xml"

    files = [
        (filepath, "PriceFull", True),
    ]

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        Mock(return_value=files),
    )

    load_files = Mock()

    monkeypatch.setattr(
        module,
        "load_files",
        load_files,
    )

    conn = MagicMock()

    connection = MagicMock()
    connection.__enter__.return_value = conn

    monkeypatch.setattr(
        module,
        "get_connection",
        Mock(return_value=connection),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_prices.py",
            "--feeds-dir",
            str(tmp_path),
        ],
    )

    module.main()

    load_files.assert_called_once_with(
        conn,
        files,
        tmp_path.resolve(),
        log_changes=False,
    )


def test_main_does_not_load_when_no_files(monkeypatch, tmp_path):
    monkeypatch.setattr(module.settings, "ENV", "test")

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        Mock(return_value=[]),
    )

    load_files = Mock()

    monkeypatch.setattr(
        module,
        "load_files",
        load_files,
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_prices.py",
            "--feeds-dir",
            str(tmp_path),
        ],
    )

    module.main()

    load_files.assert_not_called()


# ---------------------------------------------------------------------------
# main - dev allowed
# ---------------------------------------------------------------------------


def test_main_allows_dev_with_dev_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(module.settings, "ENV", "dev")

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "load_prices.py",
            "--dev",
            "--feeds-dir",
            str(tmp_path),
        ],
    )

    module.main()