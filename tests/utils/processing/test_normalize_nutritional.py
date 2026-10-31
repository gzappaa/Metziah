import pytest

from utils.processing.normalize_nutritional import (
    NutritionRow,
    clean,
    lookup,
    parse_unit,
    parse_basis,
    normalize_row,
    normalize_rows,
    validate,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def row(label, value, unit=None, size="ל-100 גרם", lt=False):
    return {
        "label": label,
        "value": value,
        "unit": unit,
        "size": size,
        "lt": lt,
    }


def find(rows, nutrient, basis=None):
    return next(
        r for r in rows
        if r.nutrient == nutrient
        and (basis is None or r.basis == basis)
    )


# ------------------------------------------------------------------
# Cleaning and label lookup
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Total   Fat  ", "Total Fat"),
        ("\u200fנתרן\u200e", "נתרן"),
        ('ויטמין “A”', 'ויטמין "A"'),
        ("שומן   רווי", "שומן רווי"),
    ],
)
def test_clean(raw, expected):
    assert clean(raw) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Total Fat", "total_fat"),
        ("שומנים", "total_fat"),
        ("Protein", "protein"),
        ("חלבונים", "protein"),
        ("נתרן", "sodium"),
        ("Vitamin C", "vitamin_c"),
        ("A ויטמין", "vitamin_a"),
    ],
)
def test_lookup(label, expected):
    assert lookup(label) == expected


def test_unknown_label_returns_none():
    assert lookup("Unknown Nutrient") is None


# ------------------------------------------------------------------
# Units
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected_unit", "expected_bound"),
    [
        ("g", "g", None),
        ("גרם", "g", None),
        ("mg", "mg", None),
        ("מג", "mg", None),
        ("mcg", "mcg", None),
        ("קק\"ל", "kcal", None),
        ("מל", "ml", None),
        ("%", "%", None),
        ("גרםn", "g", None),
        ("גרם (מינ')", "g", "min"),
        ("גרם (מקס')", "g", "max"),
        ("unknown", None, None),
        (None, None, None),
    ],
)
def test_parse_unit(raw, expected_unit, expected_bound):
    assert parse_unit(raw) == (expected_unit, expected_bound)


def test_label_unit_overrides_conflicting_unit_field():
    result = normalize_row(
        label="נתרן (מג)",
        value=500,
        unit="g",
        size="ל-100 גרם",
    )

    assert result.nutrient == "sodium"
    assert result.amount == 500
    assert result.unit == "mg"
    assert "unit_mismatch" in result.flags


def test_mcg_converted_to_mg():
    result = normalize_row(
        label="מגנזיום",
        value=500,
        unit="mcg",
        size="ל-100 גרם",
    )

    assert result.nutrient == "magnesium"
    assert result.amount == pytest.approx(0.5)
    assert result.unit == "mg"
    assert result.flags == []


def test_kg_converted_to_g():
    result = normalize_row(
        label="Total Fat",
        value=0.5,
        unit="kg",
        size="ל-100 גרם",
    )

    assert result.amount == pytest.approx(500)
    assert result.unit == "g"


def test_missing_unit_is_flagged():
    result = normalize_row(
        label="Total Fat",
        value=10,
        unit=None,
        size="ל-100 גרם",
    )

    assert result.amount == 10
    assert result.unit is None
    assert "unit_missing" in result.flags


def test_unknown_label_is_preserved():
    result = normalize_row(
        label="Unknown Nutrient",
        value=12,
        unit="g",
        size="ל-100 גרם",
    )

    assert result is not None
    assert result.raw_label == "Unknown Nutrient"
    assert result.nutrient is None
    assert result.amount == 12
    assert result.unit == "g"
    assert "unmapped" in result.flags


# ------------------------------------------------------------------
# Basis
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("ל-100 גרם", "100g"),
        ("ל100 גרם", "100g"),
        ("ל-100 מל", "100ml"),
        ("ל-100 גרם תערובת יבשה", "100g:dry_mix"),
        ("ל-100 גרם תבשיל מוכן", "100g:prepared"),
        ("ל-100 גרם לאחר סינון", "100g:drained"),
        ("למנה", "serving"),
        ("למנה מוכנה", "serving:prepared"),
        ("ליחידה", "unit"),
        ("לכוס", "cup"),
        ("אחוזים", "percent_dv"),
        ("ל-3 יחידות", "3_units"),
        ("unknown basis", "other"),
        (None, "unknown"),
    ],
)
def test_parse_basis(size, expected):
    basis, _ = parse_basis(size)
    assert basis == expected


def test_basis_raw_is_preserved():
    raw = "ל-100 גרם תערובת יבשה"

    basis, basis_raw = parse_basis(raw)

    assert basis == "100g:dry_mix"
    assert basis_raw == raw


# ------------------------------------------------------------------
# Individual row normalization
# ------------------------------------------------------------------

def test_normalize_row_basic():
    result = normalize_row(
        label="Total Fat",
        value=12,
        unit="g",
        size="ל-100 גרם",
    )

    assert isinstance(result, NutritionRow)
    assert result.raw_label == "Total Fat"
    assert result.nutrient == "total_fat"
    assert result.amount == 12
    assert result.unit == "g"
    assert result.bound is None
    assert result.basis == "100g"
    assert result.basis_raw == "ל-100 גרם"
    assert result.flags == []
    assert result.is_canonical is True


