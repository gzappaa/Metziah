# These tests intentionally focus on basic repository behavior rather than
# exhaustively testing every update/conflict branch. More advanced behavior
# is covered by the higher-level update_products, update_prices, and
# update_promos integration tests, so duplicating those cases here would
# make the repository suite unnecessarily large and redundant.


import psycopg
import pytest

from models.store import Store

from decimal import Decimal
from database.records import StoreProductRecord, PriceRecord, ProductRecord
from types import SimpleNamespace
from datetime import date
from models.promo import Promotion, PromotionGroup, PromotionItem


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
    get_downloaded_pricefull_files,
    get_latest_downloaded_price_files,
    get_downloaded_promofull_files,
    get_downloaded_unloaded_promo_files,
    upsert_promotions,
    upsert_promotion_groups,
    upsert_promotion_items,
    reconcile_removed_promotions,
    reconcile_removed_promotion_groups,
    reconcile_removed_promotion_items,
    get_promotion_details,
    load_known_barcodes,
    upsert_pharmacy_products,
    upsert_pharmacy_store_products,
    delete_promoted_pharmacy_products,
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

    ensure_chain(conn, chain_id, "Test Chain HE", "Test Chain EN")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT chain_id FROM chains WHERE chain_id = %s",
            (chain_id,),
        )
        assert cur.fetchone()[0] == chain_id


def test_ensure_chain_is_idempotent(conn):
    chain_id = "TEST_CHAIN"

    ensure_chain(conn, chain_id, "Test Chain HE", "Test Chain EN")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM chains WHERE chain_id = %s",
            (chain_id,),
        )
        assert cur.fetchone()[0] == 1


def test_upsert_stores(conn):
    chain_id = "TEST_CHAIN"

    ensure_chain(conn, chain_id, "Test Chain HE", "Test Chain EN")

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
            SELECT chain_id, store_id, item_code, name,
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
        "Test Manufacturer",
        "Israel",
        0,
    )






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
            "SELECT name, manufacturer, manufacturer_country, item_type "
            "FROM products WHERE item_code = %s",
            (record.item_code,),
        )
        assert cur.fetchone() == ("Test Barcode Product", "Acme", "IL", 1)






# ---- file_tracking ----

def _file_record(
    chain_id,
    filename,
    store_id,
    downloaded=False,
    loaded=False,
    file_type="Price",
):
    return {
        "chain_id": chain_id,
        "sub_chain_id": "001",
        "store_id": store_id,
        "source": "TEST",
        "file_type": file_type,
        "filename": filename,
        "file_date": date.today(),
        "downloaded": downloaded,
        "loaded": loaded,
        "file_size": None,
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


def test_get_downloaded_pricefull_files_returns_only_newest_unloaded(
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
                "PriceFull_001.gz",
                store_id,
                downloaded=True,
                loaded=False,
                file_type="PriceFull",
            ),
            _file_record(
                chain_id,
                "PriceFull_002.gz",
                store_id,
                downloaded=False,
                loaded=False,
                file_type="PriceFull",
            ),
            _file_record(
                chain_id,
                "PriceFull_003.gz",
                store_id,
                downloaded=True,
                loaded=False,
                file_type="PriceFull",
            ),
            _file_record(
                chain_id,
                "Price_004.gz",
                store_id,
                downloaded=True,
                loaded=False,
                file_type="Price",
            ),
        ],
    )

    rows = get_downloaded_pricefull_files(conn)

    filenames = {
        row[4]
        for row in rows
        if row[0] == chain_id and row[2] == store_id
    }

    assert filenames == {"PriceFull_003.gz"}


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
    create_store,
):
    chain_id = "TEST_PROMO_CHAIN_001"
    store_id = "TEST_STORE"

    create_store(chain_id, store_id)

    insert_file_tracking(
        conn,
        [
            _file_record(
                chain_id,
                "PromoFull_001.gz",
                store_id,
                downloaded=True,
                loaded=False,
                file_type="PromoFull",
            ),
            _file_record(
                chain_id,
                "Promo_001.gz",
                store_id,
                downloaded=True,
                loaded=False,
                file_type="Promo",
            ),
        ],
    )

    rows = get_downloaded_unloaded_promo_files(
        conn,
    )

    assert not any(
        row[0] == chain_id and row[4] == "Promo_001.gz"
        for row in rows
    )


