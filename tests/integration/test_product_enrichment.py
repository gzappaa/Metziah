"""
Integration tests: parsed JSONL  ->  product_enrichment  ->  product_nutrition

Runs the REAL loaders (load_products_enriched.main / process_source and
load_products_nutrition.load_product_nutrition) against the real test DB.

Isolation / cleanup (see `isolated_db` in conftest.py):
  * the loaders' get_connection() is swapped for the rolled-back `conn`
    fixture with commit() disabled, so NOTHING is ever committed
    * parsed files are copied into tmp_path; category mapping uses the real
    data/reference/categories.json
  * teardown rolls back and then deletes any 590123456789_ barcode anyway

Fixture data (tests/fixtures/):
  parsed/fictionalmarket/products_parsed.jsonl   almond drink (A), crackers (B),
                                                 2 invalid rows, trailing blank line
  parsed/secondmarket/products_parsed.jsonl      conflicting A', gap-filling B',
                                                 new product D
  reference/categories.json                      canonical category mapping

  A = 5901234567890   B = 5901234567891   D = 5901234567892
"""

import shutil
import sys
import types

import psycopg
import pytest
from psycopg.rows import dict_row

from config import settings
import utils.products.load_products_enriched as enriched
import utils.products.load_products_nutrition as nutrition
from utils.processing.normalize_nutritional import normalize_rows
from pathlib import Path
from tests.conftest import ENRICHMENT_TEST_CODE_LIKE, FIXTURES_DIR

A = "5901234567890"  # almond drink   (both sources)
B = "5901234567891"  # crackers       (both sources, sparse in the first)
D = "5901234567892"  # rice snack     (second source only)

TRUTH = "fictionalmarket"
FALLBACK = "secondmarket"


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parsed_env(tmp_path, monkeypatch, isolated_db):
    """Copy parsed fixtures to tmp_path and use the real category mapping."""
    parsed = tmp_path / "data" / "parsed"
    shutil.copytree(FIXTURES_DIR / "parsed", parsed)

    monkeypatch.setattr(enriched, "PARSED_ROOT", parsed)
    monkeypatch.setattr(
        enriched,
        "CATEGORIES_PATH",
        Path("data/reference/categories.json"),
    )
    monkeypatch.setattr(enriched, "get_connection", lambda: isolated_db)
    monkeypatch.setattr(enriched, "setup_general_logging", lambda: None)
    monkeypatch.setattr(nutrition, "PARSED_DIR", parsed)

    return types.SimpleNamespace(
        parsed=parsed,
        db=isolated_db,
        monkeypatch=monkeypatch,
    )


def run_enrichment(env, source):
    """Run the real CLI entry point: `load_products_enriched --source <source>`."""
    env.monkeypatch.setattr(
        sys, "argv", ["load_products_enriched", "--source", source]
    )
    enriched.main()


def run_everything(env, source=TRUTH):
    run_enrichment(env, source)
    nutrition.load_product_nutrition()


def get_enrichment(db, item_code):
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM product_enrichment WHERE item_code = %s", (item_code,)
        )
        return cur.fetchone()


def get_nutrition(db, item_code):
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM product_nutrition WHERE item_code = %s "
            "ORDER BY nutrient NULLS LAST, basis, raw_label",
            (item_code,),
        )
        return cur.fetchall()


def by_key(rows):
    """Mapped rows indexed by (nutrient, basis)."""
    return {(r["nutrient"], r["basis"]): r for r in rows if r["nutrient"]}


def count(db, table):
    with db.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {table} WHERE item_code LIKE %s",
            (ENRICHMENT_TEST_CODE_LIKE,),
        )
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# category mapping
# ---------------------------------------------------------------------------

def test_category_mapping_is_built_from_json(parsed_env):
    mapping = enriched.load_category_mapping()

    assert mapping["ירקות ופירות / ירקות"] == ("ירקות ופירות", "ירקות")
    assert mapping["מוצרי מכולת / שימורים"] == ("מכולת ובישול", "שימורים")




# ---------------------------------------------------------------------------
# product_enrichment
# ---------------------------------------------------------------------------

