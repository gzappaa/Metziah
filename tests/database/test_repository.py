
import pytest
from models.store import Store
from database.repository import (
    update_store_subchain,
    ensure_chain,
    upsert_stores,
    upsert_store_products,
    upsert_prices,
    reconcile_removed_items,
)
from decimal import Decimal
from database.records import StoreProductRecord, PriceRecord
#  maybe later i will change the naming algorithm

from database.repository import (
    _resolve_fill_only,
    _resolve_name,
    get_store_id,
)


def test_resolve_name_blank_incoming():
    assert _resolve_name("Original", 3, "") == ("Original", 3)
    assert _resolve_name("Original", 3, None) == ("Original", 3)


def test_resolve_name_matching_incoming():
    assert _resolve_name("Original", 3, "Original") == ("Original", 4)


def test_resolve_name_different_incoming():
    assert _resolve_name("Original", 3, "New") == ("Original", 2)


def test_resolve_name_switches_when_count_reaches_zero():
    assert _resolve_name("Original", 1, "New") == ("New", 1)


def test_resolve_name_empty_existing():
    assert _resolve_name(None, 0, "New") == ("New", 1)


def test_resolve_fill_only_keeps_existing_value():
    assert _resolve_fill_only("Original", "New") == "Original"


def test_resolve_fill_only_accepts_incoming_when_empty():
    assert _resolve_fill_only(None, "New") == "New"


def test_resolve_fill_only_ignores_blank_incoming():
    assert _resolve_fill_only("Original", "") == "Original"
    assert _resolve_fill_only(None, "") is None





def test_get_store_id(conn, real_store):
    result = get_store_id(
        conn,
        real_store["chain_id"],
        real_store["store_id_text"],
    )

    assert result == real_store["store_id_int"]


def test_get_store_id_missing_store(conn):

    with pytest.raises(KeyError, match="Store not found"):
        get_store_id(
            conn,
            "7290661400001",
            "999999",
        )


def test_update_store_subchain(conn, real_store):
    chain_id = real_store["chain_id"]
    store_id = real_store["store_id_text"]

    update_store_subchain(
        conn,
        chain_id,
        store_id,
        "TEST_SUBCHAIN",
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sub_chain_id
            FROM stores
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )
        assert cur.fetchone()[0] == "TEST_SUBCHAIN"


def test_ensure_chain(conn):
    chain_id = "TEST_CHAIN"

    ensure_chain(conn, chain_id)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT chain_id FROM chains WHERE chain_id = %s",
            (chain_id,),
        )
        assert cur.fetchone()[0] == chain_id


def test_ensure_chain_is_idempotent(conn):
    chain_id = "TEST_CHAIN"

    ensure_chain(conn, chain_id)
    ensure_chain(conn, chain_id)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM chains WHERE chain_id = %s",
            (chain_id,),
        )
        assert cur.fetchone()[0] == 1


def test_upsert_stores(conn):
    chain_id = "TEST_CHAIN"

    ensure_chain(conn, chain_id)

    store = Store(
        chain_id=chain_id,
        store_id="TEST_STORE",
        name="Test Store",
        address="",
        city="",
        zip_code="",
        latitude=32.1,
        longitude=34.8,
    )

    upsert_stores(conn, [store])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT store_name, address, city, zip_code, latitude, longitude
            FROM stores
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, "TEST_STORE"),
        )
        row = cur.fetchone()

    assert row == (
        "Test Store",
        None,
        None,
        None,
        Decimal("32.1"),
        Decimal("34.8"),
    )


def test_upsert_store_products_inserts_new_product(conn, real_store):
    record = StoreProductRecord(
        chain_id=real_store["chain_id"],
        store_id=real_store["store_id_text"],
        item_code="INTERNAL_TEST_001",
        name="Test Store Product",
        manufacturer="Test Manufacturer",
        manufacturer_country="Israel",
        item_type=0,
    )

    upsert_store_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chain_id, store_id, item_code, name, name_count,
                   manufacturer, manufacturer_country, item_type
            FROM store_products
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                record.chain_id,
                real_store["store_id_int"],
                record.item_code,
            ),
        )
        row = cur.fetchone()

    assert row == (
        record.chain_id,
        real_store["store_id_int"],
        record.item_code,
        "Test Store Product",
        1,
        "Test Manufacturer",
        "Israel",
        0,
    )


def test_upsert_prices_unchanged_is_noop(conn, real_store):
    record = PriceRecord(
        chain_id=real_store["chain_id"],
        store_id=real_store["store_id_text"],
        item_code="NOOP_TEST_001",
        price=Decimal("10.00"),
        unit_price=Decimal("10.00"),
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

    upsert_prices(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT updated_at
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                record.chain_id,
                real_store["store_id_int"],
                record.item_code,
            ),
        )
        first_updated_at = cur.fetchone()[0]

    upsert_prices(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT updated_at
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                record.chain_id,
                real_store["store_id_int"],
                record.item_code,
            ),
        )
        second_updated_at = cur.fetchone()[0]

    assert second_updated_at == first_updated_at



def test_reconcile_removed_items_only_removes_missing_item(
    conn, real_store
):
    chain_id = real_store["chain_id"]
    store_id = real_store["store_id_text"]
    store_id_int = real_store["store_id_int"]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT item_code
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id_int),
        )
        existing_items = {row[0] for row in cur.fetchall()}

    record = PriceRecord(
        chain_id=chain_id,
        store_id=store_id,
        item_code="REMOVE_TEST_001",
        price=Decimal("10.00"),
        unit_price=Decimal("10.00"),
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

    upsert_prices(conn, [record])

    deleted = reconcile_removed_items(
        conn,
        chain_id,
        store_id,
        item_codes_in_file=existing_items,
    )

    assert deleted == 1

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (chain_id, store_id_int, record.item_code),
        )
        assert cur.fetchone() is None


def test_upsert_store_products_fill_only_manufacturer(
    conn, real_store
):
    record = StoreProductRecord(
        chain_id=real_store["chain_id"],
        store_id=real_store["store_id_text"],
        item_code="INTERNAL_MFR_TEST",
        name="Test Product",
        manufacturer="Original Manufacturer",
        manufacturer_country="IL",
        item_type=0,
    )

    upsert_store_products(conn, [record])

    record.manufacturer = "Different Manufacturer"
    record.manufacturer_country = "US"

    upsert_store_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT manufacturer, manufacturer_country
            FROM store_products
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                record.chain_id,
                real_store["store_id_int"],
                record.item_code,
            ),
        )
        row = cur.fetchone()

    assert row == ("Original Manufacturer", "IL")


def test_upsert_store_products_name_resolution(conn, real_store):
    record = StoreProductRecord(
        chain_id=real_store["chain_id"],
        store_id=real_store["store_id_text"],
        item_code="INTERNAL_NAME_TEST",
        name="Original",
        manufacturer=None,
        manufacturer_country=None,
        item_type=0,
    )

    upsert_store_products(conn, [record])

    # Same name -> count increases
    upsert_store_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, name_count
            FROM store_products
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                record.chain_id,
                real_store["store_id_int"],
                record.item_code,
            ),
        )
        assert cur.fetchone() == ("Original", 2)

    # Different name -> count decreases, name remains
    record.name = "New"

    upsert_store_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, name_count
            FROM store_products
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                record.chain_id,
                real_store["store_id_int"],
                record.item_code,
            ),
        )
        assert cur.fetchone() == ("Original", 1)