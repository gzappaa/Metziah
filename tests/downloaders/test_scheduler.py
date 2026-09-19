from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from downloaders import scheduler


def mock_conn(monkeypatch):
    conn = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(
        scheduler,
        "get_connection",
        MagicMock(return_value=ctx),
    )

    return conn


# ---- helper functions ----

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("006", "6"),
        ("06", "6"),
        ("6", "6"),
        (6, "6"),
        (None, "None"),
        ("abc", "abc"),
    ],
)
def test_normalize_store_id(value, expected):
    assert scheduler._normalize_store_id(value) == expected


def test_load_chain_metadata_extra_overrides_base(
    monkeypatch,
    tmp_path,
):
    chains_file = tmp_path / "chains.json"
    chains_extra_file = tmp_path / "chains_extra.json"

    chains_file.write_text(
        '{"123": {"client": "OtherClient"}}',
        encoding="utf-8",
    )

    chains_extra_file.write_text(
        '{"123": {"client": "LaibcatalogClient"}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        scheduler,
        "CHAINS_FILE",
        chains_file,
    )
    monkeypatch.setattr(
        scheduler,
        "CHAINS_EXTRA_FILE",
        chains_extra_file,
    )

    metadata = scheduler._load_chain_metadata()

    assert metadata["123"]["client"] == "LaibcatalogClient"


# ---- main() / test-mode safety ----

def test_main_test_requires_env_test(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py", "--test"],
    )
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    run_all = MagicMock()
    monkeypatch.setattr(scheduler, "run_all", run_all)

    scheduler.main()

    run_all.assert_not_called()


def test_main_test_requires_test_flag(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py"],
    )
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    run_all = MagicMock()
    monkeypatch.setattr(scheduler, "run_all", run_all)

    scheduler.main()

    run_all.assert_not_called()


def test_main_test_runs_with_both_protections(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py", "--test"],
    )
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    monkeypatch.setattr(
        scheduler,
        "run_file_tracking",
        MagicMock(return_value=True),
    )

    run_all = MagicMock()
    monkeypatch.setattr(scheduler, "run_all", run_all)

    scheduler.main()

    run_all.assert_called_once()


# ---- run_all() ----

def test_run_all_test_env_skips_pricesfull(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "ENV", "test")

    pricesfull = MagicMock()
    promos = MagicMock()
    prices = MagicMock()

    monkeypatch.setattr(scheduler, "run_pricesfull", pricesfull)
    monkeypatch.setattr(scheduler, "run_promos_and_load", promos)
    monkeypatch.setattr(scheduler, "run_prices_and_load", prices)

    scheduler.run_all()

    pricesfull.assert_not_called()
    promos.assert_called_once()
    prices.assert_called_once()


def test_run_all_non_test_env_runs_pricesfull(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "ENV", "dev")

    pricesfull = MagicMock()
    promos = MagicMock()
    prices = MagicMock()

    monkeypatch.setattr(scheduler, "run_pricesfull", pricesfull)
    monkeypatch.setattr(scheduler, "run_promos_and_load", promos)
    monkeypatch.setattr(scheduler, "run_prices_and_load", prices)

    scheduler.run_all()

    pricesfull.assert_called_once()
    promos.assert_called_once()
    prices.assert_called_once()


def test_run_all_test_env_runs_promos_before_prices(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "ENV", "test")

    calls = []

    monkeypatch.setattr(
        scheduler,
        "run_promos_and_load",
        lambda: calls.append("promos"),
    )
    monkeypatch.setattr(
        scheduler,
        "run_prices_and_load",
        lambda: calls.append("prices"),
    )

    scheduler.run_all()

    assert calls == ["promos", "prices"]


# ---- run_prices_and_load() ----

def test_run_prices_passes_test_flag(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    download_prices = AsyncMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "download_prices",
        download_prices,
    )

    scheduler.run_prices_and_load()

    download_prices.assert_awaited_once_with(test=True)


def test_run_prices_passes_test_false(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    download_prices = AsyncMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "download_prices",
        download_prices,
    )

    scheduler.run_prices_and_load()

    download_prices.assert_awaited_once_with(test=False)


def test_run_prices_download_failure_stops(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(side_effect=Exception("download failed")),
    )

    load_price_files = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    load_price_files.assert_not_called()


def test_run_prices_no_pricefull_or_price_files_stops(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=[]),
    )

    load_price_files = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    load_price_files.assert_not_called()