def test_every_valid_product_is_inserted_and_invalid_ones_are_not(parsed_env):
    run_enrichment(parsed_env, TRUTH)

    assert count(parsed_env.db, "product_enrichment") == 3  # A, B, D
    for code in (A, B, D):
        assert get_enrichment(parsed_env.db, code) is not None

    # the no-barcode / blank-barcode rows must not have produced anything
    with parsed_env.db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM product_enrichment "
            "WHERE name_he IN ('מוצר בלי ברקוד', 'ברקוד ריק')"
        )
        assert cur.fetchone()[0] == 0


def test_metadata_fields_are_stored(parsed_env):
    run_enrichment(parsed_env, TRUTH)

    row = get_enrichment(parsed_env.db, A)

    assert row["source"] == TRUTH
    assert FALLBACK not in row["source_file"]
    assert row["source_file"].endswith("products_parsed.jsonl")
    assert row["local_name"] == "משקה שקדים טרי 1 ליטר"
    assert row["name_he"] == "משקה שקדים טבעי 1 ליטר"
    assert row["name_en"] == "Fictional Almond Drink"
    assert row["brand_he"] == "אלמונדיה"
    assert row["brand_en"] == "Almondia"
    assert row["family_he"] == "משקאות שקדים"
    assert row["family_en"] == "Almond Drinks"
    assert row["department_he"] == "משקאות ומוצרים צמחיים"
    assert row["ingredients_he"].startswith("מים, שקדים (4%)")
    assert row["ingredients_en"].startswith("Water, almonds (4%)")
    assert row["description_he"] == "משקה שקדים צמחי לשימוש יומיומי."
    assert row["description_en"].startswith("A fictional plant-based almond drink")
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_raw_category_path_is_kept_and_canonical_category_is_derived(parsed_env):
    run_enrichment(parsed_env, TRUTH)

    a = get_enrichment(parsed_env.db, A)

    # raw taxonomy exactly as scraped (all 3 levels), canonical from the first 2
    assert a["category_path_he"] == [
    "בריאות ותזונה",
    "תחליפי חלב",
    "משקאות שקדים",
    ]
    assert a["category_path_en"] == [
        "Food & Beverages",
        "Plant-Based Drinks",
        "Almond Drinks",
    ]
    assert a["category_he"] == "חלב וביצים"
    assert a["subcategory_he"] == "תחליפי חלב ובשר"

    # a 2-level path is enough for the mapping (D only exists in source 2)
    d = get_enrichment(parsed_env.db, D)
    assert d["category_path_he"] == ["ירקות ופירות", "ירקות"]
    assert (d["category_he"], d["subcategory_he"]) == ("ירקות ופירות", "ירקות")


def test_unmapped_category_keeps_raw_path_and_leaves_canonical_null(parsed_env):
    run_enrichment(parsed_env, TRUTH)

    b = get_enrichment(parsed_env.db, B)

    assert b["category_path_he"] == ["מזון ומשקאות", "מוצרים מיוחדים", "פריטים"]
    assert b["category_he"] is None
    assert b["subcategory_he"] is None


def test_nutrition_raw_is_stored_as_scraped_jsonb(parsed_env):
    run_enrichment(parsed_env, TRUTH)

    assert get_enrichment(parsed_env.db, B)["nutrition_raw"] == {
        "Calories": 400,
        "Serving Size": 30,
        "ServingSizeFullTxt": "30 g (about 6 crackers)",
    }
    assert get_enrichment(parsed_env.db, A)["nutrition_raw"] is None

    # and it is queryable through the GIN-indexed JSONB column
    with parsed_env.db.cursor() as cur:
        cur.execute(
            "SELECT item_code FROM product_enrichment WHERE nutrition_raw ? 'Calories'"
        )
        assert [r[0] for r in cur.fetchall()] == [B]


def test_selected_source_is_source_of_truth_when_sources_conflict(parsed_env):
    run_enrichment(parsed_env, TRUTH)

    a = get_enrichment(parsed_env.db, A)
    b = get_enrichment(parsed_env.db, B)

    assert a["name_he"] == "משקה שקדים טבעי 1 ליטר"          # NOT 'שם אחר מהמקור השני'
    assert a["brand_he"] == "אלמונדיה"
    assert a["description_he"] == "משקה שקדים צמחי לשימוש יומיומי."
    assert b["name_he"] == "קרקרים מלוחים"
    assert b["brand_he"] == "קראנצ'י"
    assert a["source"] == b["source"] == TRUTH