def test_get_downloaded_unloaded_promo_files_allows_promo_after_promofull_loaded(
    conn,
    create_store,
):
    chain_id = "TEST_PROMO_CHAIN_002"
    store_id = "TEST_STORE"

    create_store(chain_id, store_id)

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

    mark_files_loaded(conn, ["PromoFull_001.gz"])

    rows = get_downloaded_unloaded_promo_files(
        conn,
    )

    assert any(
        row[0] == chain_id and row[4] == "Promo_001.gz"
        for row in rows
    )

    


# ---- promotions / groups / items ----

def _promotion(chain_id, store_id, promotion_id="PROMO_001", description="Test Promo"):
    return Promotion(
        chain_id=chain_id, promotion_id=promotion_id, store_id=store_id,
        description=description, start_datetime=None, end_datetime=None,
        start_hour=None, end_hour=None, promotion_days=None, update_time=None,
        club_id=None, is_gift_item=None, additional_is_coupon=False,
        allow_multiple_discounts=False, redemption_limit=None,
        min_no_of_items_offered=None, additional_restrictions=None, remarks=None,
    )


def _promotion_group(chain_id, store_id, promotion_id="PROMO_GRP", group_id="G1"):
    return PromotionGroup(
        chain_id=chain_id, promotion_id=promotion_id, store_id=store_id,
        group_id=group_id, min_purchase_amount=None, discount_type=None,
    )


def _promotion_item(chain_id, store_id, promotion_id="PROMO_ITEM", group_id="G1", item_code="ITEM_001"):
    return PromotionItem(
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

def test_get_promotion_details_returns_none_when_missing(conn):
    assert get_promotion_details(
        conn,
        "MISSING_CHAIN",
        "MISSING_STORE",
        "MISSING_PROMO",
        "MISSING_GROUP",
        "MISSING_ITEM",
    ) is None

# ---- pharmacy: store_type, pharmacy_products, pharmacy_store_products ----
#
# All item codes used here start with PHARMTEST so the cleanup fixture can
# remove exactly what these tests created, without touching other data.

_PHARM_PREFIX = "PHARMTEST%"


@pytest.fixture
def pharmacy_clean(conn):
    """
    Remove PHARMTEST rows before and after the test.

    Setup deliberately does NOT rollback or commit: fixtures such as
    test_store insert their chain/store rows (uncommitted) before this one
    runs, and the test needs them. Teardown rolls back first, because a
    failed test can leave the transaction aborted, then deletes and commits
    anything that code under test committed (load_files commits).
    """

    def _delete():
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pharmacy_products WHERE item_code LIKE %s",
                (_PHARM_PREFIX,),
            )
            cur.execute(
                "DELETE FROM pharmacy_store_products WHERE item_code LIKE %s",
                (_PHARM_PREFIX,),
            )
            cur.execute(
                "DELETE FROM store_products WHERE item_code LIKE %s",
                (_PHARM_PREFIX,),
            )
            cur.execute(
                "DELETE FROM products WHERE item_code LIKE %s",
                (_PHARM_PREFIX,),
            )

    _delete()

    yield

    conn.rollback()
    _delete()
    conn.commit()


def _pharm_product(item_code, name="Pharm Product"):
    return ProductRecord(
        item_code=item_code,
        name=name,
        manufacturer="Acme",
        manufacturer_country="IL",
        item_type=1,
    )


