# tests/integration/test_full_lifecycle.py
from decimal import Decimal

from database.records import PriceRecord, ProductRecord
from database.repository import (
    upsert_products,
    upsert_prices,
    reconcile_removed_items,
)


def _get_product(conn, item_code):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, name_count, manufacturer, manufacturer_country "
            "FROM products WHERE item_code = %s",
            (item_code,),
        )
        return cur.fetchone()


def _get_price(conn, chain_id, store_id_int, item_code):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT price, unit_price FROM prices "
            "WHERE chain_id = %s AND store_id = %s AND item_code = %s",
            (chain_id, store_id_int, item_code),
        )
        return cur.fetchone()


def test_name_switches_when_votes_flip(conn, test_store):
    item_code = "9999999999995"
    upsert_products(conn, [ProductRecord(
        item_code=item_code, name="Original Name",
        manufacturer=None, manufacturer_country=None, item_type=1,
    )])
    # name_count == 1 here

    upsert_products(conn, [ProductRecord(
        item_code=item_code, name="New Name",
        manufacturer=None, manufacturer_country=None, item_type=1,
    )])
    name, name_count, _, _ = _get_product(conn, item_code)
    assert name == "New Name"
    assert name_count == 1




def test_full_item_lifecycle(conn, test_store):
    """
    Add -> change price -> fill manufacturer -> try to overwrite it ->
    change name -> remove. Real repository functions, real DB writes,
    never committed -- conn's rollback-on-teardown wipes it clean.
    """
    chain_id = test_store["chain_id"]
    store_id_text = test_store["store_id_text"]
    store_id_int = test_store["store_id_text"]
    item_code = "9999999999996"  # 13-digit -> routed to products, not store_products

    def make_price(price):
        return PriceRecord(
            chain_id=chain_id,
            store_id=store_id_text,
            item_code=item_code,
            price=Decimal(price),
            unit_price=Decimal(price),
            quantity=Decimal("1"),
            unit_qty="יחידה",
            unit_measure="",
            weighted=False,
            package_quantity=1,
            allow_discount=True,
            status="active",
            price_update_time=None,
            last_sale_datetime=None,
        )

    # --- 1. ADD ---
    upsert_products(conn, [ProductRecord(
        item_code=item_code, name="Original Name",
        manufacturer=None, manufacturer_country=None, item_type=1,
    )])
    upsert_prices(conn, [make_price("10.00")])

    name, name_count, manufacturer, country = _get_product(conn, item_code)
    assert name == "Original Name"
    assert name_count == 1
    assert manufacturer is None

    price, unit_price = _get_price(conn, chain_id, store_id_int, item_code)
    assert price == Decimal("10.00")

    # --- 2. PRICE CHANGE ---
    upsert_prices(conn, [make_price("12.00")])
    price, unit_price = _get_price(conn, chain_id, store_id_int, item_code)
    assert price == Decimal("12.00")

    # --- 3. METADATA: blank manufacturer gets filled ---
    upsert_products(conn, [ProductRecord(
        item_code=item_code, name="Original Name",
        manufacturer="Acme", manufacturer_country="IL", item_type=1,
    )])
    _, _, manufacturer, country = _get_product(conn, item_code)
    assert manufacturer == "Acme"
    assert country == "IL"

    # --- 4. METADATA: filled manufacturer must NOT be overwritten ---
    upsert_products(conn, [ProductRecord(
        item_code=item_code, name="Original Name",
        manufacturer="SomeoneElse", manufacturer_country="US", item_type=1,
    )])
    _, _, manufacturer, country = _get_product(conn, item_code)
    assert manufacturer == "Acme"   # unchanged
    assert country == "IL"          # unchanged


    # --- 5. REMOVE ---
    deleted = reconcile_removed_items(conn, chain_id, store_id_text, item_codes_in_file=set())
    assert deleted >= 1

    assert _get_price(conn, chain_id, store_id_int, item_code) is None

    # reconcile_removed_items only touches prices, not products --
    # confirms the module docstring's claim.
    name, name_count, _, _ = _get_product(conn, item_code)
    assert name == "Original Name"