def test_switching_source_of_truth_flips_the_winner(parsed_env):
    run_enrichment(parsed_env, FALLBACK)

    a = get_enrichment(parsed_env.db, A)
    b = get_enrichment(parsed_env.db, B)

    assert a["name_he"] == "שם אחר מהמקור השני"
    assert a["brand_he"] == "מותג אחר"
    assert a["description_he"] == "תיאור אחר"
    assert a["source"] == FALLBACK
    assert b["name_he"] == "שם אחר שלא אמור לדרוס"
    assert b["source"] == FALLBACK

    # ...while still filling what the new source of truth doesn't have
    assert a["brand_en"] == "Almondia"
    assert b["ingredients_he"] == "קמח, שמן צמחי, מלח"


def test_fallback_source_fills_empty_fields_only(parsed_env):
    run_enrichment(parsed_env, TRUTH)

    b = get_enrichment(parsed_env.db, B)

    # empty in the source of truth -> filled from the fallback source
    assert b["brand_en"] == "Crunchy"
    assert b["family_he"] == "קרקרים"
    assert b["description_en"] == "Salted crackers, fictional edition."
    assert b["ingredients_en"] == "Flour, vegetable oil, salt"

    # non-empty in the source of truth -> untouched
    assert b["name_he"] == "קרקרים מלוחים"
    assert b["brand_he"] == "קראנצ'י"
    assert b["ingredients_he"] == "קמח, שמן צמחי, מלח"

    # a product only the fallback knows about is added, attributed to it
    d = get_enrichment(parsed_env.db, D)
    assert d["source"] == FALLBACK
    assert d["name_en"] == "Fictional Rice Snack"


def test_process_source_reports_counts(parsed_env):
    mapping = enriched.load_category_mapping()
    first = parsed_env.parsed / TRUTH / "products_parsed.jsonl"
    second = parsed_env.parsed / FALLBACK / "products_parsed.jsonl"

    # (inserted, updated, skipped, invalid)
    assert enriched.process_source(
        parsed_env.db, TRUTH, first, True, mapping
    ) == (2, 0, 0, 2)  # A, B inserted; no-barcode + blank-barcode invalid

    assert enriched.process_source(
        parsed_env.db, FALLBACK, second, False, mapping
    ) == (1, 2, 0, 0)  # D inserted; A', B' only fill gaps


def test_malformed_json_lines_are_skipped(parsed_env):
    broken = parsed_env.parsed / "brokenmarket"
    broken.mkdir()
    (broken / "products_parsed.jsonl").write_text(
        '{this is not json\n'
        '{"barcode": "5901234567899", "name_he": "מוצר תקין אחרי שורה שבורה"}\n',
        encoding="utf-8",
    )

    run_enrichment(parsed_env, "brokenmarket")

    assert get_enrichment(parsed_env.db, "5901234567899")["name_he"] == (
        "מוצר תקין אחרי שורה שבורה"
    )
    assert count(parsed_env.db, "product_enrichment") == 4  # + A, B, D from the others


def test_unknown_source_exits_without_touching_the_db(parsed_env):
    with pytest.raises(SystemExit):
        run_enrichment(parsed_env, "does-not-exist")

    assert count(parsed_env.db, "product_enrichment") == 0


def test_enrichment_rerun_is_idempotent(parsed_env):
    run_enrichment(parsed_env, TRUTH)
    first = {c: get_enrichment(parsed_env.db, c) for c in (A, B, D)}

    run_enrichment(parsed_env, TRUTH)

    assert count(parsed_env.db, "product_enrichment") == 3
    for code, before in first.items():
        after = get_enrichment(parsed_env.db, code)
        for column in ("name_he", "brand_he", "brand_en", "category_he",
                       "subcategory_he", "source", "nutrition_raw"):
            assert after[column] == before[column], (code, column)


# ---------------------------------------------------------------------------
# nutrition extraction (pure, but driven by the real fixture)
# ---------------------------------------------------------------------------

