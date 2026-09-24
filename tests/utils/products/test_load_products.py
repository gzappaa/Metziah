from pathlib import Path

import pytest

import utils.products.load_products as module


CHAIN_ID = "999999999999"
STORE_ID = "1"


def make_pricefull_file(feeds_dir, filename):
    filepath = (
        feeds_dir
        / CHAIN_ID
        / STORE_ID
        / "pricesfull"
        / filename
    )
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"")
    return filepath


# ---------------------------------------------------------------------------
# find_pricefull_files
# ---------------------------------------------------------------------------


def test_find_pricefull_files_returns_latest_file(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"

    older = make_pricefull_file(
        feeds_dir,
        "PriceFull9999999999999-001-001-20260101-000000.gz",
    )

    newer = make_pricefull_file(
        feeds_dir,
        "PriceFull9999999999999-001-001-20260102-000000.gz",
    )

    def fake_parse_filename(filename):
        return {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": "001",
            "store_id": "001",
            "file_date": filename.split("-")[3],
        }

    monkeypatch.setattr(
        module,
        "parse_filename",
        fake_parse_filename,
    )
    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: filename.rsplit("-", 1)[1].removesuffix(".gz"),
    )

    result = list(module.find_pricefull_files(feeds_dir))

    assert result == [newer]
    assert older not in result


def test_find_pricefull_files_uses_timestamp_when_date_is_same(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"

    older = make_pricefull_file(
        feeds_dir,
        "PriceFull9999999999999-001-001-20260101-000000.gz",
    )

    newer = make_pricefull_file(
        feeds_dir,
        "PriceFull9999999999999-001-001-20260101-120000.gz",
    )

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": "001",
            "store_id": "001",
            "file_date": "20260101",
        },
    )
    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: filename.rsplit("-", 1)[1].removesuffix(".gz"),
    )

    result = list(module.find_pricefull_files(feeds_dir))

    assert result == [newer]
    assert older not in result


def test_find_pricefull_files_keeps_different_stores(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"

    store_1 = make_pricefull_file(
        feeds_dir,
        "PriceFull9999999999999-001-001-20260101-000000.gz",
    )

    store_2 = (
        feeds_dir
        / CHAIN_ID
        / "2"
        / "pricesfull"
        / "PriceFull9999999999999-001-002-20260101-000000.gz"
    )
    store_2.parent.mkdir(parents=True, exist_ok=True)
    store_2.write_bytes(b"")

    def fake_parse_filename(filename):
        store_id = "002" if "-002-" in filename else "001"

        return {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": "001",
            "store_id": store_id,
            "file_date": "20260101",
        }

    monkeypatch.setattr(
        module,
        "parse_filename",
        fake_parse_filename,
    )
    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: "000000",
    )

    result = list(module.find_pricefull_files(feeds_dir))

    assert len(result) == 2
    assert store_1 in result
    assert store_2 in result


def test_find_pricefull_files_keeps_different_subchains(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"

    subchain_1 = make_pricefull_file(
        feeds_dir,
        "PriceFull9999999999999-001-001-20260101-000000.gz",
    )

    subchain_2 = make_pricefull_file(
        feeds_dir,
        "PriceFull9999999999999-002-001-20260101-000000.gz",
    )

    def fake_parse_filename(filename):
        sub_chain_id = "002" if "-002-" in filename else "001"

        return {
            "file_type": "PriceFull",
            "chain_id": CHAIN_ID,
            "sub_chain_id": sub_chain_id,
            "store_id": "001",
            "file_date": "20260101",
        }

    monkeypatch.setattr(
        module,
        "parse_filename",
        fake_parse_filename,
    )
    monkeypatch.setattr(
        module,
        "extract_time_suffix",
        lambda filename: "000000",
    )

    result = list(module.find_pricefull_files(feeds_dir))

    assert len(result) == 2
    assert subchain_1 in result
    assert subchain_2 in result


def test_find_pricefull_files_ignores_non_pricefull(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"

    filepath = make_pricefull_file(
        feeds_dir,
        "Price9999999999999-001-001-20260101-000000.gz",
    )

    monkeypatch.setattr(
        module,
        "parse_filename",
        lambda filename: {
            "file_type": "Price",
            "chain_id": CHAIN_ID,
            "sub_chain_id": "001",
            "store_id": "001",
            "file_date": "20260101",
        },
    )

    result = list(module.find_pricefull_files(feeds_dir))

    assert result == []
    assert filepath.exists()


def test_find_pricefull_files_skips_invalid_filename(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"

    make_pricefull_file(
        feeds_dir,
        "invalid.gz",
    )

    def raise_value_error(filename):
        raise ValueError("invalid filename")

    monkeypatch.setattr(
        module,
        "parse_filename",
        raise_value_error,
    )

    result = list(module.find_pricefull_files(feeds_dir))

    assert result == []


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_returns_when_no_files(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(module.settings, "ENV", "test")
    monkeypatch.setattr(module, "TEST_FEEDS_DIR", tmp_path)

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        lambda feeds_dir: [],
    )

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
                "dev": False,
                "test": True,
                "feeds_dir": Path("ignored"),
            },
        )(),
    )

    called = False

    def fake_get_connection():
        nonlocal called
        called = True
        raise AssertionError("Database connection should not be opened")

    monkeypatch.setattr(
        module,
        "get_connection",
        fake_get_connection,
    )

    module.main()

    assert called is False