def _pharm_store_product(chain_id, store_id, item_code, name="Pharm Item"):
    return StoreProductRecord(
        chain_id=chain_id,
        store_id=store_id,
        item_code=item_code,
        name=name,
        manufacturer="Acme",
        manufacturer_country="IL",
        item_type=0,
    )


def _count(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def test_store_type_defaults_to_supermarket(conn, test_store):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT store_type FROM stores WHERE chain_id = %s AND store_id = %s",
            (test_store["chain_id"], test_store["store_id_text"]),
        )
        assert cur.fetchone()[0] == "supermarket"


def test_store_type_rejects_unknown_value(conn, test_store):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE stores SET store_type = 'bogus' "
                "WHERE chain_id = %s AND store_id = %s",
                (test_store["chain_id"], test_store["store_id_text"]),
            )

    conn.rollback()


def test_load_known_barcodes_returns_existing_products(conn, pharmacy_clean):
    upsert_products(conn, [_pharm_product("PHARMTEST_KNOWN_001")])

    known = load_known_barcodes(conn)

    assert "PHARMTEST_KNOWN_001" in known
    assert "PHARMTEST_MISSING_001" not in known


def test_upsert_pharmacy_products_inserts_new(conn, test_store, pharmacy_clean):
    chain_id = test_store["chain_id"]

    written = upsert_pharmacy_products(
        conn,
        chain_id,
        [_pharm_product("PHARMTEST_BC_001", name="שמפו")],
    )

    assert written == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, manufacturer, manufacturer_country, item_type "
            "FROM pharmacy_products WHERE chain_id = %s AND item_code = %s",
            (chain_id, "PHARMTEST_BC_001"),
        )
        assert cur.fetchone() == ("שמפו", "Acme", "IL", 1)


def test_upsert_pharmacy_products_empty_list_is_noop(conn):
    assert upsert_pharmacy_products(conn, "ANY_CHAIN", []) == 0


def test_upsert_pharmacy_products_does_not_touch_products_table(
    conn, test_store, pharmacy_clean,
):
    upsert_pharmacy_products(
        conn,
        test_store["chain_id"],
        [_pharm_product("PHARMTEST_BC_002")],
    )

    assert _count(
        conn,
        "SELECT COUNT(*) FROM products WHERE item_code = %s",
        ("PHARMTEST_BC_002",),
    ) == 0


def test_upsert_pharmacy_products_updates_existing_and_keeps_first_seen(
    conn, test_store, pharmacy_clean,
):
    chain_id = test_store["chain_id"]
    code = "PHARMTEST_BC_003"

    upsert_pharmacy_products(conn, chain_id, [_pharm_product(code, "ישן")])

    # Age the row so last_seen can visibly move forward within one transaction.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE pharmacy_products "
            "SET first_seen = '2020-06-15 12:00+00', "
            "    last_seen  = '2020-06-15 12:00+00' "
            "WHERE chain_id = %s AND item_code = %s",
            (chain_id, code),
        )

    upsert_pharmacy_products(conn, chain_id, [_pharm_product(code, "חדש")])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, first_seen, last_seen FROM pharmacy_products "
            "WHERE chain_id = %s AND item_code = %s",
            (chain_id, code),
        )
        rows = cur.fetchall()

    assert len(rows) == 1
    name, first_seen, last_seen = rows[0]
    assert name == "חדש"
    assert first_seen.year == 2020
    assert last_seen > first_seen


def test_upsert_pharmacy_products_same_barcode_in_two_chains_kept_separately(
    conn, create_store, pharmacy_clean,
):
    create_store("PHARMTEST_CHAIN_A", "1")
    create_store("PHARMTEST_CHAIN_B", "1")

    code = "PHARMTEST_BC_004"

    upsert_pharmacy_products(conn, "PHARMTEST_CHAIN_A", [_pharm_product(code)])
    upsert_pharmacy_products(conn, "PHARMTEST_CHAIN_B", [_pharm_product(code)])

    assert _count(
        conn,
        "SELECT COUNT(*) FROM pharmacy_products WHERE item_code = %s",
        (code,),
    ) == 2


