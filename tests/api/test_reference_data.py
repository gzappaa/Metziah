"""Tests for loading shopper reference data at application startup."""

import json
from pathlib import Path
from unittest.mock import mock_open, patch

from api import main


def test_reference_files_exist() -> None:
    project_root = Path(__file__).resolve().parents[2]
    reference_dir = project_root / "data" / "reference"

    assert (reference_dir / "categories.json").is_file()
    assert (reference_dir / "store_products.json").is_file()


def test_reference_json_is_readable() -> None:
    project_root = Path(__file__).resolve().parents[2]
    reference_dir = project_root / "data" / "reference"

    for filename in ("categories.json", "store_products.json"):
        with (reference_dir / filename).open(encoding="utf-8") as file:
            data = json.load(file)

        assert isinstance(data, (dict, list)), filename


def test_reference_data_is_loaded_once_at_startup() -> None:
    # This test defines the expected startup interface:
    # main.load_reference_data() should load both files once.
    with (
        patch.object(
            main,
            "load_json",
            side_effect=[{"categories": []}, {}],
        ) as load_json,
    ):
        main.load_reference_data()
        main.load_reference_data()

    assert load_json.call_count == 2