from pathlib import Path

import pytest

from utils import load_prices
from utils.load_prices import find_price_files


def test_find_price_files():
    feeds_dir = Path("data/test_feeds")

    files = list(find_price_files(feeds_dir))

    assert files
    assert all(file.suffix == ".gz" for file in files)
    assert all(
        file.parent.name in {"prices", "pricesfull"}
        for file in files
    )


def test_main_test_flag_requires_test_environment(monkeypatch):
    monkeypatch.setattr(load_prices.settings, "ENV", "dev")
    monkeypatch.setattr("sys.argv", ["load_prices.py", "--test"])

    with pytest.raises(
        RuntimeError,
        match="Development database selected",
    ):
        load_prices.main()


def test_main_test_flag_rejects_non_test_environment(monkeypatch):
    monkeypatch.setattr(load_prices.settings, "ENV", "prod")
    monkeypatch.setattr("sys.argv", ["load_prices.py", "--test"])

    with pytest.raises(
        RuntimeError,
        match="--test was provided",
    ):
        load_prices.main()


def test_main_dev_flag_requires_dev_environment(monkeypatch):
    monkeypatch.setattr(load_prices.settings, "ENV", "test")
    monkeypatch.setattr("sys.argv", ["load_prices.py", "--dev"])

    with pytest.raises(
        RuntimeError,
        match="--dev was provided",
    ):
        load_prices.main()


def test_main_returns_when_no_price_files(monkeypatch):
    monkeypatch.setattr(load_prices.settings, "ENV", "test")
    monkeypatch.setattr("sys.argv", ["load_prices.py", "--test"])

    monkeypatch.setattr(
        load_prices,
        "find_price_files",
        lambda _: [],
    )

    load_prices.main()


def test_main_loads_all_found_files(monkeypatch):
    monkeypatch.setattr(load_prices.settings, "ENV", "test")
    monkeypatch.setattr("sys.argv", ["load_prices.py", "--test"])

    files = [
        Path("file1.gz"),
        Path("file2.gz"),
    ]

    monkeypatch.setattr(
        load_prices,
        "find_price_files",
        lambda _: files,
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    conn = FakeConnection()

    monkeypatch.setattr(
        load_prices,
        "get_connection",
        lambda: conn,
    )

    calls = []

    def fake_load_files(
        conn,
        filepaths,
        feeds_dir,
        log_changes,
    ):
        calls.append(
            (
                conn,
                filepaths,
                feeds_dir,
                log_changes,
            )
        )

    monkeypatch.setattr(
        load_prices,
        "load_files",
        fake_load_files,
    )

    load_prices.main()

    assert len(calls) == 1
    assert calls[0][0] is conn
    assert calls[0][1] == files
    assert calls[0][2] == Path("data/test_feeds")
    assert calls[0][3] is False