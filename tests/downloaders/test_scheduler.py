# tests/test_scheduler.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from downloaders import scheduler


def mock_conn(monkeypatch):
    conn = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(scheduler, "get_connection", MagicMock(return_value=ctx))
    return conn


# ---- mark_downloaded ----

def test_mark_downloaded_empty_list_skips_db(monkeypatch):
    get_conn = MagicMock()
    monkeypatch.setattr(scheduler, "get_connection", get_conn)

    scheduler.mark_downloaded([])

    get_conn.assert_not_called()


def test_mark_downloaded_calls_with_filenames_and_commits(monkeypatch):
    conn = mock_conn(monkeypatch)
    mark_files = MagicMock(return_value=2)
    monkeypatch.setattr(scheduler, "mark_files_downloaded", mark_files)

    scheduler.mark_downloaded([Path("/x/a.gz"), Path("/x/b.gz")])

    mark_files.assert_called_once_with(conn, ["a.gz", "b.gz"])
    conn.commit.assert_called_once()


# ---- cleanup_old_price_files ----

def test_cleanup_deletes_other_price_files_same_folder(tmp_path):
    folder = tmp_path / "prices"
    folder.mkdir()
    keep = folder / "Price...-090000.gz"
    keep.write_bytes(b"new")
    old = folder / "Price...-040000.gz"
    old.write_bytes(b"old")

    scheduler.cleanup_old_price_files([keep])

    assert keep.exists()
    assert not old.exists()


def test_cleanup_skips_non_prices_folder(tmp_path):
    folder = tmp_path / "pricesfull"
    folder.mkdir()
    keep = folder / "PriceFull...-090000.gz"
    keep.write_bytes(b"new")
    sibling = folder / "PriceFull...-040000.gz"
    sibling.write_bytes(b"old")

    scheduler.cleanup_old_price_files([keep])

    assert sibling.exists()


def test_cleanup_continues_after_unlink_failure(tmp_path, monkeypatch):
    folder = tmp_path / "prices"
    folder.mkdir()
    keep = folder / "Price...-090000.gz"
    keep.write_bytes(b"new")
    bad = folder / "Price...-030000.gz"
    bad.write_bytes(b"bad")
    good = folder / "Price...-040000.gz"
    good.write_bytes(b"good")

    real_unlink = Path.unlink

    def flaky_unlink(self, *a, **kw):
        if self.name == bad.name:
            raise OSError("boom")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    scheduler.cleanup_old_price_files([keep])  # should not raise

    assert bad.exists()
    assert not good.exists()


# ---- run_file_tracking ----

def test_run_file_tracking_success(monkeypatch):
    monkeypatch.setattr(scheduler, "update_file_tracking", AsyncMock(return_value=3))
    assert scheduler.run_file_tracking() is True


def test_run_file_tracking_exception_returns_false(monkeypatch):
    monkeypatch.setattr(
        scheduler, "update_file_tracking", AsyncMock(side_effect=Exception("boom"))
    )
    assert scheduler.run_file_tracking() is False


# ---- run_prices_and_load ----

def test_run_prices_download_failure_returns_early(monkeypatch):
    monkeypatch.setattr(scheduler, "download_prices", AsyncMock(side_effect=Exception("x")))
    get_conn = MagicMock()
    monkeypatch.setattr(scheduler, "get_connection", get_conn)

    scheduler.run_prices_and_load()

    get_conn.assert_not_called()


def test_run_prices_no_latest_files_returns_early(monkeypatch):
    monkeypatch.setattr(scheduler, "download_prices", AsyncMock(return_value=[]))
    conn = mock_conn(monkeypatch)
    monkeypatch.setattr(scheduler, "get_latest_downloaded_price_files", MagicMock(return_value=[]))
    load_price_files = MagicMock()
    monkeypatch.setattr(scheduler, "load_price_files", load_price_files)

    scheduler.run_prices_and_load()

    load_price_files.assert_not_called()


