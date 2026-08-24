
from models.store import Store

from decimal import Decimal
from database.records import StoreProductRecord, PriceRecord, ProductRecord
#  maybe later i will change the naming algorithm
from types import SimpleNamespace
from datetime import date

from database.repository import (
    update_store_subchain,
    ensure_chain,
    upsert_stores,
    upsert_store_products,
    upsert_prices,
    reconcile_removed_items,
    upsert_products,
    insert_file_tracking,
    mark_files_downloaded,
    mark_files_loaded,
    get_latest_downloaded_price_files,
    get_downloaded_promofull_files,
    get_downloaded_unloaded_promo_files,
    upsert_promotions,
    upsert_promotion_groups,
    upsert_promotion_items,
    reconcile_removed_promotions,
    reconcile_removed_promotion_groups,
    reconcile_removed_promotion_items,
)




def test_update_store_subchain(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

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


def test_upsert_store_products_inserts_new_product(conn, test_store):
    record = StoreProductRecord(
        chain_id=test_store["chain_id"],
        store_id=test_store["store_id_text"],
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
                test_store["store_id_text"],
                record.item_code,
            ),
        )
        row = cur.fetchone()

    assert row == (
        record.chain_id,
        test_store["store_id_text"],
        record.item_code,
        "Test Store Product",
        1,
        "Test Manufacturer",
        "Israel",
        0,
    )


def test_upsert_prices_unchanged_is_noop(conn, test_store):
    record = PriceRecord(
        chain_id=test_store["chain_id"],
        store_id=test_store["store_id_text"],
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
                test_store["store_id_text"],
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
                test_store["store_id_text"],
                record.item_code,
            ),
        )
        second_updated_at = cur.fetchone()[0]

    assert second_updated_at == first_updated_at



def test_reconcile_removed_items_only_removes_missing_item(
    conn, test_store
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]
    store_id_int = test_store["store_id_text"]

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
    conn, test_store
):
    record = StoreProductRecord(
        chain_id=test_store["chain_id"],
        store_id=test_store["store_id_text"],
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
                test_store["store_id_text"],
                record.item_code,
            ),
        )
        row = cur.fetchone()

    assert row == ("Original Manufacturer", "IL")


def test_upsert_store_products_name_resolution(conn, test_store):
    record = StoreProductRecord(
        chain_id=test_store["chain_id"],
        store_id=test_store["store_id_text"],
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
                test_store["store_id_text"],
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
                test_store["store_id_text"],
                record.item_code,
            ),
        )
        assert cur.fetchone() == ("Original", 1)


# ---- upsert_products (barcode) ----

def test_upsert_products_inserts_new(conn):
    record = ProductRecord(
        item_code="BARCODE_TEST_001",
        name="Test Barcode Product",
        manufacturer="Acme",
        manufacturer_country="IL",
        item_type=1,
    )

    upsert_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, name_count, manufacturer, manufacturer_country, item_type "
            "FROM products WHERE item_code = %s",
            (record.item_code,),
        )
        assert cur.fetchone() == ("Test Barcode Product", 1, "Acme", "IL", 1)


def test_upsert_products_name_resolution_increments_on_match(conn):
    record = ProductRecord(
        item_code="BARCODE_NAME_001",
        name="Original",
        manufacturer=None,
        manufacturer_country=None,
        item_type=0,
    )

    upsert_products(conn, [record])
    upsert_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, name_count FROM products WHERE item_code = %s",
            (record.item_code,),
        )
        assert cur.fetchone() == ("Original", 2)


def test_upsert_products_fill_only_manufacturer(conn):
    record = ProductRecord(
        item_code="BARCODE_MFR_001",
        name="Test",
        manufacturer="Original Mfr",
        manufacturer_country="IL",
        item_type=0,
    )

    upsert_products(conn, [record])

    record.manufacturer = "Different Mfr"
    record.manufacturer_country = "US"
    upsert_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT manufacturer, manufacturer_country FROM products WHERE item_code = %s",
            (record.item_code,),
        )
        assert cur.fetchone() == ("Original Mfr", "IL")