def _fixture_product(env, barcode):
    for _path, product in nutrition.iter_products():
        if product.get("barcode") == barcode and product.get("company") == TRUTH:
            return product
    raise AssertionError(f"{barcode} not in fixture")


def test_nutrition_rows_flatten_sizes_values_and_units(parsed_env):
    rows = nutrition.nutrition_rows(_fixture_product(parsed_env, A))

    assert len(rows) == 28  # 14 nutrients x 2 sizes
    assert rows[0] == {
        "label": "אנרגיה (קלוריות)",
        "value": 32,
        "unit": "קלוריות",
        "size": "ל-100 מל",
        "lt": False,
    }
    assert {r["size"] for r in rows} == {"ל-100 מל", "לכוס"}


def test_non_numeric_nutrition_values_are_dropped_by_the_normalizer(parsed_env):
    rows = nutrition.nutrition_rows(_fixture_product(parsed_env, B))

    assert any(r["label"] == "ServingSizeFullTxt" for r in rows)
    assert not any(
        r.raw_label == "ServingSizeFullTxt" for r in normalize_rows(rows)
    )


# ---------------------------------------------------------------------------
# product_nutrition
# ---------------------------------------------------------------------------

def test_nutrition_row_counts_per_product(parsed_env):
    run_everything(parsed_env)

    assert len(get_nutrition(parsed_env.db, A)) == 29  # 28 + iron from 2nd source
    assert len(get_nutrition(parsed_env.db, B)) == 9   # 10 normalized - 1 collapsed dupe
    assert len(get_nutrition(parsed_env.db, D)) == 1
    assert count(parsed_env.db, "product_nutrition") == 39


def test_nutrition_source_is_the_first_source_that_has_the_barcode(parsed_env):
    run_everything(parsed_env)

    assert {r["source"] for r in get_nutrition(parsed_env.db, A)} == {TRUTH}
    assert {r["source"] for r in get_nutrition(parsed_env.db, B)} == {TRUTH}
    assert {r["source"] for r in get_nutrition(parsed_env.db, D)} == {FALLBACK}


def test_nutrition_values_are_normalized_per_basis(parsed_env):
    run_everything(parsed_env)

    rows = by_key(get_nutrition(parsed_env.db, A))

    assert float(rows["sodium", "100ml"]["amount"]) == pytest.approx(45)
    assert rows["sodium", "100ml"]["unit"] == "mg"
    assert float(rows["vitamin_b12", "100ml"]["amount"]) == pytest.approx(0.35)
    assert rows["vitamin_b12", "100ml"]["unit"] == "mcg"
    assert float(rows["calories", "cup"]["amount"]) == pytest.approx(64)
    assert rows["calories", "cup"]["unit"] == "kcal"
    assert float(rows["trans_fat", "100ml"]["amount"]) == 0   # zero is kept, not dropped
    assert rows["calories", "100ml"]["basis_raw"] == "ל-100 מל"
    assert rows["calories", "cup"]["basis_raw"] == "לכוס"
    assert all(r["flags"] == [] for r in rows.values())
    assert all(r["is_canonical"] for r in rows.values())


def test_unmapped_labels_are_kept_with_a_flag(parsed_env):
    run_everything(parsed_env)

    unmapped = [r for r in get_nutrition(parsed_env.db, A) if r["nutrient"] is None]

    assert len(unmapped) == 4  # 2 unknown labels x 2 bases
    assert {r["raw_label"] for r in unmapped} == {"סוכרים (גרם)", "ויטמין B2 (מג)"}
    assert all(r["flags"] == ["unmapped"] for r in unmapped)
    assert float(
        next(r for r in unmapped if r["raw_label"] == "סוכרים (גרם)" and r["basis"] == "100ml")["amount"]
    ) == pytest.approx(2.8)


def test_second_source_fills_gaps_but_never_overwrites(parsed_env):
    run_everything(parsed_env)

    rows = by_key(get_nutrition(parsed_env.db, A))

    # source 2 says 99 kcal, source 1 says 32 -> 32 stays
    assert float(rows["calories", "100ml"]["amount"]) == pytest.approx(32)
    # source 2 is the only one with iron -> added
    assert float(rows["iron", "100ml"]["amount"]) == pytest.approx(0.4)
    assert rows["iron", "100ml"]["unit"] == "mg"