def test_run_prices_builds_correct_paths_and_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)
    monkeypatch.setattr(scheduler, "download_prices", AsyncMock(return_value=[]))
    conn = mock_conn(monkeypatch)

    rows = [
        ("7290661400001", "001", "020", "Price", "Price...-020.gz"),
        ("7290661400001", "001", "021", "PriceFull", "PriceFull...-021.gz"),
    ]
    monkeypatch.setattr(scheduler, "get_latest_downloaded_price_files", MagicMock(return_value=rows))

    loaded = [tmp_path / "loaded.gz"]
    load_price_files = MagicMock(return_value=loaded)
    monkeypatch.setattr(scheduler, "load_price_files", load_price_files)

    cleanup = MagicMock()
    monkeypatch.setattr(scheduler, "cleanup_old_price_files", cleanup)

    scheduler.run_prices_and_load()

    called_paths = load_price_files.call_args[0][1]
    assert called_paths[0] == tmp_path / "7290661400001" / "001" / "020" / "prices" / "Price...-020.gz"
    assert called_paths[1] == tmp_path / "7290661400001" / "001" / "021" / "pricesfull" / "PriceFull...-021.gz"
    cleanup.assert_called_once_with(loaded)


# ---- run_pricesfull ----

def test_run_pricesfull_download_failure_skips_mark(monkeypatch):
    monkeypatch.setattr(scheduler, "download_pricefull", AsyncMock(side_effect=Exception("x")))
    mark = MagicMock()
    monkeypatch.setattr(scheduler, "mark_downloaded", mark)

    scheduler.run_pricesfull()

    mark.assert_not_called()


def test_run_pricesfull_success_marks_downloaded(monkeypatch):
    files = [Path("/x/PriceFull.gz")]
    monkeypatch.setattr(scheduler, "download_pricefull", AsyncMock(return_value=files))
    mark = MagicMock()
    monkeypatch.setattr(scheduler, "mark_downloaded", mark)

    scheduler.run_pricesfull()

    mark.assert_called_once_with(files)


# ---- run_promos_and_load ----

def test_promofull_download_failure_returns_early(monkeypatch):
    monkeypatch.setattr(scheduler, "download_promofull", AsyncMock(side_effect=Exception("x")))
    download_promos = AsyncMock()
    monkeypatch.setattr(scheduler, "download_promos", download_promos)

    scheduler.run_promos_and_load()

    download_promos.assert_not_called()


def test_promo_download_failure_returns_early(monkeypatch):
    monkeypatch.setattr(scheduler, "download_promofull", AsyncMock(return_value=[]))
    monkeypatch.setattr(scheduler, "download_promos", AsyncMock(side_effect=Exception("x")))
    get_conn = MagicMock()
    monkeypatch.setattr(scheduler, "get_connection", get_conn)

    scheduler.run_promos_and_load()

    get_conn.assert_not_called()


def test_no_pending_promofull_still_checks_promo(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)
    monkeypatch.setattr(scheduler, "download_promofull", AsyncMock(return_value=[]))
    monkeypatch.setattr(scheduler, "download_promos", AsyncMock(return_value=[]))
    mock_conn(monkeypatch)

    monkeypatch.setattr(scheduler, "get_downloaded_promofull_files", MagicMock(return_value=[]))
    load_promo_files = MagicMock(return_value=[])
    monkeypatch.setattr(scheduler, "load_promo_files", load_promo_files)
    monkeypatch.setattr(scheduler, "get_downloaded_unloaded_promo_files", MagicMock(return_value=[]))

    scheduler.run_promos_and_load()

    load_promo_files.assert_not_called()


def test_promo_and_promofull_paths_built_correctly(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)
    monkeypatch.setattr(scheduler, "download_promofull", AsyncMock(return_value=[]))
    monkeypatch.setattr(scheduler, "download_promos", AsyncMock(return_value=[]))
    mock_conn(monkeypatch)

    promofull_rows = [("7290661400001", "001", "020", "PromoFull", "PromoFull...-020.gz")]
    promo_rows = [("7290661400001", "001", "020", "Promo", "Promo...-020.gz")]

    monkeypatch.setattr(scheduler, "get_downloaded_promofull_files", MagicMock(return_value=promofull_rows))
    monkeypatch.setattr(scheduler, "get_downloaded_unloaded_promo_files", MagicMock(return_value=promo_rows))

    load_promo_files = MagicMock(return_value=[])
    monkeypatch.setattr(scheduler, "load_promo_files", load_promo_files)

    scheduler.run_promos_and_load()

    first_call_paths = load_promo_files.call_args_list[0][0][1]
    assert first_call_paths[0][0] == (
        tmp_path / "7290661400001" / "001" / "020" / "promosfull" / "PromoFull...-020.gz"
    )

    second_call_paths = load_promo_files.call_args_list[1][0][1]
    assert second_call_paths[0][0] == (
        tmp_path / "7290661400001" / "001" / "020" / "promos" / "Promo...-020.gz"
    )


