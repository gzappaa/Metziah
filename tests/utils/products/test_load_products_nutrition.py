
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from utils.products import load_products_nutrition as loader
from utils.processing.normalize_nutritional import NutritionRow


@pytest.fixture
def raw_product():
    """Fictional product matching the real parsed-feed nutrition structure."""
    return {
        "company": "fictional_market",
        "barcode": "7290000000001",
        "nutrition_values": {
            "sizes": [
                {"id": 101, "names": {"1": "ל-100 מל"}},
                {"id": 102, "names": {"1": "לכוס"}},
            ],
            "values": [
                {
                    "id": 201,
                    "names": {"1": "אנרגיה (קלוריות)"},
                    "sizeValues": [
                        {
                            "sizeId": 101,
                            "unitOfMeasure": {"names": {"1": "קלוריות"}},
                            "value": 51,
                            "valueLessThan": False,
                        },
                        {
                            "sizeId": 102,
                            "unitOfMeasure": {"names": {"1": "קלוריות"}},
                            "value": 102,
                            "valueLessThan": False,
                        },
                    ],
                },
                {
                    "id": 202,
                    "names": {"1": "חלבונים (גרם)"},
                    "sizeValues": [
                        {
                            "sizeId": 101,
                            "unitOfMeasure": {"names": {"1": "גרם"}},
                            "value": 3.3,
                            "valueLessThan": False,
                        },
                        {
                            "sizeId": 102,
                            "unitOfMeasure": {"names": {"1": "גרם"}},
                            "value": 6.6,
                            "valueLessThan": False,
                        },
                    ],
                },
            ],
        },
    }

@pytest.fixture
def nutrition_row():
    def make(
        nutrient="protein",
        amount=12.5,
        unit="g",
        raw_label="Protein",
        basis="100g",
        basis_raw="ל-100 גרם",
        flags=None,
        is_canonical=True,
    ):
        return NutritionRow(
            raw_label=raw_label,
            nutrient=nutrient,
            amount=amount,
            unit=unit,
            bound=None,
            basis=basis,
            basis_raw=basis_raw,
            flags=flags or [],
            is_canonical=is_canonical,
        )

    return make


def test_iter_products_reads_sorted_jsonl_files(tmp_path, monkeypatch, raw_product):
    parsed_dir = tmp_path / "parsed"
    (parsed_dir / "z_market").mkdir(parents=True)
    (parsed_dir / "a_market").mkdir(parents=True)

    first = parsed_dir / "a_market" / "products_parsed.jsonl"
    second = parsed_dir / "z_market" / "products_parsed.jsonl"

    first.write_text(
        "\n" + json.dumps(raw_product) + "\n\n",
        encoding="utf-8",
    )
    second.write_text(json.dumps({"barcode": "7290000000002"}), encoding="utf-8")

    monkeypatch.setattr(loader, "PARSED_DIR", parsed_dir)

    products = list(loader.iter_products())

    assert [path.parent.name for path, _ in products] == [
        "a_market",
        "z_market",
    ]
    assert products[0][1]["barcode"] == raw_product["barcode"]


def test_nutrition_rows_extracts_values_units_sizes_and_bounds(raw_product):
    rows = loader.nutrition_rows(raw_product)

    assert rows == [
        {
            "label": "אנרגיה (קלוריות)",
            "value": 51,
            "unit": "קלוריות",
            "size": "ל-100 מל",
            "lt": False,
        },
        {
            "label": "אנרגיה (קלוריות)",
            "value": 102,
            "unit": "קלוריות",
            "size": "לכוס",
            "lt": False,
        },
        {
            "label": "חלבונים (גרם)",
            "value": 3.3,
            "unit": "גרם",
            "size": "ל-100 מל",
            "lt": False,
        },
        {
            "label": "חלבונים (גרם)",
            "value": 6.6,
            "unit": "גרם",
            "size": "לכוס",
            "lt": False,
        },
    ]


@pytest.mark.parametrize(
    "nutrition",
    [None, [], "invalid", {}],
)
def test_nutrition_rows_returns_empty_for_invalid_structure(nutrition):
    assert loader.nutrition_rows({"nutrition_values": nutrition}) == []


def test_nutrition_rows_skips_values_without_labels():
    product = {
        "nutrition_values": {
            "sizes": [],
            "values": [
                {"names": {}, "sizeValues": [{"value": 10}]},
                {"names": {"1": ""}, "sizeValues": [{"value": 20}]},
            ],
        }
    }

    assert loader.nutrition_rows(product) == []


