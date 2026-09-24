import json

import pytest

import utils.stores.add_unregistered_stores as module


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_json(tmp_path):
    path = tmp_path / "test.json"
    data = {"foo": "bar"}

    write_json(path, data)

    assert module.load_json(path) == data


def test_main_adds_unregistered_stores(monkeypatch, tmp_path):
    missing_file = tmp_path / "stores_missing_from_registry.json"
    chains_file = tmp_path / "chains.json"
    extra_file = tmp_path / "chains_extra.json"

    write_json(
        missing_file,
        {
            "shufersal": {
                "chain_id": "7290027600007",
                "store_ids": ["041", "006"],
            }
        },
    )

    write_json(
        chains_file,
        {
            "7290027600007": {
                "name_he_normalized": "שופרסל",
                "name_en_normalized": "Shufersal",
            }
        },
    )

    monkeypatch.setattr(module, "MISSING_STORES_FILE", missing_file)
    monkeypatch.setattr(module, "CHAINS_REFERENCE_FILE", chains_file)
    monkeypatch.setattr(module, "CHAINS_EXTRA_REFERENCE_FILE", extra_file)

    ensure_chain_calls = []
    upsert_calls = []

    monkeypatch.setattr(
        module,
        "ensure_chain",
        lambda conn, chain_id, he_name, en_name: ensure_chain_calls.append(
            (chain_id, he_name, en_name)
        ),
    )
    monkeypatch.setattr(
        module,
        "upsert_stores",
        lambda conn, stores: upsert_calls.append(stores),
    )

    class DummyConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def commit(self):
            pass

    monkeypatch.setattr(module, "get_connection", lambda: DummyConnection())

    module.main()

    assert ensure_chain_calls == [
        ("7290027600007", "שופרסל", "Shufersal")
    ]

    stores = upsert_calls[0]

    assert len(stores) == 2
    assert stores[0].chain_id == "7290027600007"
    assert stores[0].store_id == "41"
    assert stores[0].name == "Unregistered store - shufersal - 41"

    assert stores[1].chain_id == "7290027600007"
    assert stores[1].store_id == "6"
    assert stores[1].name == "Unregistered store - shufersal - 6"

    assert stores[0].address is None
    assert stores[0].city is None
    assert stores[0].zip_code is None
    assert stores[0].latitude is None
    assert stores[0].longitude is None


def test_main_loads_chains_extra(monkeypatch, tmp_path):
    missing_file = tmp_path / "missing.json"
    chains_file = tmp_path / "chains.json"
    extra_file = tmp_path / "chains_extra.json"

    chain_id = "7290999999999"

    write_json(
        missing_file,
        {
            "unknown_source": {
                "chain_id": chain_id,
                "store_ids": ["12"],
            }
        },
    )

    write_json(chains_file, {})
    write_json(
        extra_file,
        {
            chain_id: {
                "name_he_normalized": "רשת נוספת",
                "name_en_normalized": "Extra Chain",
            }
        },
    )

    monkeypatch.setattr(module, "MISSING_STORES_FILE", missing_file)
    monkeypatch.setattr(module, "CHAINS_REFERENCE_FILE", chains_file)
    monkeypatch.setattr(module, "CHAINS_EXTRA_REFERENCE_FILE", extra_file)

    ensure_chain_calls = []
    upsert_calls = []

    monkeypatch.setattr(
        module,
        "ensure_chain",
        lambda conn, *args: ensure_chain_calls.append(args),
    )
    monkeypatch.setattr(
        module,
        "upsert_stores",
        lambda conn, stores: upsert_calls.append(stores),
    )

    class DummyConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def commit(self):
            pass

    monkeypatch.setattr(module, "get_connection", lambda: DummyConnection())

    module.main()

    assert ensure_chain_calls == [
        (chain_id, "רשת נוספת", "Extra Chain")
    ]
    assert len(upsert_calls[0]) == 1


def test_main_raises_for_unknown_chain(monkeypatch, tmp_path):
    missing_file = tmp_path / "missing.json"
    chains_file = tmp_path / "chains.json"
    extra_file = tmp_path / "chains_extra.json"

    chain_id = "7290999999999"

    write_json(
        missing_file,
        {
            "unknown_source": {
                "chain_id": chain_id,
                "store_ids": ["1"],
            }
        },
    )

    write_json(chains_file, {})
    write_json(extra_file, {})

    monkeypatch.setattr(module, "MISSING_STORES_FILE", missing_file)
    monkeypatch.setattr(module, "CHAINS_REFERENCE_FILE", chains_file)
    monkeypatch.setattr(module, "CHAINS_EXTRA_REFERENCE_FILE", extra_file)

    with pytest.raises(KeyError, match=chain_id):
        module.main()


def test_main_does_nothing_when_no_stores(monkeypatch, tmp_path):
    missing_file = tmp_path / "missing.json"
    chains_file = tmp_path / "chains.json"
    extra_file = tmp_path / "chains_extra.json"

    write_json(missing_file, {})
    write_json(chains_file, {})
    write_json(extra_file, {})

    monkeypatch.setattr(module, "MISSING_STORES_FILE", missing_file)
    monkeypatch.setattr(module, "CHAINS_REFERENCE_FILE", chains_file)
    monkeypatch.setattr(module, "CHAINS_EXTRA_REFERENCE_FILE", extra_file)

    monkeypatch.setattr(
        module,
        "get_connection",
        lambda: pytest.fail("Database should not be opened"),
    )

    module.main()


def test_main_commits(monkeypatch, tmp_path):
    missing_file = tmp_path / "missing.json"
    chains_file = tmp_path / "chains.json"
    extra_file = tmp_path / "chains_extra.json"

    chain_id = "7290027600007"

    write_json(
        missing_file,
        {
            "source": {
                "chain_id": chain_id,
                "store_ids": ["123"],
            }
        },
    )

    write_json(
        chains_file,
        {
            chain_id: {
                "name_he_normalized": "שופרסל",
                "name_en_normalized": "Shufersal",
            }
        },
    )
    write_json(extra_file, {})

    monkeypatch.setattr(module, "MISSING_STORES_FILE", missing_file)
    monkeypatch.setattr(module, "CHAINS_REFERENCE_FILE", chains_file)
    monkeypatch.setattr(module, "CHAINS_EXTRA_REFERENCE_FILE", extra_file)

    committed = False

    class DummyConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def commit(self):
            nonlocal committed
            committed = True

    monkeypatch.setattr(module, "get_connection", lambda: DummyConnection())
    monkeypatch.setattr(module, "ensure_chain", lambda *args: None)
    monkeypatch.setattr(module, "upsert_stores", lambda *args: None)

    module.main()

    assert committed is True