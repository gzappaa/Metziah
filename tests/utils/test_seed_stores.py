import json

import pytest

from models.store import Store
from utils.seed_stores import load_stores_from_json


def test_load_stores_from_json(tmp_path):
    data = [
        {
            "chain_id": "7290661400001",
            "store_id": "001",
            "name": "Test Store",
            "address": "123 Main St",
            "city": "Tel Aviv",
            "zip_code": "12345",
            "latitude": 32.0853,
            "longitude": 34.7818,
        },
        {
            "chain_id": "7290661400001",
            "store_id": "002",
            "name": "Second Store",
        },
    ]

    json_path = tmp_path / "stores.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    stores = load_stores_from_json(json_path)

    assert len(stores) == 2

    assert stores[0] == Store(
        chain_id="7290661400001",
        store_id="001",
        name="Test Store",
        address="123 Main St",
        city="Tel Aviv",
        zip_code="12345",
        latitude=32.0853,
        longitude=34.7818,
    )

    assert stores[1] == Store(
        chain_id="7290661400001",
        store_id="002",
        name="Second Store",
        address=None,
        city=None,
        zip_code=None,
        latitude=None,
        longitude=None,
    )


def test_load_stores_from_json_missing_required_field(tmp_path):
    data = [
        {
            "chain_id": "7290661400001",
            "store_id": "001",
            # name is missing
        }
    ]

    json_path = tmp_path / "stores.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(KeyError):
        load_stores_from_json(json_path)