@pytest.mark.parametrize("value", ["12", None, True, False])
def test_non_numeric_values_are_skipped(value):
    assert normalize_row(
        label="Total Fat",
        value=value,
        unit="g",
        size="ל-100 גרם",
    ) is None


def test_less_than_bound():
    result = normalize_row(
        label="Sodium",
        value=5,
        unit="mg",
        size="ל-100 גרם",
        less_than=True,
    )

    assert result.bound == "lt"


def test_unit_bound():
    result = normalize_row(
        label="Total Fat",
        value=5,
        unit="גרם (מינ')",
        size="ל-100 גרם",
    )

    assert result.bound == "min"


def test_less_than_overrides_unit_bound():
    result = normalize_row(
        label="Total Fat",
        value=5,
        unit="גרם (מקס')",
        size="ל-100 גרם",
        less_than=True,
    )

    assert result.bound == "lt"


def test_percent_daily_value_uses_percent_unit():
    result = normalize_row(
        label="Calcium",
        value=20,
        unit="mg",
        size="אחוזים",
    )

    assert result.nutrient == "calcium"
    assert result.amount == 20
    assert result.unit == "%"
    assert result.basis == "percent_dv"


def test_serving_nutrient_keeps_free_text_unit():
    result = normalize_row(
        label="Serving Size",
        value=30,
        unit="cup",
        size="למנה",
    )

    assert result.nutrient == "serving_size"
    assert result.amount == 30
    assert result.unit == "cup"


# ------------------------------------------------------------------
# Multiple rows and duplicates
# ------------------------------------------------------------------

def test_normalize_rows_skips_non_numeric_values():
    rows = normalize_rows([
        row("Total Fat", 10, "g"),
        row("ServingSizeFullTxt", "30g", None),
    ])

    assert len(rows) == 1
    assert rows[0].nutrient == "total_fat"


def test_exact_duplicate_is_skipped():
    rows = normalize_rows([
        row("Total Fat", 10, "g"),
        row("Total Fat", 20, "g"),
    ])

    assert len(rows) == 1
    assert rows[0].amount == 10


def test_same_nutrient_and_basis_keeps_first_as_canonical():
    rows = normalize_rows([
        row("Saturated Fat", 5, "g"),
        row("שומן רווי", 6, "g"),
    ])

    assert len(rows) == 2

    assert rows[0].nutrient == "saturated_fat"
    assert rows[0].is_canonical is True

    assert rows[1].nutrient == "saturated_fat"
    assert rows[1].is_canonical is False


def test_same_nutrient_with_different_basis_is_canonical():
    rows = normalize_rows([
        row("Total Fat", 10, "g", "ל-100 גרם"),
        row("Total Fat", 5, "g", "ל-100 גרם תערובת יבשה"),
    ])

    assert len(rows) == 2
    assert all(r.is_canonical for r in rows)


def test_unknown_rows_are_preserved():
    rows = normalize_rows([
        row("Unknown Nutrient", 10, "g"),
    ])

    assert len(rows) == 1
    assert rows[0].nutrient is None
    assert "unmapped" in rows[0].flags


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

def test_out_of_range_flag():
    rows = normalize_rows([
        row("Total Fat", 101, "g"),
    ])

    assert "out_of_range" in find(rows, "total_fat").flags


def test_macro_sum_high_flag():
    rows = normalize_rows([
        row("Protein", 40, "g"),
        row("Total Fat", 40, "g"),
        row("Total Carbohydrates", 30, "g"),
    ])

    for nutrient in ("protein", "total_fat", "total_carbs"):
        assert "macro_sum_high" in find(rows, nutrient).flags


def test_sugars_greater_than_carbs_flag():
    rows = normalize_rows([
        row("Total Carbohydrates", 10, "g"),
        row("Sugar", 12, "g"),
    ])

    assert "child_gt_parent" in find(rows, "sugars").flags
    assert "child_gt_parent" in find(rows, "total_carbs").flags


def test_energy_mismatch_flag():
    rows = normalize_rows([
        row("Protein", 10, "g"),
        row("Total Fat", 10, "g"),
        row("Total Carbohydrates", 10, "g"),
        row("Calories", 100, "kcal"),
    ])

    assert "energy_mismatch" in find(rows, "calories").flags


def test_energy_consistent_has_no_energy_mismatch():
    rows = normalize_rows([
        row("Protein", 10, "g"),
        row("Total Fat", 10, "g"),
        row("Total Carbohydrates", 10, "g"),
        row("Calories", 170, "kcal"),
    ])

    assert "energy_mismatch" not in find(rows, "calories").flags


def test_validation_ignores_different_bases():
    rows = normalize_rows([
        row("Protein", 40, "g", "ל-100 גרם"),
        row("Total Fat", 40, "g", "ל-100 גרם"),
        row("Total Carbohydrates", 30, "g", "ל-100 גרם תערובת יבשה"),
    ])

    assert "macro_sum_high" not in find(rows, "protein").flags
    assert "macro_sum_high" not in find(rows, "total_fat").flags


def test_validation_is_idempotent():
    rows = normalize_rows([
        row("Total Fat", 101, "g"),
    ])

    validate(rows)
    first_flags = list(rows[0].flags)

    validate(rows)

    assert rows[0].flags == first_flags


def test_validation_preserves_non_validation_flags():
    rows = normalize_rows([
        row("Unknown Nutrient", 10, "g"),
    ])

    validate(rows)

    assert "unmapped" in rows[0].flags