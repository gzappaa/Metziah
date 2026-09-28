import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from models.store import Store
from utils.stores import seed_stores


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHAINS_FILE = PROJECT_ROOT / "data" / "reference" / "chains.json"
CHAINS_EXTRA_FILE = PROJECT_ROOT / "data" / "reference" / "chains_extra.json"


def _load_real_chains():
    with open(CHAINS_FILE, encoding="utf-8") as f:
        chains = json.load(f)

    if CHAINS_EXTRA_FILE.exists():
        with open(CHAINS_EXTRA_FILE, encoding="utf-8") as f:
            chains.update(json.load(f))

    return chains


def _real_chain_id():
    chains = _load_real_chains()
    return next(iter(chains))


def test_normalize_store_id():
    assert seed_stores.normalize_store_id("006") == "6"
    assert seed_stores.normalize_store_id("06") == "6"
    assert seed_stores.normalize_store_id("6") == "6"
    assert seed_stores.normalize_store_id("069") == "69"
    assert seed_stores.normalize_store_id(" TEST ") == "TEST"


def test_load_stores_from_json(tmp_path):
    path = tmp_path / "stores.json"

    path.write_text(
        json.dumps(
            [
                {
                    "chain_id": "123",
                    "store_id": "006",
                    "name": "Test Store",
                    "address": "Test Address",
                    "city": "Test City",
                    "zip_code": "00000000",
                    "latitude": 31.5,
                    "longitude": 34.8,
                }
            ]
        ),
        encoding="utf-8",
    )

    stores = seed_stores.load_stores_from_json(path)

    assert stores == [
        Store(
            chain_id="123",
            store_id="6",
            name="Test Store",
            address="Test Address",
            city="Test City",
            zip_code="00000000",
            latitude=31.5,
            longitude=34.8,
        )
    ]


def test_load_stores_from_json_optional_fields(tmp_path):
    path = tmp_path / "stores.json"

    path.write_text(
        json.dumps(
            [
                {
                    "chain_id": "123",
                    "store_id": "001",
                    "name": "Test Store",
                }
            ]
        ),
        encoding="utf-8",
    )

    stores = seed_stores.load_stores_from_json(path)

    assert stores[0] == Store(
        chain_id="123",
        store_id="1",
        name="Test Store",
        address=None,
        city=None,
        zip_code=None,
        latitude=None,
        longitude=None,
    )


def test_load_chains_from_json(tmp_path):
    path = tmp_path / "chains.json"

    data = {
        "123": {
            "name_he_normalized": "Test",
            "name_en_normalized": "Test",
        }
    }

    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    assert seed_stores.load_chains_from_json(path) == data


def test_load_test_store_keys(tmp_path):
    test_feeds = tmp_path / "data" / "test_feeds"

    (test_feeds / "123" / "006").mkdir(parents=True)
    (test_feeds / "123" / "007").mkdir(parents=True)
    (test_feeds / "456" / "001").mkdir(parents=True)

    (test_feeds / "not_a_chain_file").write_text("x")
    (test_feeds / "123" / "file.txt").write_text("x")

    result = seed_stores.load_test_store_keys(test_feeds)

    assert result == {
        ("123", "6"),
        ("123", "7"),
        ("456", "1"),
    }


def test_load_test_store_keys_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        seed_stores.load_test_store_keys(
            tmp_path / "does_not_exist"
        )


