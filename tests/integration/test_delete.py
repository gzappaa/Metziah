import pytest

from utils.processing.delete_suspicious_products import (
    delete_products,
    find_products_to_delete,
)

CHAIN_ID = "9999999999999"
STORE_1 = "DEL_STORE_1"
STORE_2 = "DEL_STORE_2"

# --- products that MUST be deleted (severity "delete" / "ultra_high") --------
TRASH_NULL_NAME = "TEST-TRASH-NULL-NAME"
TRASH_BLANK_NAME = "TEST-TRASH-BLANK-NAME"
TRASH_ONCE_ZERO_NAMED = "TEST-TRASH-ONCE-ZERO"

TRASH = [TRASH_NULL_NAME, TRASH_BLANK_NAME, TRASH_ONCE_ZERO_NAMED]

# --- products that must SURVIVE ----------------------------------------------
KEEP_GOOD = "TEST-KEEP-GOOD"
KEEP_ALL_ZERO = "TEST-KEEP-ALL-ZERO"
KEEP_MIXED_PRICES = "TEST-KEEP-MIXED"
KEEP_PLACEHOLDER = "TEST-KEEP-PLACEHOLDER"
KEEP_NULL_PRICES = "TEST-KEEP-NULL-PRICES"
KEEP_UNUSED = "TEST-KEEP-UNUSED"
KEEP_PHARMACY_ONLY = "TEST-KEEP-PHARMACY-ONLY"

KEEP = [
    KEEP_GOOD,
    KEEP_ALL_ZERO,
    KEEP_MIXED_PRICES,
    KEEP_PLACEHOLDER,
    KEEP_NULL_PRICES,
    KEEP_UNUSED,
    KEEP_PHARMACY_ONLY,
]

ALL_CODES = TRASH + KEEP


def _insert_product(cur, item_code, name):
    cur.execute(
        "INSERT INTO products (item_code, name) VALUES (%s, %s)",
        (item_code, name),
    )


def _insert_price(cur, store_id, item_code, price):
    cur.execute(
        """
        INSERT INTO prices (chain_id, store_id, item_code, price)
        VALUES (%s, %s, %s, %s)
        """,
        (CHAIN_ID, store_id, item_code, price),
    )


def _count(conn, table, codes):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE item_code = ANY(%s)",
            (list(codes),),
        )
        return cur.fetchone()[0]


