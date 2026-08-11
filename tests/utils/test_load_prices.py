from pathlib import Path
import pytest
from utils import load_prices
from parsers.xml import MachseneiXmlParser
from utils.load_prices import find_price_files, load_one_file
import gzip

def test_find_price_files():
    feeds_dir = Path("data/test_feeds")

    files = list(find_price_files(feeds_dir))

    assert files
    assert all(file.suffix == ".gz" for file in files)
    assert all(file.parent.name == "prices" for file in files)



def test_load_one_file(conn):
    feeds_dir = Path("data/test_feeds")
    filepath = next(find_price_files(feeds_dir))

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prices")
        price_count = cur.fetchone()[0]

    assert price_count > 0


def test_load_one_file_updates_store_subchain(conn):
    feeds_dir = Path("data/test_feeds")
    filepath = next(find_price_files(feeds_dir))

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )

    chain_id, sub_chain_id, store_id = filepath.relative_to(feeds_dir).parts[:3]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sub_chain_id
            FROM stores
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )

        row = cur.fetchone()

    assert row is not None
    assert row[0] == sub_chain_id



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


def test_load_one_file_empty_xml_does_nothing(conn, tmp_path):
    

    feeds_dir = tmp_path
    filepath = (
        feeds_dir
        / "TEST_CHAIN"
        / "001"
        / "001"
        / "prices"
        / "empty.gz"
    )

    filepath.parent.mkdir(parents=True)

    with gzip.open(filepath, "wb") as f:
        f.write(b"<xml></xml>")

    parser = MachseneiXmlParser()

    load_one_file(
        conn,
        parser,
        filepath,
        feeds_dir,
    )

def test_main_continues_after_file_failure(monkeypatch):
    monkeypatch.setattr(load_prices.settings, "ENV", "test")
    monkeypatch.setattr("sys.argv", ["load_prices.py", "--test"])

    files = [Path("file1.gz"), Path("file2.gz")]

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

        def rollback(self):
            pass

    monkeypatch.setattr(
        load_prices,
        "get_connection",
        lambda: FakeConnection(),
    )

    calls = []

    def fake_load_one_file(conn, parser, filepath, feeds_dir):
        calls.append(filepath)
        if filepath == files[0]:
            raise RuntimeError("test failure")

    monkeypatch.setattr(
        load_prices,
        "load_one_file",
        fake_load_one_file,
    )

    monkeypatch.setattr(
        load_prices,
        "MachseneiXmlParser",
        lambda: object(),
    )

    load_prices.main()

    assert calls == files


def test_main_rolls_back_on_failure(monkeypatch):
    monkeypatch.setattr(load_prices.settings, "ENV", "test")
    monkeypatch.setattr("sys.argv", ["load_prices.py", "--test"])

    filepath = Path("file.gz")

    monkeypatch.setattr(
        load_prices,
        "find_price_files",
        lambda _: [filepath],
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rollback(self):
            self.rolled_back = True

    conn = FakeConnection()
    conn.rolled_back = False

    monkeypatch.setattr(
        load_prices,
        "get_connection",
        lambda: conn,
    )

    monkeypatch.setattr(
        load_prices,
        "MachseneiXmlParser",
        lambda: object(),
    )

    def fail(*args):
        raise RuntimeError("test failure")

    monkeypatch.setattr(
        load_prices,
        "load_one_file",
        fail,
    )

    load_prices.main()

    assert conn.rolled_back is True


def test_main_continues_after_failure(monkeypatch):
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

        def rollback(self):
            pass

    monkeypatch.setattr(
        load_prices,
        "get_connection",
        lambda: FakeConnection(),
    )

    monkeypatch.setattr(
        load_prices,
        "MachseneiXmlParser",
        lambda: object(),
    )

    processed_files = []

    def fake_load_one_file(conn, parser, filepath, feeds_dir):
        processed_files.append(filepath)

        if filepath == files[0]:
            raise RuntimeError("test failure")

    monkeypatch.setattr(
        load_prices,
        "load_one_file",
        fake_load_one_file,
    )

    load_prices.main()

    assert processed_files == files