def test_upsert_products_blank_name_is_true_noop(conn):
    # Blank name never participates in name resolution, and manufacturer
    # is unchanged (fill-only, same value) -- so nothing should update.
    record = ProductRecord(
        item_code="BARCODE_BLANK_001",
        name=None,
        manufacturer="Mfr",
        manufacturer_country="IL",
        item_type=0,
    )
    upsert_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT updated_at FROM products WHERE item_code = %s",
            (record.item_code,),
        )
        first = cur.fetchone()[0]

    upsert_products(conn, [record])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT updated_at FROM products WHERE item_code = %s",
            (record.item_code,),
        )
        second = cur.fetchone()[0]

    assert second == first


# ---- file_tracking ----

def _file_record(
    chain_id,
    filename,
    store_id,
    downloaded=False,
    file_type="Price",
):
    return {
        "chain_id": chain_id,
        "sub_chain_id": "001",
        "store_id": store_id,
        "file_type": file_type,
        "filename": filename,
        "file_date": date(2026, 8, 1),
        "downloaded": downloaded,
    }


def test_insert_file_tracking_empty_list_returns_zero(conn):
    assert insert_file_tracking(conn, []) == 0


def test_insert_file_tracking_inserts_new_row(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    insert_file_tracking(
        conn, [_file_record(chain_id, "Price_TRACK_001.gz", store_id, downloaded=True)]
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT downloaded, loaded FROM file_tracking "
            "WHERE chain_id = %s AND filename = %s",
            (chain_id, "Price_TRACK_001.gz"),
        )
        assert cur.fetchone() == (True, False)


def test_insert_file_tracking_downloaded_flips_false_to_true(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]
    filename = "Price_TRACK_002.gz"

    insert_file_tracking(conn, [_file_record(chain_id, filename, store_id, downloaded=False)])
    insert_file_tracking(conn, [_file_record(chain_id, filename, store_id, downloaded=True)])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT downloaded FROM file_tracking WHERE chain_id = %s AND filename = %s",
            (chain_id, filename),
        )
        assert cur.fetchone()[0] is True


def test_insert_file_tracking_downloaded_never_reverts(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]
    filename = "Price_TRACK_003.gz"

    insert_file_tracking(conn, [_file_record(chain_id, filename, store_id, downloaded=True)])
    insert_file_tracking(conn, [_file_record(chain_id, filename, store_id, downloaded=False)])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT downloaded FROM file_tracking WHERE chain_id = %s AND filename = %s",
            (chain_id, filename),
        )
        assert cur.fetchone()[0] is True


def test_insert_file_tracking_never_touches_loaded(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]
    filename = "Price_TRACK_004.gz"

    insert_file_tracking(conn, [_file_record(chain_id, filename, store_id, downloaded=True)])
    mark_files_loaded(conn, [filename])

    # Simulates a later file_tracking re-scan seeing the same file again.
    insert_file_tracking(conn, [_file_record(chain_id, filename, store_id, downloaded=True)])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT loaded FROM file_tracking WHERE chain_id = %s AND filename = %s",
            (chain_id, filename),
        )
        assert cur.fetchone()[0] is True