def test_nutrition_key_uses_canonical_nutrient_and_basis(nutrition_row):
    row = nutrition_row(nutrient="protein", basis="100g")

    assert loader._nutrition_key(row) == ("canonical", "protein", "100g")


def test_nutrition_key_uses_raw_label_for_unmapped_rows(nutrition_row):
    row = nutrition_row(
        nutrient=None,
        raw_label="Unknown nutrient",
        basis_raw="per serving",
    )

    assert loader._nutrition_key(row) == (
        "unmapped",
        "Unknown nutrient",
        "per serving",
    )


@pytest.mark.parametrize(
    ("existing", "incoming", "expected"),
    [
        (None, 12.5, 12.5),
        (12.5, 20.0, 12.5),
        (0, 20.0, 0),
        (None, None, None),
    ],
)
def test_merge_value_only_fills_missing_values(existing, incoming, expected):
    assert loader._merge_value(existing, incoming) == expected


def test_reconcile_rows_preserves_existing_values_and_combines_flags(
    nutrition_row,
):
    existing = nutrition_row(
        amount=10,
        unit="g",
        flags=["unit_missing"],
    )
    incoming = nutrition_row(
        amount=20,
        unit="mg",
        flags=["unmapped"],
    )
    incoming.bound = "lt"

    result = loader.reconcile_rows(existing, incoming)

    assert result is existing
    assert result.amount == 10
    assert result.unit == "g"
    assert result.bound == "lt"
    assert result.flags == ["unit_missing", "unmapped"]


def test_reconcile_rows_fills_missing_fields(nutrition_row):
    existing = nutrition_row(
        amount=None,
        unit=None,
        raw_label="",
        basis_raw="",
    )
    incoming = nutrition_row(
        amount=8,
        unit="g",
        raw_label="Protein",
        basis_raw="ל-100 גרם",
    )

    loader.reconcile_rows(existing, incoming)

    assert existing.amount == 8
    assert existing.unit == "g"
    assert existing.raw_label == "Protein"
    assert existing.basis_raw == "ל-100 גרם"


class FakeCursor:
    def __init__(self):
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        self.executions.append((" ".join(query.split()), params))


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.committed = True


def test_load_product_nutrition_reconciles_sources_and_inserts(
    monkeypatch,
    raw_product,
    nutrition_row,
    capsys,
):
    product_a = {
        **raw_product,
        "company": "market_a",
    }
    product_b = {
        **raw_product,
        "company": "market_b",
    }
    product_b["nutrition_values"] = {
        **raw_product["nutrition_values"],
        "values": [
            {
                "id": 202,
                "names": {"1": "חלבונים (גרם)"},
                "sizeValues": [
                    {
                        "sizeId": 101,
                        "unitOfMeasure": {"names": {"1": "גרם"}},
                        "value": 99,
                        "valueLessThan": False,
                    }
                ],
            }
        ],
    }

    monkeypatch.setattr(
        loader,
        "iter_products",
        lambda: iter([
            (None, product_a),
            (None, product_b),
            (None, {"company": "missing_barcode"}),
            (None, {
                "barcode": "7290000000002",
                "company": "no_nutrition",
                "nutrition_values": {},
            }),
        ]),
    )

    validation_calls = []

    def fake_validate(rows):
        validation_calls.append(list(rows))

    monkeypatch.setattr(loader, "validate", fake_validate)

    connection = FakeConnection()

    @contextmanager
    def fake_connection():
        yield connection

    monkeypatch.setattr(loader.db, "get_connection", fake_connection)

    loader.load_product_nutrition()

    statements = connection.fake_cursor.executions
    assert statements[0][0] == "TRUNCATE product_nutrition"

    inserts = [
        params
        for query, params in statements
        if query.startswith("INSERT")
    ]

    # Two nutrients, each with two distinct serving bases.
    assert len(inserts) == 4
    assert all(row[0] == "7290000000001" for row in inserts)

    protein_100ml = next(
        row for row in inserts
        if row[3] == "protein" and row[7] == "100ml"
    )
    assert protein_100ml[4] == 3.3  # market_a's value wins over 99
    assert protein_100ml[5] == "g"

    protein_cup = next(
        row for row in inserts
        if row[3] == "protein" and row[7] == "cup"
    )
    assert protein_cup[4] == 6.6

    assert connection.committed
    assert len(validation_calls) == 1

    output = capsys.readouterr().out
    assert "Products with nutrition: 1" in output
    assert "Inserted nutrition rows: 4" in output