def test_upsert_pharmacy_store_products_inserts_new(
    conn, test_store, pharmacy_clean,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    written = upsert_pharmacy_store_products(
        conn,
        [_pharm_store_product(chain_id, store_id, "PHARMTEST_SP_001", "משחה")],
    )

    assert written == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, manufacturer, manufacturer_country, item_type "
            "FROM pharmacy_store_products "
            "WHERE chain_id = %s AND store_id = %s AND item_code = %s",
            (chain_id, store_id, "PHARMTEST_SP_001"),
        )
        assert cur.fetchone() == ("משחה", "Acme", "IL", 0)


def test_upsert_pharmacy_store_products_empty_list_is_noop(conn):
    assert upsert_pharmacy_store_products(conn, []) == 0


def test_upsert_pharmacy_store_products_does_not_touch_store_products(
    conn, test_store, pharmacy_clean,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]

    upsert_pharmacy_store_products(
        conn,
        [_pharm_store_product(chain_id, store_id, "PHARMTEST_SP_002")],
    )

    assert _count(
        conn,
        "SELECT COUNT(*) FROM store_products WHERE item_code = %s",
        ("PHARMTEST_SP_002",),
    ) == 0


def test_upsert_pharmacy_store_products_updates_existing(
    conn, test_store, pharmacy_clean,
):
    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]
    code = "PHARMTEST_SP_003"

    upsert_pharmacy_store_products(
        conn, [_pharm_store_product(chain_id, store_id, code, "ישן")],
    )
    upsert_pharmacy_store_products(
        conn, [_pharm_store_product(chain_id, store_id, code, "חדש")],
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM pharmacy_store_products "
            "WHERE chain_id = %s AND store_id = %s AND item_code = %s",
            (chain_id, store_id, code),
        )
        rows = cur.fetchall()

    assert rows == [("חדש",)]


def test_upsert_pharmacy_store_products_same_code_in_two_stores_kept_separately(
    conn, create_store, pharmacy_clean,
):
    chain_id = "PHARMTEST_CHAIN_C"
    create_store(chain_id, "1")
    create_store(chain_id, "2")

    code = "PHARMTEST_SP_004"

    upsert_pharmacy_store_products(
        conn,
        [
            _pharm_store_product(chain_id, "1", code),
            _pharm_store_product(chain_id, "2", code),
        ],
    )

    assert _count(
        conn,
        "SELECT COUNT(*) FROM pharmacy_store_products WHERE item_code = %s",
        (code,),
    ) == 2


def test_delete_promoted_pharmacy_products_removes_only_known_barcodes(
    conn, test_store, pharmacy_clean,
):
    chain_id = test_store["chain_id"]

    upsert_products(conn, [_pharm_product("PHARMTEST_PROMOTED_001")])
    upsert_pharmacy_products(
        conn,
        chain_id,
        [
            _pharm_product("PHARMTEST_PROMOTED_001"),
            _pharm_product("PHARMTEST_STILL_PHARMACY_001"),
        ],
    )

    deleted = delete_promoted_pharmacy_products(conn)

    assert deleted >= 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_code FROM pharmacy_products WHERE item_code LIKE %s",
            (_PHARM_PREFIX,),
        )
        remaining = {row[0] for row in cur.fetchall()}

    assert remaining == {"PHARMTEST_STILL_PHARMACY_001"}


def test_delete_promoted_pharmacy_products_noop_when_nothing_promoted(
    conn, test_store, pharmacy_clean,
):
    upsert_pharmacy_products(
        conn,
        test_store["chain_id"],
        [_pharm_product("PHARMTEST_STILL_PHARMACY_002")],
    )

    delete_promoted_pharmacy_products(conn)

    assert _count(
        conn,
        "SELECT COUNT(*) FROM pharmacy_products WHERE item_code = %s",
        ("PHARMTEST_STILL_PHARMACY_002",),
    ) == 1