def test_mark_files_downloaded_only_flips_undownloaded(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    insert_file_tracking(conn, [
        _file_record(chain_id, "Price_MARK_001.gz", store_id, downloaded=False),
        _file_record(chain_id, "Price_MARK_002.gz", store_id, downloaded=True),
    ])

    updated = mark_files_downloaded(
        conn, ["Price_MARK_001.gz", "Price_MARK_002.gz", "Price_MARK_MISSING.gz"]
    )

    assert updated == 1  # only the false -> true flip counts


def test_mark_files_loaded_only_flips_unloaded(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]
    filename = "Promo_LOAD_001.gz"

    insert_file_tracking(
        conn, [_file_record(chain_id, filename, store_id, downloaded=True, file_type="Promo")]
    )

    assert mark_files_loaded(conn, [filename]) == 1
    assert mark_files_loaded(conn, [filename]) == 0


def test_get_latest_downloaded_price_files_picks_newest_when_nothing_loaded(
    conn,
    test_store,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    filenames = [
        "Price7290661400001-001-097-20000101-040000.gz",
        "Price7290661400001-001-097-20000101-090000.gz",
        "Price7290661400001-001-097-19991231-230000.gz",
    ]

    try:
        insert_file_tracking(conn, [
            _file_record(chain_id, filenames[0], store_id, downloaded=True),
            _file_record(chain_id, filenames[1], store_id, downloaded=True),
            _file_record(chain_id, filenames[2], store_id, downloaded=False),
        ])

        rows = get_latest_downloaded_price_files(conn)
        matching = [r for r in rows if r[2] == store_id]

        assert len(matching) == 1
        assert matching[0][4] == filenames[1]

    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM file_tracking
                WHERE chain_id = %s
                  AND store_id = %s
                  AND filename = ANY(%s)
                """,
                (chain_id, store_id, filenames),
            )


def test_get_latest_downloaded_price_files_picks_newest_after_latest_loaded(
    conn,
    test_store,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    filenames = [
        "Price7290661400001-001-097-20000101-040000.gz",
        "Price7290661400001-001-097-20000101-050000.gz",
        "Price7290661400001-001-097-20000101-090000.gz",
    ]

    try:
        insert_file_tracking(conn, [
            _file_record(chain_id, filenames[0], store_id, downloaded=True),
            _file_record(chain_id, filenames[1], store_id, downloaded=True),
            _file_record(chain_id, filenames[2], store_id, downloaded=True),
        ])
        mark_files_loaded(conn, [filenames[0]])

        rows = get_latest_downloaded_price_files(conn)
        matching = [r for r in rows if r[2] == store_id]

        assert len(matching) == 1
        assert matching[0][4] == filenames[2]

    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM file_tracking
                WHERE chain_id = %s
                  AND store_id = %s
                  AND filename = ANY(%s)
                """,
                (chain_id, store_id, filenames),
            )

def test_get_latest_downloaded_price_files_never_loads_older_than_latest_loaded(
    conn,
    test_store,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    filenames = [
        "Price7290661400001-001-097-20000102-040000.gz",
        "Price7290661400001-001-097-20000102-060000.gz",
        "Price7290661400001-001-097-20000102-090000.gz",
    ]

    try:
        insert_file_tracking(conn, [
            _file_record(chain_id, filenames[0], store_id, downloaded=True),
            _file_record(chain_id, filenames[1], store_id, downloaded=True),
            _file_record(chain_id, filenames[2], store_id, downloaded=True),
        ])
        mark_files_loaded(conn, [filenames[2]])

        rows = get_latest_downloaded_price_files(conn)
        matching = [r for r in rows if r[2] == store_id]

        assert matching == []

    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM file_tracking
                WHERE chain_id = %s
                  AND store_id = %s
                  AND filename = ANY(%s)
                """,
                (chain_id, store_id, filenames),
            )


def test_get_downloaded_promofull_files_filters_type_downloaded_loaded(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    insert_file_tracking(conn, [
        _file_record(chain_id, "PromoFull_PF_001.gz", store_id, downloaded=True, file_type="PromoFull"),
        _file_record(chain_id, "PromoFull_PF_002.gz", store_id, downloaded=False, file_type="PromoFull"),
        _file_record(chain_id, "Promo_P_003.gz", store_id, downloaded=True, file_type="Promo"),
    ])

    rows = get_downloaded_promofull_files(conn)
    filenames = {r[4] for r in rows if r[2] == store_id}

    assert filenames == {"PromoFull_PF_001.gz"}


def test_get_downloaded_unloaded_promo_files_requires_loaded_promofull(
    conn,
    test_store,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    insert_file_tracking(
        conn,
        [
            _file_record(
                chain_id,
                "PromoFull_001.gz",
                store_id,
                downloaded=True,
                file_type="PromoFull",
            ),
            _file_record(
                chain_id,
                "Promo_001.gz",
                store_id,
                downloaded=True,
                file_type="Promo",
            ),
        ],
    )

    # PromoFull exists and was downloaded, but was NOT loaded.
    rows = get_downloaded_unloaded_promo_files(conn)

    assert rows == []


def test_get_downloaded_unloaded_promo_files_allows_promo_after_promofull_loaded(
    conn,
    test_store,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    insert_file_tracking(
        conn,
        [
            _file_record(
                chain_id,
                "PromoFull_001.gz",
                store_id,
                downloaded=True,
                file_type="PromoFull",
            ),
            _file_record(
                chain_id,
                "Promo_001.gz",
                store_id,
                downloaded=True,
                file_type="Promo",
            ),
        ],
    )

    mark_files_loaded(
        conn,
        ["PromoFull_001.gz"],
    )

    rows = get_downloaded_unloaded_promo_files(conn)

    filenames = {r[4] for r in rows}

    assert filenames == {"Promo_001.gz"}

    

# ---- promotions / groups / items ----
# NOTE: models/promo.py wasn't in what I've seen, so these use SimpleNamespace
# matching the attributes repository.py actually reads. Swap in the real
# Promotion/PromotionGroup/PromotionItem classes if their field names differ.

def _promotion(chain_id, store_id, promotion_id="PROMO_001", description="Test Promo"):
    return SimpleNamespace(
        chain_id=chain_id, promotion_id=promotion_id, store_id=store_id,
        description=description, start_datetime=None, end_datetime=None,
        start_hour=None, end_hour=None, promotion_days=None, update_time=None,
        club_id=None, is_gift_item=False, additional_is_coupon=False,
        allow_multiple_discounts=False, redemption_limit=None,
        min_no_of_items_offered=None, additional_restrictions=None, remarks=None,
    )


def _promotion_group(chain_id, store_id, promotion_id="PROMO_GRP", group_id="G1"):
    return SimpleNamespace(
        chain_id=chain_id, promotion_id=promotion_id, store_id=store_id,
        group_id=group_id, min_purchase_amount=None, discount_type=None,
    )


def _promotion_item(chain_id, store_id, promotion_id="PROMO_ITEM", group_id="G1", item_code="ITEM_001"):
    return SimpleNamespace(
        chain_id=chain_id, promotion_id=promotion_id, store_id=store_id,
        group_id=group_id, item_code=item_code, item_type=0, reward_type=0,
        min_qty=None, max_qty=None, discount_rate=None, discounted_price=None,
        discounted_price_per_mida=None, is_weighted=False,
    )


def test_upsert_promotions_inserts_new(conn, test_store):
    chain_id, store_id = test_store["chain_id"], test_store["store_id_text"]
    promo = _promotion(chain_id, store_id)

    upsert_promotions(conn, [promo])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT description FROM promotions "
            "WHERE chain_id=%s AND promotion_id=%s AND store_id=%s",
            (chain_id, promo.promotion_id, store_id),
        )
        assert cur.fetchone()[0] == "Test Promo"


def test_upsert_promotions_noop_when_unchanged(conn, test_store):
    chain_id, store_id = test_store["chain_id"], test_store["store_id_text"]
    promo = _promotion(chain_id, store_id, promotion_id="PROMO_NOOP")

    upsert_promotions(conn, [promo])
    with conn.cursor() as cur:
        cur.execute(
            "SELECT updated_at FROM promotions "
            "WHERE chain_id=%s AND promotion_id=%s AND store_id=%s",
            (chain_id, promo.promotion_id, store_id),
        )
        first = cur.fetchone()[0]

    upsert_promotions(conn, [promo])
    with conn.cursor() as cur:
        cur.execute(
            "SELECT updated_at FROM promotions "
            "WHERE chain_id=%s AND promotion_id=%s AND store_id=%s",
            (chain_id, promo.promotion_id, store_id),
        )
        second = cur.fetchone()[0]

    assert second == first


def test_upsert_promotions_updates_changed_field(conn, test_store):
    chain_id, store_id = test_store["chain_id"], test_store["store_id_text"]
    promo = _promotion(chain_id, store_id, promotion_id="PROMO_CHANGE")

    upsert_promotions(conn, [promo])
    promo.description = "Updated description"
    upsert_promotions(conn, [promo])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT description FROM promotions "
            "WHERE chain_id=%s AND promotion_id=%s AND store_id=%s",
            (chain_id, promo.promotion_id, store_id),
        )
        assert cur.fetchone()[0] == "Updated description"


def test_upsert_promotion_groups_inserts_and_updates(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    promotion_id = "PROMO_GRP"

    upsert_promotions(
        conn,
        [
            _promotion(
                chain_id,
                store_id,
                promotion_id=promotion_id,
            )
        ],
    )

    group = _promotion_group(
        chain_id,
        store_id,
        promotion_id=promotion_id,
    )

    upsert_promotion_groups(conn, [group])

    group.discount_type = "percentage"

    upsert_promotion_groups(conn, [group])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT discount_type
            FROM promotion_groups
            WHERE chain_id = %s
              AND promotion_id = %s
              AND store_id = %s
              AND group_id = %s
            """,
            (
                chain_id,
                promotion_id,
                store_id,
                group.group_id,
            ),
        )

        assert cur.fetchone()[0] == "percentage"


def test_upsert_promotion_items_inserts_and_updates(conn, test_store):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    promotion_id = "PROMO_ITEM"

    upsert_promotions(
        conn,
        [
            _promotion(
                chain_id,
                store_id,
                promotion_id=promotion_id,
            )
        ],
    )

    upsert_promotion_groups(
        conn,
        [
            _promotion_group(
                chain_id,
                store_id,
                promotion_id=promotion_id,
                group_id="G1",
            )
        ],
    )

    item = _promotion_item(
        chain_id,
        store_id,
        promotion_id=promotion_id,
        group_id="G1",
    )

    upsert_promotion_items(conn, [item])

    item.discounted_price = Decimal("9.90")

    upsert_promotion_items(conn, [item])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT discounted_price
            FROM promotion_items
            WHERE chain_id = %s
              AND promotion_id = %s
              AND store_id = %s
              AND group_id = %s
              AND item_code = %s
            """,
            (
                chain_id,
                promotion_id,
                store_id,
                item.group_id,
                item.item_code,
            ),
        )

        assert cur.fetchone()[0] == Decimal("9.90")


def test_reconcile_removed_promotion_items_only_removes_missing(conn, test_store):
    chain_id, store_id = test_store["chain_id"], test_store["store_id_text"]
    promo_id = "PROMO_RECON"

    upsert_promotions(conn, [_promotion(chain_id, store_id, promotion_id=promo_id)])
    upsert_promotion_groups(conn, [_promotion_group(chain_id, store_id, promotion_id=promo_id, group_id="G1")])
    upsert_promotion_items(conn, [
        _promotion_item(chain_id, store_id, promotion_id=promo_id, group_id="G1", item_code="KEEP"),
        _promotion_item(chain_id, store_id, promotion_id=promo_id, group_id="G1", item_code="REMOVE"),
    ])

    deleted = reconcile_removed_promotion_items(
        conn, chain_id, store_id, current_keys={(promo_id, "G1", "KEEP")}
    )

    assert deleted == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_code FROM promotion_items "
            "WHERE chain_id=%s AND promotion_id=%s AND store_id=%s",
            (chain_id, promo_id, store_id),
        )
        assert {row[0] for row in cur.fetchall()} == {"KEEP"}


def test_reconcile_removed_promotion_items_cascades_empty_group(conn, test_store):
    chain_id, store_id = test_store["chain_id"], test_store["store_id_text"]
    promo_id = "PROMO_EMPTYGRP"

    upsert_promotions(conn, [_promotion(chain_id, store_id, promotion_id=promo_id)])
    upsert_promotion_groups(conn, [_promotion_group(chain_id, store_id, promotion_id=promo_id, group_id="G1")])
    upsert_promotion_items(conn, [
        _promotion_item(chain_id, store_id, promotion_id=promo_id, group_id="G1", item_code="ONLY")
    ])

    reconcile_removed_promotion_items(conn, chain_id, store_id, current_keys=set())

    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM promotion_groups "
            "WHERE chain_id=%s AND promotion_id=%s AND store_id=%s AND group_id=%s",
            (chain_id, promo_id, store_id, "G1"),
        )
        assert cur.fetchone() is None


def test_reconcile_removed_promotions_only_removes_missing(conn, test_store):
    chain_id, store_id = test_store["chain_id"], test_store["store_id_text"]

    upsert_promotions(conn, [
        _promotion(chain_id, store_id, promotion_id="PROMO_KEEP"),
        _promotion(chain_id, store_id, promotion_id="PROMO_REMOVE"),
    ])

    deleted = reconcile_removed_promotions(
        conn, chain_id, store_id, promotion_ids_in_file={"PROMO_KEEP"}
    )

    assert deleted == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM promotions WHERE chain_id=%s AND store_id=%s AND promotion_id=%s",
            (chain_id, store_id, "PROMO_REMOVE"),
        )
        assert cur.fetchone() is None


def test_reconcile_removed_promotion_groups_only_removes_missing(conn, test_store):
    chain_id, store_id = test_store["chain_id"], test_store["store_id_text"]
    promo_id = "PROMO_GRPRECON"

    upsert_promotions(conn, [_promotion(chain_id, store_id, promotion_id=promo_id)])
    upsert_promotion_groups(conn, [
        _promotion_group(chain_id, store_id, promotion_id=promo_id, group_id="KEEP"),
        _promotion_group(chain_id, store_id, promotion_id=promo_id, group_id="REMOVE"),
    ])

    deleted = reconcile_removed_promotion_groups(
        conn, chain_id, store_id, current_keys={(promo_id, "KEEP")}
    )

    assert deleted == 1