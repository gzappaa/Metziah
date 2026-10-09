import pytest

from utils.processing.normalize_nutritional import normalize_row, normalize_rows, parse_basis


@pytest.mark.parametrize("size, expected", [
    ("ל-100 גרם", "100g"),
    ("ל-100 מל", "100ml"),
    ("ל-100 גרם מוצר מבושל", "100g:cooked"),
    ('ל-100 מ"ל מוכן בהכנה דליל', "100ml:prepared_diluted"),
    ("ל 100 גרם ביסלי ללא שקית תיבול", "100g:other"),
    ("למנה", "serving"),
    ("אחוזים", "percent_dv"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_parse_basis(size, expected):
    assert parse_basis(size)[0] == expected


def test_label_unit_wins_over_garbage_field():
    r = normalize_row("נתרן (מג)", 45, "11", "ל-100 גרם")
    assert (r.nutrient, r.amount, r.unit, r.basis, r.flags) == ("sodium", 45, "mg", "100g", [])


def test_label_unit_mismatch_is_flagged_not_converted():
    r = normalize_row("נתרן (מג)", 45, "גרם", "ל-100 גרם")
    assert r.amount == 45 and r.flags == ["unit_mismatch"]


def test_variable_unit_is_converted_from_field():
    r = normalize_row("ויטמין B1 (תיאמין) (מג או מקג)", 370, "מקג", "למנה")
    assert r.unit == "mg" and r.amount == pytest.approx(0.37)


def test_variable_unit_without_field_is_flagged():
    r = normalize_row("ויטמין B1 (תיאמין) (מג או מקג)", 0.37, None, "למנה")
    assert r.unit is None and r.flags == ["unit_missing"]


def test_percent_dv_gets_percent_unit():
    assert normalize_row("ברזל (מג)", 15, "מג", "אחוזים").unit == "%"


def test_bounds():
    assert normalize_row("נתרן (מג)", 5, "מג", "ל-100 גרם", less_than=True).bound == "lt"
    assert normalize_row("סידן (מג)", 120, "(מינ׳)", "ל-100 גרם").bound == "min"


def test_unmapped_label_keeps_row():
    r = normalize_row("משהו חדש", 3, "גרם", "למנה")
    assert r.nutrient is None and r.flags == ["unmapped"]


def test_text_value_is_skipped():
    assert normalize_row("ServingSizeFullTxt", "1 cup") is None


def test_duplicate_nutrient_and_basis_marks_second_non_canonical():
    rows = [
        {"label": "חומצות שומן רוויות (גרם)", "value": 2, "unit": "גרם", "size": "ל-100 גרם"},
        {"label": "חומצות שומן רוויות (גרם) מתוך סך השומנים", "value": 2, "unit": "גרם", "size": "ל-100 גרם"},
    ]
    a, b = normalize_rows(rows)
    assert a.is_canonical and not b.is_canonical