def test_main_loads_files(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(module.settings, "ENV", "test")
    monkeypatch.setattr(module, "TEST_FEEDS_DIR", tmp_path)

    filepath = make_pricefull_file(
        tmp_path,
        "PriceFull9999999999999-001-001-20260101-000000.gz",
    )

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        lambda feeds_dir: [filepath],
    )

    loaded = []

    monkeypatch.setattr(
        module,
        "load_files",
        lambda conn, files, feeds_dir: loaded.append(
            (conn, files, feeds_dir)
        ),
    )

    class DummyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(
        module,
        "get_connection",
        lambda: DummyConnection(),
    )

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
                "dev": False,
                "test": True,
                "feeds_dir": Path("ignored"),
            },
        )(),
    )

    module.main()

    assert len(loaded) == 1
    assert loaded[0][1] == [filepath]
    assert loaded[0][2] == tmp_path


def test_main_uses_default_feeds_dir(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(module.settings, "ENV", "test")
    monkeypatch.setattr(module, "BASE_DIR", tmp_path)

    captured = []

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        lambda feeds_dir: captured.append(feeds_dir) or [],
    )

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
                "dev": False,
                "test": False,
                "feeds_dir": Path("data/feeds"),
            },
        )(),
    )

    module.main()

    assert captured == [
        (tmp_path / "data" / "feeds").resolve()
    ]


def test_main_test_flag_overrides_feeds_dir(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(module.settings, "ENV", "test")
    monkeypatch.setattr(module, "TEST_FEEDS_DIR", tmp_path / "test_feeds")

    captured = []

    monkeypatch.setattr(
        module,
        "find_pricefull_files",
        lambda feeds_dir: captured.append(feeds_dir) or [],
    )

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
                "dev": False,
                "test": True,
                "feeds_dir": Path("some/other/feeds"),
            },
        )(),
    )

    module.main()

    assert captured == [
        (tmp_path / "test_feeds").resolve()
    ]


def test_main_rejects_dev_without_confirmation(
    monkeypatch,
):
    monkeypatch.setattr(module.settings, "ENV", "dev")

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
                "dev": False,
                "test": False,
                "feeds_dir": Path("data/feeds"),
            },
        )(),
    )

    with pytest.raises(
        RuntimeError,
        match="Development database selected",
    ):
        module.main()


def test_main_rejects_dev_outside_dev_environment(
    monkeypatch,
):
    monkeypatch.setattr(module.settings, "ENV", "test")

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
                "dev": True,
                "test": False,
                "feeds_dir": Path("data/feeds"),
            },
        )(),
    )

    with pytest.raises(
        RuntimeError,
        match="configured environment is not dev",
    ):
        module.main()


def test_main_rejects_test_outside_test_environment(
    monkeypatch,
):
    monkeypatch.setattr(module.settings, "ENV", "prod")

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
                "dev": False,
                "test": True,
                "feeds_dir": Path("data/feeds"),
            },
        )(),
    )

    with pytest.raises(
        RuntimeError,
        match="configured environment is not test",
    ):
        module.main()