def test_two_spellings_of_the_same_nutrient_collapse_to_one_row(parsed_env):
    run_everything(parsed_env)

    sat_fat = [
        r for r in get_nutrition(parsed_env.db, B)
        if r["nutrient"] == "saturated_fat" and r["basis"] == "100g"
    ]

    assert len(sat_fat) == 1
    assert float(sat_fat[0]["amount"]) == pytest.approx(3)   # first spelling wins, not 3.2
    assert sat_fat[0]["is_canonical"] is True


def test_unit_conversion_bounds_flags_and_bases(parsed_env):
    run_everything(parsed_env)

    rows = by_key(get_nutrition(parsed_env.db, B))

    # unit field said grams, label says mg -> label wins and the conflict is flagged
    assert float(rows["sodium", "100g"]["amount"]) == pytest.approx(480)
    assert rows["sodium", "100g"]["unit"] == "mg"
    assert rows["sodium", "100g"]["flags"] == ["unit_mismatch"]

    # "(מג או מקג)" label + unit field "מקג": 120 mcg stored as 0.12 mg
    assert float(rows["vitamin_b1", "100g"]["amount"]) == pytest.approx(0.12)
    assert rows["vitamin_b1", "100g"]["unit"] == "mg"

    # valueLessThan -> bound 'lt'
    assert rows["salt", "100g"]["bound"] == "lt"
    assert float(rows["salt", "100g"]["amount"]) == pytest.approx(1.2)

    # percent-of-daily-value basis is its own basis with unit '%'
    assert float(rows["calcium", "percent_dv"]["amount"]) == pytest.approx(6)
    assert rows["calcium", "percent_dv"]["unit"] == "%"
    assert ("calcium", "100g") not in rows

    # non-numeric ServingSizeFullTxt never reaches the table
    assert not any(
        r["raw_label"] == "ServingSizeFullTxt" for r in get_nutrition(parsed_env.db, B)
    )


def test_nutrition_rebuild_is_idempotent_and_replaces_stale_rows(parsed_env):
    run_everything(parsed_env)

    with parsed_env.db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO product_nutrition (item_code, source, raw_label, basis_raw)
            VALUES (%s, %s, 'stale row that must disappear', 'x')
            """,
            (A, TRUTH),
        )

    nutrition.load_product_nutrition()  # TRUNCATE + reload

    assert count(parsed_env.db, "product_nutrition") == 39
    assert not any(
        r["raw_label"] == "stale row that must disappear"
        for r in get_nutrition(parsed_env.db, A)
    )


def test_deleting_an_enrichment_row_cascades_to_its_nutrition(parsed_env):
    run_everything(parsed_env)

    with parsed_env.db.cursor() as cur:
        cur.execute("DELETE FROM product_enrichment WHERE item_code = %s", (A,))

    assert get_enrichment(parsed_env.db, A) is None
    assert get_nutrition(parsed_env.db, A) == []
    assert len(get_nutrition(parsed_env.db, B)) == 9   # others untouched
    assert len(get_nutrition(parsed_env.db, D)) == 1


# ---------------------------------------------------------------------------
# "delete everything": prove the test run leaves nothing behind
# ---------------------------------------------------------------------------

def test_loaders_leave_nothing_committed(parsed_env):
    run_everything(parsed_env)
    assert count(parsed_env.db, "product_enrichment") == 3   # visible in OUR transaction

    # A completely separate connection must see none of it. (Only product_enrichment is
    # read: the nutrition loader's TRUNCATE holds a lock on product_nutrition until rollback.)
    other = psycopg.connect(
        host=settings.PGHOST,
        port=settings.PGPORT,
        user=settings.PGUSER,
        password=settings.PGPASSWORD,
        dbname=settings.PGDATABASE,
        options="-c lock_timeout=3000",
    )
    try:
        with other.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM product_enrichment WHERE item_code LIKE %s",
                (ENRICHMENT_TEST_CODE_LIKE,),
            )
            assert cur.fetchone()[0] == 0
    finally:
        other.close()