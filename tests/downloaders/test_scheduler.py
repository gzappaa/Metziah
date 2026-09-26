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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    assert scheduler.normalize_store_id(value) == expected


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

    monkeypatch.setattr(scheduler, "CHAINS_FILE", chains_file)
    monkeypatch.setattr(
        scheduler,
        "CHAINS_EXTRA_FILE",
        chains_extra_file,
    )

    metadata = scheduler._load_chain_metadata()

    assert metadata["123"]["client"] == "LaibcatalogClient"


@pytest.mark.parametrize(
    ("chain_id", "metadata", "expected"),
    [
        (
            "123",
            {"123": {"client": "LaibcatalogClient"}},
            True,
        ),
        (
            "123",
            {"123": {"client": "OtherClient"}},
            False,
        ),
        (
            "999",
            {"123": {"client": "LaibcatalogClient"}},
            False,
        ),
    ],
)
def test_is_laibcatalog_chain(chain_id, metadata, expected):
    assert (
        scheduler._is_laibcatalog_chain(chain_id, metadata)
        is expected
    )


def test_load_ignored_price_stores(tmp_path, monkeypatch):
    ignored_file = tmp_path / "ignored_stores.json"

    ignored_file.write_text(
        """
        [
            {
                "chain": "123",
                "stores": ["006", "07"]
            }
        ]
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(
        scheduler,
        "IGNORED_STORES_FILE",
        ignored_file,
    )

    assert scheduler._load_ignored_price_stores() == {
        ("123", "6"),
        ("123", "7"),
    }


def test_load_ignored_price_stores_missing_file(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "IGNORED_STORES_FILE",
        tmp_path / "missing.json",
    )

    assert scheduler._load_ignored_price_stores() == set()


# ---------------------------------------------------------------------------
# main() / safety
# ---------------------------------------------------------------------------

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


def test_main_unknown_command_does_not_run_pipeline(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py", "unknown"],
    )

    run_all = MagicMock()
    run_prices = MagicMock()
    run_pricesfull = MagicMock()
    run_promos = MagicMock()

    monkeypatch.setattr(scheduler, "run_all", run_all)
    monkeypatch.setattr(
        scheduler,
        "run_prices_and_load",
        run_prices,
    )
    monkeypatch.setattr(
        scheduler,
        "run_pricesfull",
        run_pricesfull,
    )
    monkeypatch.setattr(
        scheduler,
        "run_promos_and_load",
        run_promos,
    )

    scheduler.main()

    run_all.assert_not_called()
    run_prices.assert_not_called()
    run_pricesfull.assert_not_called()
    run_promos.assert_not_called()


# ---------------------------------------------------------------------------
# run_all()
# ---------------------------------------------------------------------------

def test_run_all_order(monkeypatch):
    calls = []

    monkeypatch.setattr(
        scheduler,
        "run_pricesfull",
        lambda: calls.append("pricesfull"),
    )

    monkeypatch.setattr(
        scheduler,
        "run_prices_and_load",
        lambda: calls.append("prices"),
    )

    monkeypatch.setattr(
        scheduler,
        "run_promos_and_load",
        lambda: calls.append("promos"),
    )

    async def refresh():
        calls.append("refresh")

    monkeypatch.setattr(
        scheduler,
        "refresh_html_caches",
        refresh,
    )

    scheduler.run_all()

    assert calls == [
        "pricesfull",
        "refresh",
        "prices",
        "refresh",
        "promos",
    ]


# ---------------------------------------------------------------------------
# run_file_tracking()
# ---------------------------------------------------------------------------

def test_run_file_tracking_success(monkeypatch):
    update = AsyncMock(return_value=5)

    monkeypatch.setattr(
        scheduler,
        "update_file_tracking",
        update,
    )

    assert scheduler.run_file_tracking() is True
    update.assert_awaited_once()


def test_run_file_tracking_failure(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "update_file_tracking",
        AsyncMock(side_effect=RuntimeError("failed")),
    )

    assert scheduler.run_file_tracking() is False


# ---------------------------------------------------------------------------
# mark_downloaded()
# ---------------------------------------------------------------------------

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

    mark_files_downloaded = MagicMock(return_value=2)

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


# ---------------------------------------------------------------------------
# cleanup_old_price_files()
# ---------------------------------------------------------------------------

def test_cleanup_old_price_files_removes_old_snapshots(tmp_path):
    prices_dir = (
        tmp_path
        / "7290661400001"
        / "002"
        / "prices"
    )
    prices_dir.mkdir(parents=True)

    loaded = prices_dir / "Price7290661400001-001-002.gz"
    old = prices_dir / "Price7290661400001-001-001.gz"

    loaded.touch()
    old.touch()

    scheduler.cleanup_old_price_files(
        [(loaded, True)]
    )

    assert loaded.exists()
    assert not old.exists()


def test_cleanup_old_price_files_keeps_delta_prices(tmp_path):
    prices_dir = (
        tmp_path
        / "7290661400001"
        / "002"
        / "prices"
    )
    prices_dir.mkdir(parents=True)

    loaded = prices_dir / "Price7290661400001-001-002.gz"
    old = prices_dir / "Price7290661400001-001-001.gz"

    loaded.touch()
    old.touch()

    scheduler.cleanup_old_price_files(
        [(loaded, False)]
    )

    assert loaded.exists()
    assert old.exists()


def test_cleanup_old_price_files_keeps_files_outside_prices(tmp_path):
    pricesfull_dir = (
        tmp_path
        / "7290661400001"
        / "002"
        / "pricesfull"
    )
    pricesfull_dir.mkdir(parents=True)

    loaded = (
        pricesfull_dir
        / "PriceFull7290661400001-001-002.gz"
    )
    other = (
        pricesfull_dir
        / "PriceFull7290661400001-001-001.gz"
    )

    loaded.touch()
    other.touch()

    scheduler.cleanup_old_price_files(
        [(loaded, True)]
    )

    assert loaded.exists()
    assert other.exists()


# ---------------------------------------------------------------------------
# run_pricesfull()
# ---------------------------------------------------------------------------

def test_run_pricesfull_passes_test_flag(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    download = AsyncMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "download_pricefull",
        download,
    )

    mark = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark,
    )

    scheduler.run_pricesfull()

    download.assert_awaited_once_with(test=True)
    mark.assert_called_once_with([])


def test_run_pricesfull_passes_test_false(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    download = AsyncMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "download_pricefull",
        download,
    )

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        MagicMock(),
    )

    scheduler.run_pricesfull()

    download.assert_awaited_once_with(test=False)


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

    mark = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark,
    )

    scheduler.run_pricesfull()

    mark.assert_called_once_with(downloaded)


def test_run_pricesfull_download_failure_stops(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "download_pricefull",
        AsyncMock(
            side_effect=RuntimeError("download failed")
        ),
    )

    mark = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark,
    )

    scheduler.run_pricesfull()

    mark.assert_not_called()


# ---------------------------------------------------------------------------
# run_prices_and_load()
# ---------------------------------------------------------------------------

def test_run_prices_passes_test_flag(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    download = AsyncMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        download,
    )

    scheduler.run_prices_and_load()

    download.assert_awaited_once_with(test=True)


def test_run_prices_passes_test_false(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    download = AsyncMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        download,
    )

    scheduler.run_prices_and_load()

    download.assert_awaited_once_with(test=False)


def test_run_prices_download_failure_stops(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(
            side_effect=Exception("download failed")
        ),
    )

    load = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load,
    )

    scheduler.run_prices_and_load()

    load.assert_not_called()


def test_run_prices_loads_pricefull_first(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

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
                / "6"
                / "pricesfull"
                / "PriceFull7290058108879-001-006.gz",
                "PriceFull",
                True,
            )
        ]
    ]


def test_run_prices_builds_delta_price_path(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

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
        "_load_chain_metadata",
        MagicMock(return_value={}),
    )

    monkeypatch.setattr(
        scheduler,
        "_load_ignored_price_stores",
        MagicMock(return_value=set()),
    )

    rows = [
        (
            "7290644700005",
            "001",
            "20",
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

    load = MagicMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load,
    )

    scheduler.run_prices_and_load()

    assert load.call_args.args[1] == [
        (
            tmp_path
            / "7290644700005"
            / "20"
            / "prices"
            / "Price7290644700005-001-020.gz",
            "Price",
            False,
        )
    ]


def test_run_prices_laibcatalog_price_is_snapshot(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

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
        "_load_chain_metadata",
        MagicMock(
            return_value={
                "7290661400001": {
                    "client": "LaibcatalogClient",
                }
            }
        ),
    )

    monkeypatch.setattr(
        scheduler,
        "_load_ignored_price_stores",
        MagicMock(return_value=set()),
    )

    rows = [
        (
            "7290661400001",
            "001",
            "2",
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

    load = MagicMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load,
    )

    scheduler.run_prices_and_load()

    assert load.call_args.args[1] == [
        (
            tmp_path
            / "7290661400001"
            / "2"
            / "prices"
            / "Price7290661400001-001-002.gz",
            "Price",
            True,
        )
    ]


def test_run_prices_ignores_ignored_store(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

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
        "_load_chain_metadata",
        MagicMock(return_value={}),
    )

    monkeypatch.setattr(
        scheduler,
        "_load_ignored_price_stores",
        MagicMock(
            return_value={
                ("7290058108879", "6"),
            }
        ),
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

    load = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load,
    )

    scheduler.run_prices_and_load()

    load.assert_not_called()


def test_run_prices_no_eligible_files_stops(
    monkeypatch,
):
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

    load = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        load,
    )

    scheduler.run_prices_and_load()

    load.assert_not_called()


def test_run_prices_discovers_products_after_pricefull_load(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    conn = mock_conn(monkeypatch)

    pricefull_rows = [
        (
            "123",
            "001",
            "2",
            "PriceFull",
            "PriceFull123-001-002.gz",
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

    loaded = [
        tmp_path
        / "123"
        / "2"
        / "pricesfull"
        / "PriceFull123-001-002.gz"
    ]

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        MagicMock(return_value=loaded),
    )

    discover = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "discover_new_products",
        discover,
    )

    scheduler.run_prices_and_load()

    discover.assert_called_once_with(
        conn,
        loaded,
        tmp_path,
    )

# ---------------------------------------------------------------------------
# run_promos_and_load()
# ---------------------------------------------------------------------------

def _mock_promo_dependencies(monkeypatch):
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


def test_run_promos_passes_test_flag(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "test",
    )

    _mock_promo_dependencies(monkeypatch)

    scheduler.run_promos_and_load()

    scheduler.download_promofull.assert_awaited_once_with(
        test=True
    )
    scheduler.download_promos.assert_awaited_once_with(
        test=True
    )


def test_run_promos_passes_test_false(monkeypatch):
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    _mock_promo_dependencies(monkeypatch)

    scheduler.run_promos_and_load()

    scheduler.download_promofull.assert_awaited_once_with(
        test=False
    )
    scheduler.download_promos.assert_awaited_once_with(
        test=False
    )


def test_run_promos_download_promofull_failure_stops(
    monkeypatch,
):
    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        AsyncMock(
            side_effect=RuntimeError("failed")
        ),
    )

    download_promos = AsyncMock(
        return_value=[]
    )

    monkeypatch.setattr(
        scheduler,
        "download_promos",
        download_promos,
    )

    scheduler.run_promos_and_load()

    download_promos.assert_not_awaited()


def test_run_promos_downloads_and_marks_promofull(
    monkeypatch,
):
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

    mark = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark,
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

    assert mark.call_args_list[0].args[0] == promofull_files


def test_run_promos_downloads_and_marks_promo(
    monkeypatch,
):
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

    mark = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "mark_downloaded",
        mark,
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

    assert mark.call_count == 2
    assert mark.call_args_list[0].args[0] == promofull_files
    assert mark.call_args_list[1].args[0] == promo_files


def test_run_promos_loads_pending_promofull(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

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
            "3",
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

    load = MagicMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        load,
    )

    scheduler.run_promos_and_load()

    assert load.call_args.args[1] == [
        (
            tmp_path
            / "7290058108879"
            / "3"
            / "promosfull"
            / "PromoFull7290058108879-001-003.gz",
            "PromoFull",
        )
    ]


def test_run_promos_builds_promo_path(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

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
            "3",
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

    load = MagicMock(return_value=[])

    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        load,
    )

    scheduler.run_promos_and_load()

    assert load.call_args.args[1] == [
        (
            tmp_path
            / "7290058108879"
            / "3"
            / "promos"
            / "Promo7290058108879-001-003.gz",
            "Promo",
        )
    ]


def test_run_promos_without_eligible_promo_stops(
    monkeypatch,
):
    _mock_promo_dependencies(monkeypatch)

    mock_conn(monkeypatch)

    scheduler.run_promos_and_load()

    scheduler.load_promo_files.assert_not_called()


# ---------------------------------------------------------------------------
# Command routing
# ---------------------------------------------------------------------------

def test_main_prices_command(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py", "prices"],
    )

    tracking = MagicMock()
    pricesfull = MagicMock()
    prices = MagicMock()
    file_sizes = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "run_file_tracking",
        tracking,
    )
    monkeypatch.setattr(
        scheduler,
        "run_pricesfull",
        pricesfull,
    )
    monkeypatch.setattr(
        scheduler,
        "run_prices_and_load",
        prices,
    )
    monkeypatch.setattr(
        scheduler,
        "populate_file_sizes",
        file_sizes,
    )

    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    scheduler.main()

    tracking.assert_called_once()
    pricesfull.assert_called_once()
    prices.assert_called_once()
    file_sizes.assert_called_once()


def test_main_pricesfull_command(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py", "pricesfull"],
    )

    tracking = MagicMock()
    pricesfull = MagicMock()
    file_sizes = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "run_file_tracking",
        tracking,
    )
    monkeypatch.setattr(
        scheduler,
        "run_pricesfull",
        pricesfull,
    )
    monkeypatch.setattr(
        scheduler,
        "populate_file_sizes",
        file_sizes,
    )
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    scheduler.main()

    tracking.assert_called_once()
    pricesfull.assert_called_once()
    file_sizes.assert_called_once()


def test_main_promos_command(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py", "promos"],
    )

    tracking = MagicMock()
    promos = MagicMock()
    file_sizes = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "run_file_tracking",
        tracking,
    )
    monkeypatch.setattr(
        scheduler,
        "run_promos_and_load",
        promos,
    )
    monkeypatch.setattr(
        scheduler,
        "populate_file_sizes",
        file_sizes,
    )
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    scheduler.main()

    tracking.assert_called_once()
    promos.assert_called_once()
    file_sizes.assert_called_once()


def test_main_all_command(monkeypatch):
    monkeypatch.setattr(
        scheduler.sys,
        "argv",
        ["scheduler.py", "all"],
    )

    tracking = MagicMock()
    run_all = MagicMock()
    file_sizes = MagicMock()

    monkeypatch.setattr(
        scheduler,
        "run_file_tracking",
        tracking,
    )
    monkeypatch.setattr(
        scheduler,
        "run_all",
        run_all,
    )
    monkeypatch.setattr(
        scheduler,
        "populate_file_sizes",
        file_sizes,
    )
    monkeypatch.setattr(
        scheduler.settings,
        "ENV",
        "dev",
    )

    scheduler.main()

    tracking.assert_called_once()
    run_all.assert_called_once()
    file_sizes.assert_called_once()