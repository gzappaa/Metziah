# tests/downloaders/test_scheduler.py
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from downloaders import scheduler


def _make_gz(base: Path, chain, store, branch, fname, mtime=None):
    """Create a fake .gz file at base/chain/store/branch/prices/fname."""
    path = base / chain / store / branch / "prices" / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return path


def test_new_files_are_picked_up_old_ones_are_not(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    start_time = time.time()

    old_file = _make_gz(
        tmp_path, "7290661400001", "001", "058", "old.gz",
        mtime=start_time - 100,
    )
    time.sleep(0.01)  # ensure new file's mtime is strictly after start_time
    new_file = _make_gz(
        tmp_path, "7290661400001", "001", "058", "new.gz",
        mtime=start_time + 10,
    )

    mock_load_files = MagicMock()
    mock_conn = MagicMock()
    mock_get_connection = MagicMock()
    mock_get_connection.return_value.__enter__.return_value = mock_conn

    with patch.object(scheduler, "run", return_value=True), \
         patch.object(scheduler, "get_connection", mock_get_connection), \
         patch.object(scheduler, "load_files", mock_load_files), \
         patch("time.time", return_value=start_time):
        scheduler.run_prices_and_load()

    assert mock_load_files.called
    loaded_files = mock_load_files.call_args[0][1]  # first positional arg
    assert new_file in loaded_files
    assert old_file not in loaded_files


def test_run_fails_load_files_not_called():
    mock_load_files = MagicMock()

    with patch.object(scheduler, "run", return_value=False), \
         patch.object(scheduler, "load_files", mock_load_files):
        scheduler.run_prices_and_load()

    mock_load_files.assert_not_called()


def test_no_new_files_load_files_not_called(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    start_time = time.time()

    # only an old file exists, nothing newer than start_time
    _make_gz(
        tmp_path, "7290661400001", "001", "058", "old.gz",
        mtime=start_time - 100,
    )

    mock_load_files = MagicMock()

    with patch.object(scheduler, "run", return_value=True), \
         patch.object(scheduler, "load_files", mock_load_files), \
         patch("time.time", return_value=start_time):
        scheduler.run_prices_and_load()

    mock_load_files.assert_not_called()