@pytest.fixture
def seeded(conn, create_store, test_price_partitions, test_promo_partitions):
    """
    Seed trash + good products with dependent rows.

    Fixture order matters: the partition fixtures commit and later DROP their
    tables, so this fixture must be set up AFTER them (so it is torn down
    BEFORE them) and roll back first. Otherwise their conn.commit() would
    persist the test rows.
    """
    create_store(CHAIN_ID, STORE_1)
    create_store(CHAIN_ID, STORE_2)

    with conn.cursor() as cur:
        # ---- trash ----
        _insert_product(cur, TRASH_NULL_NAME, None)
        _insert_price(cur, STORE_1, TRASH_NULL_NAME, 0)

        _insert_product(cur, TRASH_BLANK_NAME, "   ")
        _insert_price(cur, STORE_1, TRASH_BLANK_NAME, 0)

        _insert_product(cur, TRASH_ONCE_ZERO_NAMED, "Named but zero once")
        _insert_price(cur, STORE_1, TRASH_ONCE_ZERO_NAMED, 0)

        # ---- keepers ----
        _insert_product(cur, KEEP_GOOD, "Milk 3% 1L")
        _insert_price(cur, STORE_1, KEEP_GOOD, 6.90)
        _insert_price(cur, STORE_2, KEEP_GOOD, 7.10)

        _insert_product(cur, KEEP_ALL_ZERO, "Ghost Product")
        _insert_price(cur, STORE_1, KEEP_ALL_ZERO, 0)
        _insert_price(cur, STORE_2, KEEP_ALL_ZERO, 0)

        _insert_product(cur, KEEP_MIXED_PRICES, "Mixed price product")
        _insert_price(cur, STORE_1, KEEP_MIXED_PRICES, 0)
        _insert_price(cur, STORE_2, KEEP_MIXED_PRICES, 5.00)

        _insert_product(cur, KEEP_PLACEHOLDER, "לא ידוע")
        _insert_price(cur, STORE_1, KEEP_PLACEHOLDER, 3.00)
        _insert_price(cur, STORE_2, KEEP_PLACEHOLDER, 3.20)

        _insert_product(cur, KEEP_NULL_PRICES, "Null price product")
        _insert_price(cur, STORE_1, KEEP_NULL_PRICES, None)
        _insert_price(cur, STORE_2, KEEP_NULL_PRICES, None)

        _insert_product(cur, KEEP_UNUSED, "Unused product")

        # Pharmacy-only barcode: exists in both catalogs, but has no prices
        # or promotions. Its pharmacy record must count as usage.
        _insert_product(cur, KEEP_PHARMACY_ONLY, "Pharmacy-only barcode")
        cur.execute(
            """
            INSERT INTO pharmacy_products (chain_id, item_code, name)
            VALUES (%s, %s, %s)
            """,
            (CHAIN_ID, KEEP_PHARMACY_ONLY, "Pharmacy-only barcode"),
        )

        # ---- dependents: store_products ----
        for code in (TRASH_ONCE_ZERO_NAMED, KEEP_GOOD):
            cur.execute(
                """
                INSERT INTO store_products (chain_id, store_id, item_code, name)
                VALUES (%s, %s, %s, %s)
                """,
                (CHAIN_ID, STORE_1, code, "store-level copy"),
            )

        # ---- dependents: promotion -> group -> items ----
        cur.execute(
            """
            INSERT INTO promotions (chain_id, promotion_id, store_id)
            VALUES (%s, 'PROMO1', %s)
            """,
            (CHAIN_ID, STORE_1),
        )
        cur.execute(
            """
            INSERT INTO promotion_groups (chain_id, promotion_id, store_id, group_id)
            VALUES (%s, 'PROMO1', %s, 'G1')
            """,
            (CHAIN_ID, STORE_1),
        )
        for code in (TRASH_ONCE_ZERO_NAMED, KEEP_GOOD):
            cur.execute(
                """
                INSERT INTO promotion_items
                    (chain_id, promotion_id, store_id, group_id, item_code)
                VALUES (%s, 'PROMO1', %s, 'G1', %s)
                """,
                (CHAIN_ID, STORE_1, code),
            )

    yield

    conn.rollback()


def test_seed_sanity(conn, seeded):
    assert _count(conn, "products", ALL_CODES) == len(ALL_CODES)


def test_find_flags_only_trash(conn, seeded):
    found = find_products_to_delete(conn, ALL_CODES)

    assert set(found) == set(TRASH)


def test_pharmacy_product_is_not_deleted(conn, seeded):
    found = find_products_to_delete(conn, [KEEP_PHARMACY_ONLY])

    assert KEEP_PHARMACY_ONLY not in found


def test_delete_removes_trash_and_dependents(conn, seeded):
    # Sanity: dependents exist before deletion.
    assert _count(conn, "prices", TRASH) == 3
    assert _count(conn, "store_products", [TRASH_ONCE_ZERO_NAMED]) == 1
    assert _count(conn, "promotion_items", [TRASH_ONCE_ZERO_NAMED]) == 1

    item_codes = find_products_to_delete(conn, ALL_CODES)
    deleted = delete_products(conn, item_codes)

    assert deleted == len(TRASH)

    # Trash and all of its dependents are gone.
    assert _count(conn, "products", TRASH) == 0
    assert _count(conn, "prices", TRASH) == 0
    assert _count(conn, "store_products", TRASH) == 0
    assert _count(conn, "promotion_items", TRASH) == 0

    # Keepers and their dependents are untouched.
    assert _count(conn, "products", KEEP) == len(KEEP)
    assert _count(conn, "prices", KEEP) == 10
    assert _count(conn, "store_products", [KEEP_GOOD]) == 1
    assert _count(conn, "promotion_items", [KEEP_GOOD]) == 1
    assert _count(conn, "pharmacy_products", [KEEP_PHARMACY_ONLY]) == 1


def test_delete_with_empty_list_is_noop(conn, seeded):
    assert delete_products(conn, []) == 0
    assert _count(conn, "products", ALL_CODES) == len(ALL_CODES)


def test_second_run_finds_nothing_new(conn, seeded):
    delete_products(conn, find_products_to_delete(conn, ALL_CODES))

    assert find_products_to_delete(conn, ALL_CODES) == []