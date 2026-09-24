# tests/monitoring/test_chains_id_normalizer.py

import json

import utils.stores.chains_id_normalizer as chains_id_normalizer


def write_json(path, data):
    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )


def read_json(path):
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_find_store_padded_id():
    stores = [
        {"store_id": "001", "chain_id": "old"},
    ]

    assert (
        chains_id_normalizer.find_store(stores, "1")
        == stores[0]
    )


def test_find_store_unpadded_id():
    stores = [
        {"store_id": "1", "chain_id": "old"},
    ]

    assert (
        chains_id_normalizer.find_store(stores, "001")
        == stores[0]
    )


def test_find_store_missing():
    stores = [
        {"store_id": "001", "chain_id": "old"},
    ]

    assert (
        chains_id_normalizer.find_store(stores, "002")
        is None
    )


def test_enrich_source_updates_chain_id(tmp_path, monkeypatch):
    stores_file = tmp_path / "TestSource.json"

    write_json(
        stores_file,
        [
            {
                "chain_id": "9999999999999",
                "store_id": "3",
                "name": "Store 3",
            }
        ],
    )

    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        tmp_path,
    )

    source_data = {
        "unknown_chain_ids": [
            "7777777777777"
        ],
        "unknown_store_ids": {
            "7777777777777": ["003"]
        },
    }

    chains_id_normalizer.enrich_source(
        "TestSource",
        source_data,
    )

    stores = read_json(stores_file)

    assert stores[0]["chain_id"] == "7777777777777"
    assert stores[0]["store_id"] == "3"


def test_enrich_source_does_not_change_already_correct_chain(
    tmp_path,
    monkeypatch,
):
    stores_file = tmp_path / "TestSource.json"

    original = [
        {
            "chain_id": "7777777777777",
            "store_id": "3",
            "name": "Store 3",
        }
    ]

    write_json(stores_file, original)

    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        tmp_path,
    )

    chains_id_normalizer.enrich_source(
        "TestSource",
        {
            "unknown_chain_ids": [
                "7777777777777"
            ],
            "unknown_store_ids": {
                "7777777777777": ["003"]
            },
        },
    )

    assert read_json(stores_file) == original


def test_enrich_source_missing_store_does_not_write(
    tmp_path,
    monkeypatch,
):
    stores_file = tmp_path / "TestSource.json"

    original = [
        {
            "chain_id": "9999999999999",
            "store_id": "1",
        }
    ]

    write_json(stores_file, original)

    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        tmp_path,
    )

    chains_id_normalizer.enrich_source(
        "TestSource",
        {
            "unknown_chain_ids": [
                "7777777777777"
            ],
            "unknown_store_ids": {
                "7777777777777": ["003"]
            },
        },
    )

    assert read_json(stores_file) == original


def test_enrich_source_missing_stores_file(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        tmp_path,
    )

    chains_id_normalizer.enrich_source(
        "MissingSource",
        {
            "unknown_chain_ids": [
                "7777777777777"
            ],
            "unknown_store_ids": {
                "7777777777777": ["003"]
            },
        },
    )

    assert not (
        tmp_path / "MissingSource.json"
    ).exists()


def test_enrich_source_invalid_stores_file(
    tmp_path,
    monkeypatch,
):
    stores_file = tmp_path / "TestSource.json"

    write_json(
        stores_file,
        {"not": "a list"},
    )

    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        tmp_path,
    )

    chains_id_normalizer.enrich_source(
        "TestSource",
        {
            "unknown_chain_ids": [
                "7777777777777"
            ],
            "unknown_store_ids": {
                "7777777777777": ["003"]
            },
        },
    )

    assert read_json(stores_file) == {
        "not": "a list"
    }


def test_enrich_source_no_unknown_chains(
    tmp_path,
    monkeypatch,
):
    stores_file = tmp_path / "TestSource.json"

    original = [
        {
            "chain_id": "9999999999999",
            "store_id": "3",
        }
    ]

    write_json(stores_file, original)

    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        tmp_path,
    )

    chains_id_normalizer.enrich_source(
        "TestSource",
        {
            "unknown_chain_ids": [],
            "unknown_store_ids": {},
        },
    )

    assert read_json(stores_file) == original


def test_enrich_source_multiple_chains_and_stores(
    tmp_path,
    monkeypatch,
):
    stores_file = tmp_path / "TestSource.json"

    write_json(
        stores_file,
        [
            {
                "chain_id": "1111111111111",
                "store_id": "1",
            },
            {
                "chain_id": "1111111111111",
                "store_id": "2",
            },
        ],
    )

    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        tmp_path,
    )

    chains_id_normalizer.enrich_source(
        "TestSource",
        {
            "unknown_chain_ids": [
                "2222222222222",
                "3333333333333",
            ],
            "unknown_store_ids": {
                "2222222222222": ["001"],
                "3333333333333": ["002"],
            },
        },
    )

    stores = read_json(stores_file)

    assert stores[0]["chain_id"] == "2222222222222"
    assert stores[1]["chain_id"] == "3333333333333"


def test_main_processes_sources(
    tmp_path,
    monkeypatch,
):
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    filename_chains_file = (
        tmp_path / "filename_chains.json"
    )

    stores_file = stores_dir / "TestSource.json"

    write_json(
        stores_file,
        [
            {
                "chain_id": "9999999999999",
                "store_id": "3",
            }
        ],
    )

    write_json(
        filename_chains_file,
        {
            "TestSource": {
                "unknown_chain_ids": [
                    "7777777777777"
                ],
                "unknown_store_ids": {
                    "7777777777777": ["003"]
                },
            }
        },
    )

    monkeypatch.setattr(
        chains_id_normalizer,
        "STORES_DIR",
        stores_dir,
    )
    monkeypatch.setattr(
        chains_id_normalizer,
        "FILENAME_CHAINS_FILE",
        filename_chains_file,
    )

    chains_id_normalizer.main()

    stores = read_json(stores_file)

    assert stores[0]["chain_id"] == "7777777777777"