def test_run_prices_builds_price_path(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )

    rows = [
        (
            "7290644700005",
            "001",
            "020",
            "Price",
            "Price7290644700005-001-020.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=rows),
    )

    load_price_files = MagicMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    files = load_price_files.call_args.args[1]

    assert files == [
        (
            tmp_path
            / "7290644700005"
            / "020"
            / "prices"
            / "Price7290644700005-001-020.gz",
            "Price",
            False,
        )
    ]


def test_run_prices_snapshot_false(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )

    rows = [
        (
            "7290644700005",
            "001",
            "007",
            "Price",
            "Price7290644700005-001-007.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=rows),
    )

    load_price_files = MagicMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    files = load_price_files.call_args.args[1]

    assert files == [
        (
            tmp_path
            / "7290644700005"
            / "007"
            / "prices"
            / "Price7290644700005-001-007.gz",
            "Price",
            False,
        )
    ]


def test_run_prices_ignores_ignored_store(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )

    rows = [
        (
            "7290058108879",
            "001",
            "006",
            "Price",
            "Price7290058108879-001-006.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=rows),
    )

    load_price_files = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    load_price_files.assert_not_called()


def test_run_prices_loads_pending_pricefull(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    pricefull_rows = [
        (
            "7290058108879",
            "001",
            "006",
            "PriceFull",
            "PriceFull7290058108879-001-006.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=pricefull_rows),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=[]),
    )

    load_price_files = MagicMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    files = load_price_files.call_args.args[1]

    assert files == [
        (
            tmp_path
            / "7290058108879"
            / "006"
            / "pricesfull"
            / "PriceFull7290058108879-001-006.gz",
            "PriceFull",
            True,
        )
    ]


def test_run_prices_snapshot_true(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )

    rows = [
        (
            "7290661400001",
            "001",
            "002",
            "Price",
            "Price7290661400001-001-002.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=rows),
    )

    load_price_files = MagicMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    files = load_price_files.call_args.args[1]

    assert files == [
        (
            tmp_path
            / "7290661400001"
            / "002"
            / "prices"
            / "Price7290661400001-001-002.gz",
            "Price",
            True,
        )
    ]


def test_run_prices_loads_pricefull_before_price(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    pricefull_rows = [
        (
            "7290058108879",
            "001",
            "006",
            "PriceFull",
            "PriceFull7290058108879-001-006.gz",
            "2026-09-16",
        ),
    ]

    price_rows = [
        (
            "7290644700005",
            "001",
            "020",
            "Price",
            "Price7290644700005-001-020.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=pricefull_rows),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=price_rows),
    )

    calls = []

    def load_price_files(conn, files, feed_dir):
        calls.append(files)
        return []

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    scheduler.run_prices_and_load()

    assert calls == [
        [
            (
                tmp_path
                / "7290058108879"
                / "006"
                / "pricesfull"
                / "PriceFull7290058108879-001-006.gz",
                "PriceFull",
                True,
            )
        ],
        [
            (
                tmp_path
                / "7290644700005"
                / "020"
                / "prices"
                / "Price7290644700005-001-020.gz",
                "Price",
                False,
            )
        ],
    ]


# ---- mark_downloaded() ----

def test_mark_downloaded_empty_skips_db(monkeypatch):
    mark_files_downloaded = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_files_downloaded",
        mark_files_downloaded,
    )

    scheduler.mark_downloaded([])

    mark_files_downloaded.assert_not_called()


def test_mark_downloaded_marks_files_and_commits(monkeypatch):
    conn = mock_conn(monkeypatch)

    mark_files_downloaded = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_files_downloaded",
        mark_files_downloaded,
    )

    files = [
        Path("Price7290661400001-001-002.gz"),
        Path("Promo7290661400001-001-002.gz"),
    ]

    scheduler.mark_downloaded(files)

    mark_files_downloaded.assert_called_once_with(
        conn,
        [
            "Price7290661400001-001-002.gz",
            "Promo7290661400001-001-002.gz",
        ],
    )

    conn.commit.assert_called_once()


# ---- cleanup_old_price_files() ----

def test_cleanup_old_price_files_removes_old_snapshots(tmp_path):
    prices_dir = tmp_path / "7290661400001" / "002" / "prices"
    prices_dir.mkdir(parents=True)

    loaded = prices_dir / "Price7290661400001-001-002.gz"
    old = prices_dir / "Price7290661400001-001-001.gz"

    loaded.touch()
    old.touch()

    scheduler.cleanup_old_price_files(
        [
            (loaded, True),
        ]
    )

    assert loaded.exists()
    assert not old.exists()


def test_cleanup_old_price_files_keeps_delta_prices(tmp_path):
    prices_dir = tmp_path / "7290661400001" / "002" / "prices"
    prices_dir.mkdir(parents=True)

    loaded = prices_dir / "Price7290661400001-001-002.gz"
    old = prices_dir / "Price7290661400001-001-001.gz"

    loaded.touch()
    old.touch()

    scheduler.cleanup_old_price_files(
        [
            (loaded, False),
        ]
    )

    assert loaded.exists()
    assert old.exists()


def test_cleanup_old_price_files_keeps_files_outside_prices(tmp_path):
    pricesfull_dir = tmp_path / "7290661400001" / "002" / "pricesfull"
    pricesfull_dir.mkdir(parents=True)

    loaded = pricesfull_dir / "PriceFull7290661400001-001-002.gz"
    other = pricesfull_dir / "PriceFull7290661400001-001-001.gz"

    loaded.touch()
    other.touch()

    scheduler.cleanup_old_price_files(
        [
            (loaded, True),
        ]
    )

    assert loaded.exists()
    assert other.exists()


def test_run_prices_non_laibcatalog_price_is_delta(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(
            return_value=[
                "Price7290644700005-001-001.gz",
            ]
        ),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(
            return_value=[
                (
                    "7290644700005",
                    "001",
                    "001",
                    "Price",
                    "Price7290644700005-001-001.gz",
                    "2026-09-16",
                )
            ]
        ),
    )

    load_price_files = MagicMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        MagicMock(),
    )

    scheduler.run_prices_and_load()

    files = load_price_files.call_args.args[1]

    assert files == [
        (
            tmp_path
            / "7290644700005"
            / "001"
            / "prices"
            / "Price7290644700005-001-001.gz",
            "Price",
            False,
        )
    ]


def test_run_prices_cleans_old_snapshot_files_after_successful_load(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(
            return_value=[
                "Price7290661400001-001-002.gz",
            ]
        ),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(
            return_value=[
                (
                    "7290661400001",
                    "001",
                    "002",
                    "Price",
                    "Price7290661400001-001-002.gz",
                    "2026-09-16",
                )
            ]
        ),
    )

    loaded_file = (
        tmp_path
        / "7290661400001"
        / "002"
        / "prices"
        / "Price7290661400001-001-002.gz"
    )

    load_price_files = MagicMock(
        return_value=[loaded_file]
    )

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_price_files,
    )

    cleanup = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "cleanup_old_price_files",
        cleanup,
    )

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        MagicMock(),
    )

    scheduler.run_prices_and_load()

    cleanup.assert_called_once_with(
        [
            (loaded_file, True),
        ]
    )


# ---- run_pricesfull() ----

def test_run_pricesfull_passes_test_flag(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    download_pricefull = AsyncMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "download_pricefull",
        download_pricefull,
    )

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        MagicMock(),
    )

    scheduler.run_pricesfull()

    download_pricefull.assert_awaited_once_with(test=True)


def test_run_pricesfull_passes_test_false(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    download_pricefull = AsyncMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "download_pricefull",
        download_pricefull,
    )

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        MagicMock(),
    )

    scheduler.run_pricesfull()

    download_pricefull.assert_awaited_once_with(test=False)


