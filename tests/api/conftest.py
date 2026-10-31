"""Shared fixtures for the shopper API tests (tests/api).

IMPORTANT: do NOT add an __init__.py to tests/api - the folder would become a
top-level package called `api` and shadow the real `api` package.

Two kinds of tests live here:

* unit / route tests   - no database; collaborators are monkeypatched.
* integration tests    - use `seed` + `api_db`: real Postgres, everything is
                         written inside the `conn` fixture's transaction and
                         rolled back at teardown (nothing is ever committed).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """TestClient without lifespan (so data/reference/*.json isn't needed).

    raise_server_exceptions=False -> an unhandled error shows up as a 500
    response that tests can assert on, instead of blowing up the test.
    """
    # Jinja2Templates(directory="api/templates") is relative to the CWD.
    monkeypatch.chdir(PROJECT_ROOT)
    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------
# Database plumbing
# --------------------------------------------------------------------------

class _NoCommit:
    """Wrap the rolled-back-at-teardown `conn` so production code can run
    unmodified: commit/close are no-ops and `with conn:` doesn't close it."""

    def __init__(self, real):
        self._real = real

    def commit(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def api_db(conn, monkeypatch):
    """Route every `get_connection()` used by the API to the test transaction.

    NOTE: api.queries / api.routes_web do `from db import get_connection`, so
    patching `db.get_connection` would NOT affect them - we patch the names
    inside those modules.
    """
    import api.queries as queries
    import api.routes_web as routes_web

    proxy = _NoCommit(conn)
    monkeypatch.setattr(queries, "get_connection", lambda: proxy)
    monkeypatch.setattr(routes_web, "get_connection", lambda: proxy)
    return proxy


CHAIN_A = "7770000000001"
CHAIN_B = "7770000000002"
TEST_CHAINS = (CHAIN_A, CHAIN_B)

# Product barcodes
MILK = "7770000000101"        # enriched, in products, has prices + promos + nutrition
CHEESE = "7770000000102"      # enriched, in products, no prices
NO_PRODUCT = "7770000000103"  # enriched but NOT in products  -> not "packaged"
STORE_CODE = "7770000000104"  # enriched, in products AND in store_products -> excluded

CAT_PACKAGED = "קטגוריית-ארוזים-טסט"
CAT_FRESH = "קטגוריית-טריים-טסט"
SUB_TOMATO = "עגבניהטסט"
SUB_CHICKEN = "חזהטסט עוףטסט"

TOMATO_CHERRY = "עגבניהטסט שרי"
TOMATO_ORGANIC = "עגבניהטסט אורגנית"


@pytest.fixture
def seed(conn, api_db):
    """Insert a small, self-contained dataset inside the test transaction."""
    now = datetime.now(timezone.utc)
    day = timedelta(days=1)

    with conn.cursor() as cur:
        # Refuse to run on top of leftovers (we never want to touch real data).
        cur.execute("SELECT count(*) FROM chains WHERE chain_id = ANY(%s)", (list(TEST_CHAINS),))
        if cur.fetchone()[0]:
            pytest.fail(f"Chains {TEST_CHAINS} already exist in the DB; remove them first.")

        # Partitions are created INSIDE the transaction (DDL is transactional
        # in Postgres) so they vanish on rollback.
        for chain_id in TEST_CHAINS:
            cur.execute(f"CREATE TABLE prices_{chain_id} PARTITION OF prices FOR VALUES IN ('{chain_id}')")
            cur.execute(
                f"CREATE TABLE promotion_items_{chain_id} PARTITION OF promotion_items FOR VALUES IN ('{chain_id}')"
            )

        cur.execute(
            "INSERT INTO chains (chain_id, name_he_normalized, name_en_normalized, brands) VALUES "
            "(%s, 'רשת בדיקה א', 'test chain a', ARRAY['מותג א']), "
            "(%s, 'רשת בדיקה ב', 'test chain b', '{}')",
            (CHAIN_A, CHAIN_B),
        )

        stores = [
            (CHAIN_A, "S1", "סניף א1", "תל אביב", Decimal("32.0853"), Decimal("34.7818")),
            (CHAIN_A, "S2", None, "חיפה", None, None),  # store_name is NULL on purpose
            (CHAIN_B, "S1", "סניף ב1", "ירושלים", None, None),
            (CHAIN_B, "S2", "סניף ב2", "באר שבע", None, None),
        ]
        for chain_id, store_id, name, city, lat, lon in stores:
            cur.execute(
                "INSERT INTO stores (chain_id, store_id, store_name, city, latitude, longitude) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (chain_id, store_id, name, city, lat, lon),
            )

        # ---- packaged products -------------------------------------------
        for code in (MILK, CHEESE, STORE_CODE):
            cur.execute("INSERT INTO products (item_code, name) VALUES (%s, %s)", (code, f"p-{code}"))

        enrichment = [
            (MILK, "חלבטסט תנובה", "Test Milk", "תנובה", "Tnuva", CAT_PACKAGED, "חלב"),
            (CHEESE, "גבינהטסט", "Test Cheese", None, None, CAT_PACKAGED, None),
            (NO_PRODUCT, "ללא מוצר", None, None, None, CAT_PACKAGED, None),
            (STORE_CODE, "קוד חנות", None, None, None, CAT_PACKAGED, None),
        ]
        for code, he, en, bhe, ben, cat, sub in enrichment:
            cur.execute(
                "INSERT INTO product_enrichment "
                "(item_code, source, name_he, name_en, brand_he, brand_en, category_he, subcategory_he, "
                " category_path_he, category_path_en, description_he, nutrition_raw) "
                "VALUES (%s,'test',%s,%s,%s,%s,%s,%s, ARRAY['חלב', NULL, 'מוצרי חלב'], ARRAY['Dairy', NULL], "
                "'תיאור', '{\"אנרגיה\": \"60\"}'::jsonb)",
                (code, he, en, bhe, ben, cat, sub),
            )

        nutrition = [
            # (raw_label, nutrient, amount, unit, basis)
            ("זzz-unmapped", None, None, None, "100ml"),
            ("שומן", "fat", Decimal("3.0"), "g", "100ml"),
            ("חלבון", "protein", Decimal("3.3"), "g", "100g"),
        ]
        for raw_label, nutrient, amount, unit, basis in nutrition:
            cur.execute(
                "INSERT INTO product_nutrition (item_code, source, raw_label, nutrient, amount, unit, basis, basis_raw) "
                "VALUES (%s,'test',%s,%s,%s,%s,%s,%s)",
                (MILK, raw_label, nutrient, amount, unit, basis, basis),
            )

        prices = [
            (CHAIN_A, "S1", MILK, Decimal("5.90"), Decimal("5.90")),
            (CHAIN_A, "S2", MILK, Decimal("0.00"), None),     # zero price = "unavailable"
            (CHAIN_B, "S1", MILK, Decimal("6.50"), None),
            (CHAIN_B, "S2", MILK, None, None),                # NULL price
        ]
        for chain_id, store_id, code, price, unit_price in prices:
            cur.execute(
                "INSERT INTO prices (chain_id, store_id, item_code, price, unit_price) VALUES (%s,%s,%s,%s,%s)",
                (chain_id, store_id, code, price, unit_price),
            )

        # ---- promotions on MILK ------------------------------------------
        promos = [
            # id, chain, store, start, end, discounted, min_qty
            ("PA1", CHAIN_A, "S1", now - day, now + 5 * day, Decimal("4.90"), Decimal("2")),  # active
            ("PA2", CHAIN_A, "S1", now - 5 * day, now - day, Decimal("1.00"), None),          # expired
            ("PA3", CHAIN_A, "S1", now + 3 * day, now + 9 * day, Decimal("1.50"), None),      # future
            ("PA4", CHAIN_A, "S1", None, None, Decimal("5.10"), None),                        # open-ended
            ("PB1", CHAIN_B, "S1", now - day, now + day, Decimal("6.00"), None),              # active, other chain
        ]
        for pid, chain_id, store_id, start, end, discounted, min_qty in promos:
            _insert_promo(cur, pid, chain_id, store_id, start, end, MILK, discounted, min_qty, f"מבצע {pid}")

        # ---- fresh (store_products) --------------------------------------
        cur.execute(
            "INSERT INTO store_product_categories (name, sort_order) VALUES (%s, 9999) RETURNING id",
            (CAT_FRESH,),
        )
        category_id = cur.fetchone()[0]
        subs = {}
        for order, name in enumerate((SUB_TOMATO, SUB_CHICKEN), start=1):
            cur.execute(
                "INSERT INTO store_product_subcategories (category_id, name, sort_order) VALUES (%s,%s,%s) RETURNING id",
                (category_id, name, order),
            )
            subs[name] = cur.fetchone()[0]

        store_products = [
            (CHAIN_A, "S1", "F1", TOMATO_CHERRY),
            (CHAIN_B, "S1", "F2", TOMATO_CHERRY),
            (CHAIN_A, "S2", "F3", TOMATO_ORGANIC),
            (CHAIN_A, "S1", "F4", "עוףטסט טרי חזהטסט"),  # words reversed + extra word
            (CHAIN_A, "S1", STORE_CODE, "פריט חנות"),
        ]
        for chain_id, store_id, code, name in store_products:
            cur.execute(
                "INSERT INTO store_products (chain_id, store_id, item_code, name) VALUES (%s,%s,%s,%s)",
                (chain_id, store_id, code, name),
            )

        fresh_prices = [
            (CHAIN_A, "S1", "F1", Decimal("3.50")),
            (CHAIN_B, "S1", "F2", Decimal("0.00")),
            (CHAIN_A, "S2", "F3", None),
        ]
        for chain_id, store_id, code, price in fresh_prices:
            cur.execute(
                "INSERT INTO prices (chain_id, store_id, item_code, price) VALUES (%s,%s,%s,%s)",
                (chain_id, store_id, code, price),
            )

        _insert_promo(cur, "PF1", CHAIN_A, "S1", now - day, now + 4 * day, "F1", Decimal("2.90"), None, "מבצע עגבניות")
        _insert_promo(cur, "PF2", CHAIN_A, "S1", now - 5 * day, now - day, "F1", Decimal("1.00"), None, "מבצע שפג")

        # The "fresh" queries read the materialized view
        # `store_product_category_matches`. REFRESHing it recomputes EVERY
        # store_product x subcategory pair in the whole DB (very slow on real
        # data, and it takes a heavy lock). Instead we create a TEMP table with
        # the same name - temp tables shadow public ones for unqualified names
        # and vanish on rollback - filled using the view's own defining query,
        # restricted to our test chains. Same matching logic, tiny cost.
        cur.execute("SELECT pg_get_viewdef('public.store_product_category_matches'::regclass)")
        viewdef = cur.fetchone()[0].strip().rstrip(";")
        chains_sql = ", ".join(f"'{c}'" for c in TEST_CHAINS)  # constants, safe to inline
        cur.execute(
            "CREATE TEMP TABLE store_product_category_matches AS "
            f"SELECT * FROM ({viewdef}) AS v WHERE v.chain_id IN ({chains_sql})"
        )

    return SimpleNamespace(
        chain_a=CHAIN_A,
        chain_b=CHAIN_B,
        milk=MILK,
        cheese=CHEESE,
        no_product=NO_PRODUCT,
        store_code=STORE_CODE,
        cat_packaged=CAT_PACKAGED,
        cat_fresh=CAT_FRESH,
        tomato_cherry=TOMATO_CHERRY,
        tomato_organic=TOMATO_ORGANIC,
        category_id=category_id,
        sub_tomato=subs[SUB_TOMATO],
        sub_chicken=subs[SUB_CHICKEN],
    )


def _insert_promo(cur, pid, chain_id, store_id, start, end, item_code, discounted, min_qty, description):
    cur.execute(
        "INSERT INTO promotions (chain_id, promotion_id, store_id, description, start_datetime, end_datetime) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (chain_id, pid, store_id, description, start, end),
    )
    cur.execute(
        "INSERT INTO promotion_groups (chain_id, promotion_id, store_id, group_id) VALUES (%s,%s,%s,'G1')",
        (chain_id, pid, store_id),
    )
    cur.execute(
        "INSERT INTO promotion_items (chain_id, promotion_id, store_id, group_id, item_code, discounted_price, min_qty) "
        "VALUES (%s,%s,%s,'G1',%s,%s,%s)",
        (chain_id, pid, store_id, item_code, discounted, min_qty),
    )