def test_main_seeds_all_stores(monkeypatch, tmp_path):
    chain_id = _real_chain_id()

    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    stores_file = stores_dir / "test.json"
    stores_file.write_text(
        json.dumps(
            [
                {
                    "chain_id": chain_id,
                    "store_id": "001",
                    "name": "Store 1",
                },
                {
                    "chain_id": chain_id,
                    "store_id": "002",
                    "name": "Store 2",
                },
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        seed_stores,
        "STORES_DIR",
        stores_dir,
    )

    monkeypatch.setattr(
        seed_stores,
        "CHAINS_REFERENCE_FILE",
        CHAINS_FILE,
    )

    monkeypatch.setattr(
        seed_stores,
        "CHAINS_EXTRA_REFERENCE_FILE",
        CHAINS_EXTRA_FILE,
    )

    conn = MagicMock()

    ensure_chain = MagicMock()
    upsert_stores = MagicMock()

    monkeypatch.setattr(
        seed_stores,
        "ensure_chain",
        ensure_chain,
    )

    monkeypatch.setattr(
        seed_stores,
        "upsert_stores",
        upsert_stores,
    )

    monkeypatch.setattr(
        seed_stores,
        "logger",
        MagicMock(),
    )

    monkeypatch.setattr(
        seed_stores,
        "get_connection",
        lambda: _fake_connection(conn),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_stores"],
    )

    seed_stores.main()

    upsert_stores.assert_called_once()

    seeded_stores = upsert_stores.call_args.args[1]

    assert seeded_stores == [
        Store(
            chain_id=chain_id,
            store_id="1",
            name="Store 1",
            address=None,
            city=None,
            zip_code=None,
            latitude=None,
            longitude=None,
        ),
        Store(
            chain_id=chain_id,
            store_id="2",
            name="Store 2",
            address=None,
            city=None,
            zip_code=None,
            latitude=None,
            longitude=None,
        ),
    ]


    chains = _load_real_chains()

    assert ensure_chain.call_count == len(chains)

    for chain_id, chain in chains.items():
        ensure_chain.assert_any_call(
            conn,
            chain_id,
            chain["name_he_normalized"],
            chain["name_en_normalized"],
        )

    conn.commit.assert_called_once()


def test_main_test_mode_only_seeds_test_feed_stores(
    monkeypatch,
    tmp_path,
):
    chain_id = _real_chain_id()

    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    stores_file = stores_dir / "test.json"
    stores_file.write_text(
        json.dumps(
            [
                {
                    "chain_id": chain_id,
                    "store_id": "001",
                    "name": "Store 1",
                },
                {
                    "chain_id": chain_id,
                    "store_id": "002",
                    "name": "Store 2",
                },
                {
                    "chain_id": chain_id,
                    "store_id": "003",
                    "name": "Store 3",
                },
            ]
        ),
        encoding="utf-8",
    )

    test_feeds = tmp_path / "data" / "test_feeds"
    (test_feeds / chain_id / "002").mkdir(parents=True)

    monkeypatch.setattr(
        seed_stores,
        "PROJECT_ROOT",
        tmp_path,
    )

    monkeypatch.setattr(
        seed_stores,
        "STORES_DIR",
        stores_dir,
    )

    monkeypatch.setattr(
        seed_stores,
        "CHAINS_REFERENCE_FILE",
        CHAINS_FILE,
    )

    monkeypatch.setattr(
        seed_stores,
        "CHAINS_EXTRA_REFERENCE_FILE",
        CHAINS_EXTRA_FILE,
    )

    conn = MagicMock()

    ensure_chain = MagicMock()
    upsert_stores = MagicMock()

    monkeypatch.setattr(
        seed_stores,
        "ensure_chain",
        ensure_chain,
    )

    monkeypatch.setattr(
        seed_stores,
        "upsert_stores",
        upsert_stores,
    )

    monkeypatch.setattr(
        seed_stores,
        "get_connection",
        lambda: _fake_connection(conn),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_stores", "--test"],
    )

    seed_stores.main()

    upsert_stores.assert_called_once()

    seeded_stores = upsert_stores.call_args.args[1]

    assert seeded_stores == [
        Store(
            chain_id=chain_id,
            store_id="2",
            name="Store 2",
            address=None,
            city=None,
            zip_code=None,
            latitude=None,
            longitude=None,
        )
    ]


    chains = _load_real_chains()

    assert ensure_chain.call_count == len(chains)

    for chain_id, chain in chains.items():
        ensure_chain.assert_any_call(
            conn,
            chain_id,
            chain["name_he_normalized"],
            chain["name_en_normalized"],
        )

    conn.commit.assert_called_once()


def test_main_returns_when_no_store_files(
    monkeypatch,
    tmp_path,
):
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    monkeypatch.setattr(
        seed_stores,
        "STORES_DIR",
        stores_dir,
    )

    get_connection = MagicMock()

    monkeypatch.setattr(
        seed_stores,
        "get_connection",
        get_connection,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_stores"],
    )

    seed_stores.main()

    get_connection.assert_not_called()


def test_main_returns_when_no_stores_selected(
    monkeypatch,
    tmp_path,
):
    chain_id = _real_chain_id()

    stores_dir = tmp_path / "data" / "stores"
    stores_dir.mkdir(parents=True)

    (stores_dir / "test.json").write_text(
        json.dumps(
            [
                {
                    "chain_id": chain_id,
                    "store_id": "001",
                    "name": "Store 1",
                }
            ]
        ),
        encoding="utf-8",
    )

    test_feeds = tmp_path / "data" / "test_feeds"
    test_feeds.mkdir(parents=True)

    monkeypatch.setattr(
        seed_stores,
        "PROJECT_ROOT",
        tmp_path,
    )

    monkeypatch.setattr(
        seed_stores,
        "STORES_DIR",
        stores_dir,
    )

    monkeypatch.setattr(
        seed_stores,
        "CHAINS_REFERENCE_FILE",
        CHAINS_FILE,
    )

    monkeypatch.setattr(
        seed_stores,
        "CHAINS_EXTRA_REFERENCE_FILE",
        CHAINS_EXTRA_FILE,
    )

    get_connection = MagicMock()

    monkeypatch.setattr(
        seed_stores,
        "get_connection",
        get_connection,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_stores", "--test"],
    )

    seed_stores.main()

    get_connection.assert_not_called()





class _fake_connection:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False