def test_run_pricesfull_downloads_and_marks(monkeypatch):
    downloaded = [
        "PriceFull7290058108879-001-003.gz",
        "PriceFull7290058140886-001-711.gz",
    ]

    monkeypatch.setattr(
        scheduler,
        "download_pricefull",
        AsyncMock(return_value=downloaded),
    )

    mark_downloaded = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark_downloaded,
    )

    scheduler.run_pricesfull()

    mark_downloaded.assert_called_once_with(downloaded)


def test_run_pricesfull_download_failure_stops(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "download_pricefull",
        AsyncMock(side_effect=RuntimeError("download failed")),
    )

    mark_downloaded = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark_downloaded,
    )

    scheduler.run_pricesfull()

    mark_downloaded.assert_not_called()


# ---- run_promos_and_load() ----

def test_run_promos_passes_test_flag(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    download_promofull = AsyncMock(return_value=[])
    download_promos = AsyncMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        download_promofull,
    )
    monkeypatch.setattr(
        scheduler,
        "download_promos",
        download_promos,
    )

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        MagicMock(),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        MagicMock(),
    )

    scheduler.run_promos_and_load()

    download_promofull.assert_awaited_once_with(test=True)
    download_promos.assert_awaited_once_with(test=True)


def test_run_promos_passes_test_false(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    download_promofull = AsyncMock(return_value=[])
    download_promos = AsyncMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        download_promofull,
    )
    monkeypatch.setattr(
        scheduler,
        "download_promos",
        download_promos,
    )

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        MagicMock(),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        MagicMock(),
    )

    scheduler.run_promos_and_load()

    download_promofull.assert_awaited_once_with(test=False)
    download_promos.assert_awaited_once_with(test=False)


