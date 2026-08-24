from pathlib import Path

import pytest

from utils import load_promos
from utils.load_promos import find_promo_files


def test_find_promo_files():
    feeds_dir = Path("data/test_feeds")

    files = list(find_promo_files(feeds_dir))

    assert files
    assert all(
        filepath.suffix == ".gz"
        for filepath, file_type in files
    )
    assert all(
        filepath.parent.name == "promosfull"
        for filepath, file_type in files
    )
    assert all(
        file_type == "PromoFull"
        for filepath, file_type in files
    )

def test_find_promo_files_keeps_only_latest_per_store(tmp_path):
    promosfull_dir = (
        tmp_path
        / "7290661400001"
        / "002"
        / "055"
        / "promosfull"
    )
    promosfull_dir.mkdir(parents=True)

    old_file = promosfull_dir / (
        "PromoFull7290661400001-002-055-20260815-043144.gz"
    )
    new_file = promosfull_dir / (
        "PromoFull7290661400001-002-055-20260816-043144.gz"
    )

    old_file.touch()
    new_file.touch()

    files = list(find_promo_files(tmp_path))

    assert files == [
        (new_file, "PromoFull"),
    ]


def test_main_test_flag_requires_test_environment(monkeypatch):
    monkeypatch.setattr(
        load_promos.settings,
        "ENV",
        "dev",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["load_promos.py", "--test"],
    )

    with pytest.raises(
        RuntimeError,
        match="Development database selected",
    ):
        load_promos.main()


def test_main_test_flag_rejects_non_test_environment(monkeypatch):
    monkeypatch.setattr(
        load_promos.settings,
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
        load_promos.main()


def test_main_dev_flag_requires_dev_environment(monkeypatch):
    monkeypatch.setattr(
        load_promos.settings,
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
        load_promos.main()


def test_main_returns_when_no_promo_files(monkeypatch):
    monkeypatch.setattr(
        load_promos.settings,
        "ENV",
        "test",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["load_promos.py", "--test"],
    )

    monkeypatch.setattr(
        load_promos,
        "find_promo_files",
        lambda _: [],
    )

    load_promos.main()


def test_main_loads_all_promo_files(monkeypatch):
    monkeypatch.setattr(
        load_promos.settings,
        "ENV",
        "test",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["load_promos.py", "--test"],
    )

    files = [
        (Path("file1.gz"), "PromoFull"),
        (Path("file2.gz"), "PromoFull"),
    ]

    monkeypatch.setattr(
        load_promos,
        "find_promo_files",
        lambda _: files,
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    conn = FakeConnection()

    monkeypatch.setattr(
        load_promos,
        "get_connection",
        lambda: conn,
    )

    calls = []

    def fake_load_files(
        connection,
        filepaths,
        feeds_dir,
        log_changes,
    ):
        calls.append(
            (
                connection,
                filepaths,
                feeds_dir,
                log_changes,
            )
        )

    monkeypatch.setattr(
        load_promos,
        "load_files",
        fake_load_files,
    )

    load_promos.main()

    assert len(calls) == 1
    assert calls[0][0] is conn
    assert calls[0][1] == files
    assert calls[0][2] == Path("data/test_feeds")
    assert calls[0][3] is False