# ---- run_all ----

def test_run_all_test_env_skips_pricesfull(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "ENV", "test")
    pricesfull = MagicMock()
    promos = MagicMock()
    prices_ = MagicMock()
    monkeypatch.setattr(scheduler, "run_pricesfull", pricesfull)
    monkeypatch.setattr(scheduler, "run_promos_and_load", promos)
    monkeypatch.setattr(scheduler, "run_prices_and_load", prices_)

    scheduler.run_all()

    pricesfull.assert_not_called()
    promos.assert_called_once()
    prices_.assert_called_once()


def test_run_all_non_test_env_runs_all_three(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "ENV", "dev")
    pricesfull = MagicMock()
    promos = MagicMock()
    prices_ = MagicMock()
    monkeypatch.setattr(scheduler, "run_pricesfull", pricesfull)
    monkeypatch.setattr(scheduler, "run_promos_and_load", promos)
    monkeypatch.setattr(scheduler, "run_prices_and_load", prices_)

    scheduler.run_all()

    pricesfull.assert_called_once()
    promos.assert_called_once()
    prices_.assert_called_once()


# ---- main() dispatch ----

def test_main_prices_command_runs_when_tracking_succeeds(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "prices"])
    monkeypatch.setattr(scheduler, "run_file_tracking", MagicMock(return_value=True))
    run_prices = MagicMock()
    monkeypatch.setattr(scheduler, "run_prices_and_load", run_prices)

    scheduler.main()

    run_prices.assert_called_once()


def test_main_skips_command_when_tracking_fails(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "prices"])
    monkeypatch.setattr(scheduler, "run_file_tracking", MagicMock(return_value=False))
    run_prices = MagicMock()
    monkeypatch.setattr(scheduler, "run_prices_and_load", run_prices)

    scheduler.main()

    run_prices.assert_not_called()


def test_main_unknown_command_does_nothing(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "bogus"])
    monkeypatch.setattr(scheduler, "run_file_tracking", MagicMock(return_value=True))
    run_all = MagicMock()
    monkeypatch.setattr(scheduler, "run_all", run_all)

    scheduler.main()

    run_all.assert_not_called()


def test_main_no_args_runs_default(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    monkeypatch.setattr(scheduler, "run_file_tracking", MagicMock(return_value=True))
    run_all = MagicMock()
    monkeypatch.setattr(scheduler, "run_all", run_all)

    scheduler.main()

    run_all.assert_called_once()

def test_run_prices_load_failure_does_not_cleanup(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)
    monkeypatch.setattr(
        scheduler,
        "download_prices",
        AsyncMock(return_value=[]),
    )

    mock_conn(monkeypatch)

    rows = [
        (
            "7290661400001",
            "001",
            "020",
            "Price",
            "Price...-020.gz",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_latest_downloaded_price_files",
        MagicMock(return_value=rows),
    )

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        MagicMock(side_effect=Exception("load failed")),
    )

    cleanup = MagicMock()
    monkeypatch.setattr(
        scheduler,
        "cleanup_old_price_files",
        cleanup,
    )

    with pytest.raises(Exception, match="load failed"):
        scheduler.run_prices_and_load()

    cleanup.assert_not_called()


def test_promofull_load_failure_does_not_process_promos(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

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

    mock_conn(monkeypatch)

    promofull_rows = [
        (
            "7290661400001",
            "001",
            "020",
            "PromoFull",
            "PromoFull...-020.gz",
        ),
    ]

    monkeypatch.setattr(
        scheduler,
        "get_downloaded_promofull_files",
        MagicMock(return_value=promofull_rows),
    )

    promo_query = MagicMock(
        return_value=[
            (
                "7290661400001",
                "001",
                "020",
                "Promo",
                "Promo...-020.gz",
            ),
        ]
    )
    monkeypatch.setattr(
        scheduler,
        "get_downloaded_unloaded_promo_files",
        promo_query,
    )

    load_promo_files = MagicMock(
        side_effect=Exception("PromoFull load failed")
    )
    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        load_promo_files,
    )

    with pytest.raises(Exception, match="PromoFull load failed"):
        scheduler.run_promos_and_load()

    # Promo eligibility must never be checked because the
    # PromoFull baseline failed to load.
    promo_query.assert_not_called()

    # Only the PromoFull load was attempted.
    load_promo_files.assert_called_once()