def test_run_promos_downloads_and_marks_promofull(monkeypatch):
    promofull_files = [
        "PromoFull7290058108879-001-003.gz",
        "PromoFull7290058140886-001-711.gz",
    ]

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        AsyncMock(return_value=promofull_files),
    )

    monkeypatch.setattr(
        scheduler,
        "download_promos",
        AsyncMock(return_value=[]),
    )

    mark_downloaded = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark_downloaded,
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        MagicMock(),
    )

    scheduler.run_promos_and_load()

    assert mark_downloaded.call_args_list[0].args[0] == promofull_files


def test_run_promos_downloads_and_marks_promo(monkeypatch):
    promofull_files = [
        "PromoFull7290058108879-001-003.gz",
    ]

    promo_files = [
        "Promo7290058108879-001-003.gz",
        "Promo7290058140886-001-711.gz",
    ]

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        AsyncMock(return_value=promofull_files),
    )

    monkeypatch.setattr(
        scheduler,
        "download_promos",
        AsyncMock(return_value=promo_files),
    )

    mark_downloaded = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark_downloaded,
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        MagicMock(),
    )

    scheduler.run_promos_and_load()

    assert mark_downloaded.call_count == 2

    assert mark_downloaded.call_args_list[0].args[0] == promofull_files
    assert mark_downloaded.call_args_list[1].args[0] == promo_files


def test_run_promos_loads_pending_promofull(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        scheduler,
        "download_promos",
        AsyncMock(return_value=[]),
    )

    rows = [
        (
            "7290058108879",
            "001",
            "003",
            "PromoFull",
            "PromoFull7290058108879-001-003.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=rows),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        MagicMock(return_value=[]),
    )

    load_promo_files = MagicMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        load_promo_files,
    )

    scheduler.run_promos_and_load()

    files = load_promo_files.call_args.args[1]

    assert files == [
        (
            tmp_path
            / "7290058108879"
            / "003"
            / "promosfull"
            / "PromoFull7290058108879-001-003.gz",
            "PromoFull",
        )
    ]


def test_run_promos_builds_promo_path(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        scheduler,
        "download_promos",
        AsyncMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=[]),
    )

    rows = [
        (
            "7290058108879",
            "001",
            "003",
            "Promo",
            "Promo7290058108879-001-003.gz",
            "2026-09-16",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        MagicMock(return_value=rows),
    )

    load_promo_files = MagicMock(return_value=[])
    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        load_promo_files,
    )

    scheduler.run_promos_and_load()

    files = load_promo_files.call_args.args[1]

    assert files == [
        (
            tmp_path
            / "7290058108879"
            / "003"
            / "promos"
            / "Promo7290058108879-001-003.gz",
            "Promo",
        )
    ]


def test_run_promos_does_not_load_promo_without_loaded_promofull(
    monkeypatch,
):
    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        scheduler,
        "download_promos",
        AsyncMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        MagicMock(return_value=[]),
    )

    load_mock = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        load_mock,
    )

    scheduler.run_promos_and_load()

    load_mock.assert_not_called()


def test_run_prices_does_not_load_price_without_loaded_pricefull(
    monkeypatch,
):
    mock_conn(monkeypatch)

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_pricefull_files",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_price_files",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        scheduler,
        "_load_chain_metadata",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(
        scheduler,
        "_load_ignored_price_stores",
        MagicMock(return_value=set()),
    )

    load_mock = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load_mock,
    )

    scheduler.run_prices_and_load()

    load_mock.assert_not_called()