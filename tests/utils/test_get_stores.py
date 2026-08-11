import json

import pytest

from models.store import Store
from utils.get_stores import clean_address, load_existing, compare_stores


def test_clean_address():
    assert clean_address(None) is None
    assert clean_address("") is None
    assert clean_address("  Main Street  ") == "Main Street"
    assert clean_address("Main   Street") == "Main Street"
    assert clean_address("Main Street https://example.com") == "Main Street"
    assert clean_address("Main Street http://example.com") == "Main Street"
    assert clean_address("Main Street https") == "Main Street"


def test_load_existing(tmp_path):
    stores = [
        {
            "chain_id": "7290661400001",
            "store_id": "001",
            "name": "Store One",
            "address": "Address One",
            "city": "Tel Aviv",
            "zip_code": "12345",
        },
        {
            "chain_id": "7290661400001",
            "store_id": "002",
            "name": "Store Two",
            "address": None,
            "city": None,
            "zip_code": None,
        },
    ]

    path = tmp_path / "stores.json"
    path.write_text(json.dumps(stores), encoding="utf-8")

    result = load_existing(path)

    assert result["001"] == stores[0]
    assert result["002"] == stores[1]


def test_load_existing_missing_file(tmp_path):
    path = tmp_path / "stores.json"

    assert load_existing(path) == {}


def test_compare_stores():
    old = {
        "001": {
            "store_id": "001",
            "name": "Store One",
            "address": "Old Address",
            "city": "Tel Aviv",
            "zip_code": "12345",
        },
        "002": {
            "store_id": "002",
            "name": "Store Two",
            "address": "Address Two",
            "city": "Haifa",
            "zip_code": "54321",
        },
    }

    new = [
        Store(
            chain_id="7290661400001",
            store_id="001",
            name="Store One Updated",
            address="New Address",
            city="Tel Aviv",
            zip_code="12345",
        ),
        Store(
            chain_id="7290661400001",
            store_id="003",
            name="Store Three",
            address=None,
            city=None,
            zip_code=None,
        ),
    ]

    changes = compare_stores(old, new)

    assert "NEW STORE: 003" in changes
    assert "REMOVED STORE: 002" in changes
    assert "CHANGED 001 name: Store One -> Store One Updated" in changes
    assert "CHANGED 001 address: Old Address -> New Address" in changes