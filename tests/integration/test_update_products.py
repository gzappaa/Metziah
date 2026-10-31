from decimal import Decimal
from types import SimpleNamespace

import pytest

from database.records import ProductRecord
from database.repository import upsert_products
from parsers.xml import StoreXmlParser
from utils.products.update_products import load_files, discover_new_products
from utils.resolve_canonical_name import resolve_canonical_name


# Valid GTIN-13 required to exercise the products/canonical-name path.

VALID_BARCODE = "4006381333931"
DISCOVER_BARCODE = "4006381333948"
NEW_BARCODE = "4006381333943"

def _fake_product(item_code, name, chain_id, store_id, manufacturer=None,
                   manufacturer_country=None):
    return SimpleNamespace(
        item_code=item_code, name=name, manufacturer=manufacturer,
        manufacturer_country=manufacturer_country, item_type=1,
        chain_id=chain_id, store_id=store_id,
        price=Decimal("5.00"), unit_price=Decimal("5.00"),
        quantity=Decimal("1"), unit_qty="יחידה", unit_measure="",
        weighted=False, package_quantity=1, allow_discount=True,
        status="active", price_update_time=None, last_sale_datetime=None,
    )


def _product_row(conn, item_code):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, manufacturer, manufacturer_country "
            "FROM products WHERE item_code = %s",
            (item_code,),
        )
        return cur.fetchone()


def _write_and_patch(monkeypatch, tmp_path, files_products: dict):
    """
    files_products: {relative_path_str: [fake_product, ...]}
    Writes a placeholder file at each path and monkeypatches the parser to
    dispatch by filename, so update_products.load_files() runs for real
    except for XML parsing itself.
    """
    filepaths = []
    by_name = {}

    for rel_path, products in files_products.items():
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"<Root/>")
        filepaths.append(path)
        by_name[path.name] = products

    def fake_parse_price_file(self, xml_content):
        return by_name[xml_content.decode()]

    monkeypatch.setattr(
        StoreXmlParser, "parse_price_file", fake_parse_price_file,
    )
    monkeypatch.setattr(
        "utils.products.update_products.iter_xml_from_path",
        lambda path: [path.name.encode()],
    )

    return filepaths


def test_canonical_name_chosen_from_multiple_chains(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
):
    """
    Two different chains observe the same barcode with two different raw
    names. resolve_canonical_name() is the production oracle for which one
    wins (its own ranking logic is tested separately) -- this test only
    verifies update_products.load_files() aggregates observations across
    files/chains and calls it correctly.
    """
    create_store("9999999999999", "1")
    create_store("8888888888888", "1")

    name_a = "** קוקה קולה זירו בק"
    name_b = "משקה קוקה קולה זירו 1.5 ליטר"

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(VALID_BARCODE, name_a, "9999999999999", "001"),
            ],
            "8888888888888/1/pricesfull/PriceFull8888888888888-001-001-20260101-000000.xml": [
                _fake_product(VALID_BARCODE, name_b, "8888888888888", "001"),
            ],
        },
    )

    expected_name = resolve_canonical_name({
        name_a: {"9999999999999": 1},
        name_b: {"8888888888888": 1},
    })

    load_files(conn, filepaths, tmp_path)

    name, _, _ = _product_row(conn, VALID_BARCODE)
    assert name == expected_name


def test_all_junk_names_fall_back_to_first_seen_raw_name(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
):
    create_store("9999999999999", "1")
    create_store("8888888888888", "1")

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(VALID_BARCODE, "***", "9999999999999", "001"),
            ],
            "8888888888888/1/pricesfull/PriceFull8888888888888-001-001-20260101-000000.xml": [
                _fake_product(VALID_BARCODE, "###", "8888888888888", "001"),
            ],
        },
    )

    # File processing order determines which junk name wins the fallback.
    load_files(conn, filepaths, tmp_path)

    name, _, _ = _product_row(conn, VALID_BARCODE)
    assert name == "***"  # first file processed


def test_blank_manufacturer_filled_within_same_batch(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
):
    create_store("9999999999999", "1")
    create_store("8888888888888", "1")

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(VALID_BARCODE, "מוצר", "9999999999999", "001"),
            ],
            "8888888888888/1/pricesfull/PriceFull8888888888888-001-001-20260101-000000.xml": [
                _fake_product(
                    VALID_BARCODE, "מוצר", "8888888888888", "001",
                    manufacturer="Acme", manufacturer_country="IL",
                ),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    _, manufacturer, country = _product_row(conn, VALID_BARCODE)
    assert manufacturer == "Acme"
    assert country == "IL"


def test_filled_manufacturer_not_overwritten_within_same_batch(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
):
    create_store("9999999999999", "1")
    create_store("8888888888888", "1")

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(
                    VALID_BARCODE, "מוצר", "9999999999999", "001",
                    manufacturer="Acme", manufacturer_country="IL",
                ),
            ],
            "8888888888888/1/pricesfull/PriceFull8888888888888-001-001-20260101-000000.xml": [
                _fake_product(
                    VALID_BARCODE, "מוצר", "8888888888888", "001",
                    manufacturer="SomeoneElse", manufacturer_country="US",
                ),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    _, manufacturer, country = _product_row(conn, VALID_BARCODE)
    assert manufacturer == "Acme"
    assert country == "IL"


def test_unknown_metadata_sentinel_normalized_to_none(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
):
    create_store("9999999999999", "1")
    create_store("8888888888888", "1")

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(
                    VALID_BARCODE, "מוצר", "9999999999999", "001",
                    manufacturer_country="לא יודע",
                ),
            ],
            "8888888888888/1/pricesfull/PriceFull8888888888888-001-001-20260101-000000.xml": [
                _fake_product(
                    VALID_BARCODE, "מוצר", "8888888888888", "001",
                    manufacturer_country="IL",
                ),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    _, _, country = _product_row(conn, VALID_BARCODE)
    assert country == "IL"


def test_unknown_chain_is_skipped_not_raised(
    conn, mock_chain_metadata, monkeypatch, tmp_path,
):
    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "1231231231231/1/pricesfull/PriceFull1231231231231-001-001-20260101-000000.xml": [
                _fake_product(VALID_BARCODE, "מוצר", "1231231231231", "001"),
            ],
        },
    )

    successful = load_files(conn, filepaths, tmp_path)
    assert successful == []

NEW_BARCODE = "9506000140445"
def test_discover_new_products_inserts_new_item_with_observed_name(
    conn,
    create_store,
    monkeypatch,
    tmp_path,
):
    create_store("9999999999999", "1")

    filepaths = _write_and_patch(
        monkeypatch,
        tmp_path,
        {
            "9999999999999/1/pricesfull/"
            "PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(
                    NEW_BARCODE,
                    "שם מלוכלך גולמי",
                    "9999999999999",
                    "001",
                ),
            ],
        },
    )

    discover_new_products(conn, filepaths, tmp_path)

    name, _, _ = _product_row(conn, NEW_BARCODE)

    assert name == "שם מלוכלך גולמי"


def test_discover_new_products_never_touches_existing_item(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
):
    create_store("9999999999999", "1")
    create_store("8888888888888", "1")

    canonical_filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(DISCOVER_BARCODE, "שם קנוני שנבחר", "9999999999999", "001"),
            ],
        },
    )
    load_files(conn, canonical_filepaths, tmp_path)

    discover_filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260102-000000.xml": [
                _fake_product(DISCOVER_BARCODE, "שם אחר לגמרי", "9999999999999", "001"),
            ],
        },
    )
    discover_new_products(conn, discover_filepaths, tmp_path)

    name, _, _ = _product_row(conn, DISCOVER_BARCODE)
    assert name == "שם קנוני שנבחר"

# ===========================================================================
# Pharmacy routing
#
# Pharmacy stores are not skipped. For a pharmacy store:
#   - non-barcode item                  -> pharmacy_store_products
#   - barcode already known             -> nothing (product already exists)
#   - barcode not known anywhere else   -> pharmacy_products (quarantine)
#
# "Known" = in `products`, or coming from a non-pharmacy store in the
# same run/batch, regardless of file order.
#
# The two chain ids below are the ones mock_chain_metadata already knows.
# ===========================================================================

SUPERMARKET_CHAIN = "9999999999999"
PHARMACY_CHAIN = "8888888888888"

# Valid GTIN-13s, unique to the pharmacy tests.
PH_ONLY_BARCODE = "7290000990019"
PH_KNOWN_DB_BARCODE = "7290000990026"
PH_SHARED_BARCODE = "7290000990033"
PH_OTHER_STORE_BARCODE = "7290000990040"

PH_BARCODES = [
    PH_ONLY_BARCODE,
    PH_KNOWN_DB_BARCODE,
    PH_SHARED_BARCODE,
    PH_OTHER_STORE_BARCODE,
]

PH_INTERNAL_CODE = "PHARMTEST_INTERNAL_001"
SUPER_INTERNAL_CODE = "PHARMTEST_INTERNAL_002"


@pytest.fixture
def pharmacy_clean(conn):
    """
    Remove pharmacy-test rows before and after the test.

    Setup does not rollback or commit (see test_repository.py). Teardown
    rolls back, deletes what load_files / discover_new_products committed,
    then commits, so cleanup_test_chains can later delete the test chains
    without hitting the pharmacy tables' foreign keys.
    """

    def _delete():
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pharmacy_products WHERE item_code = ANY(%s)",
                (PH_BARCODES,),
            )
            cur.execute(
                "DELETE FROM pharmacy_store_products WHERE item_code LIKE %s",
                ("PHARMTEST%",),
            )
            cur.execute(
                "DELETE FROM store_products WHERE item_code LIKE %s",
                ("PHARMTEST%",),
            )
            cur.execute(
                "DELETE FROM products WHERE item_code = ANY(%s)",
                (PH_BARCODES,),
            )

    _delete()

    yield

    conn.rollback()
    _delete()
    conn.commit()


def _patch_pharmacy_stores(monkeypatch, stores=None):
    """
    Make PHARMACY_CHAIN the only pharmacy chain.
    stores=None -> every store of the chain is a pharmacy.
    stores=[...] -> only those store ids are pharmacies.
    """
    monkeypatch.setattr(
        "utils.products.update_products._load_pharmacy_stores",
        lambda: {PHARMACY_CHAIN: None if stores is None else set(stores)},
    )


def _feed_path(chain_id, store_id, stamp="20260101-000000"):
    return (
        f"{chain_id}/{store_id}/pricesfull/"
        f"PriceFull{chain_id}-001-{store_id.zfill(3)}-{stamp}.xml"
    )


def _count_rows(conn, table, item_code):
    # `table` is always a constant from this module, never user input.
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE item_code = %s",
            (item_code,),
        )
        return cur.fetchone()[0]


def _ordered_files(pharmacy_first, pharmacy_file, supermarket_file):
    """Build a files dict in a chosen order (dict order = scan order)."""
    items = [pharmacy_file, supermarket_file]
    if not pharmacy_first:
        items.reverse()
    return dict(items)


# ---------------------------------------------------------------------------
# load_files
# ---------------------------------------------------------------------------


def test_pharmacy_non_barcode_item_goes_to_pharmacy_store_products(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_INTERNAL_CODE, "משחת שיניים", PHARMACY_CHAIN, "001"),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_store_products", PH_INTERNAL_CODE) == 1
    assert _count_rows(conn, "store_products", PH_INTERNAL_CODE) == 0


def test_pharmacy_only_barcode_is_quarantined_not_added_to_products(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_ONLY_BARCODE, "שמפו", PHARMACY_CHAIN, "001"),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_products", PH_ONLY_BARCODE) == 1
    assert _product_row(conn, PH_ONLY_BARCODE) is None


def test_pharmacy_barcode_already_in_products_is_not_quarantined(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    upsert_products(
        conn,
        [ProductRecord(PH_KNOWN_DB_BARCODE, "שם קיים", None, None, 1)],
    )
    conn.commit()

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(
                    PH_KNOWN_DB_BARCODE, "שם מבית מרקחת", PHARMACY_CHAIN, "001",
                ),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_products", PH_KNOWN_DB_BARCODE) == 0

    name, _, _ = _product_row(conn, PH_KNOWN_DB_BARCODE)
    assert name == "שם קיים"


@pytest.mark.parametrize("pharmacy_first", [True, False])
def test_pharmacy_barcode_known_from_supermarket_in_same_run(
    pharmacy_first,
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    """
    Scan order must not matter: a barcode sold by a supermarket in the
    same run is known, whether the pharmacy file is scanned before or after.
    The pharmacy's own name must not influence the canonical name.
    """
    create_store(SUPERMARKET_CHAIN, "1")
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    supermarket_name = "משקה קוקה קולה זירו 1.5 ליטר"

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        _ordered_files(
            pharmacy_first,
            (
                _feed_path(PHARMACY_CHAIN, "1"),
                [_fake_product(
                    PH_SHARED_BARCODE, "שם מבית מרקחת", PHARMACY_CHAIN, "001",
                )],
            ),
            (
                _feed_path(SUPERMARKET_CHAIN, "1"),
                [_fake_product(
                    PH_SHARED_BARCODE, supermarket_name, SUPERMARKET_CHAIN, "001",
                )],
            ),
        ),
    )

    load_files(conn, filepaths, tmp_path)

    expected_name = resolve_canonical_name({
        supermarket_name: {SUPERMARKET_CHAIN: 1},
    })

    name, _, _ = _product_row(conn, PH_SHARED_BARCODE)
    assert name == expected_name
    assert _count_rows(conn, "pharmacy_products", PH_SHARED_BARCODE) == 0


def test_pharmacy_scope_limited_to_listed_stores(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    """
    Only store 1 of the chain is a pharmacy. Store 2 of the same chain is a
    normal supermarket, so its barcode is inserted into products.
    """
    create_store(PHARMACY_CHAIN, "1")
    create_store(PHARMACY_CHAIN, "2")
    _patch_pharmacy_stores(monkeypatch, stores=["1"])

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_ONLY_BARCODE, "שמפו", PHARMACY_CHAIN, "001"),
            ],
            _feed_path(PHARMACY_CHAIN, "2"): [
                _fake_product(
                    PH_OTHER_STORE_BARCODE, "חטיף", PHARMACY_CHAIN, "002",
                ),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_products", PH_ONLY_BARCODE) == 1
    assert _product_row(conn, PH_ONLY_BARCODE) is None

    assert _product_row(conn, PH_OTHER_STORE_BARCODE) is not None
    assert _count_rows(conn, "pharmacy_products", PH_OTHER_STORE_BARCODE) == 0


def test_supermarket_non_barcode_item_still_goes_to_store_products(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    create_store(SUPERMARKET_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(SUPERMARKET_CHAIN, "1"): [
                _fake_product(
                    SUPER_INTERNAL_CODE, "עגבניה", SUPERMARKET_CHAIN, "001",
                ),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)

    assert _count_rows(conn, "store_products", SUPER_INTERNAL_CODE) == 1
    assert _count_rows(conn, "pharmacy_store_products", SUPER_INTERNAL_CODE) == 0


def test_pharmacy_file_is_reported_as_successfully_processed(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_ONLY_BARCODE, "שמפו", PHARMACY_CHAIN, "001"),
            ],
        },
    )

    successful = load_files(conn, filepaths, tmp_path)

    assert successful == filepaths


def test_pharmacy_load_is_idempotent(
    conn, mock_chain_metadata, create_store, monkeypatch, tmp_path,
    pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_ONLY_BARCODE, "שמפו", PHARMACY_CHAIN, "001"),
                _fake_product(PH_INTERNAL_CODE, "משחה", PHARMACY_CHAIN, "001"),
            ],
        },
    )

    load_files(conn, filepaths, tmp_path)
    load_files(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_products", PH_ONLY_BARCODE) == 1
    assert _count_rows(conn, "pharmacy_store_products", PH_INTERNAL_CODE) == 1


# ---------------------------------------------------------------------------
# discover_new_products
# ---------------------------------------------------------------------------


def test_discover_pharmacy_only_barcode_is_quarantined_not_inserted(
    conn, create_store, monkeypatch, tmp_path, pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_ONLY_BARCODE, "שמפו", PHARMACY_CHAIN, "001"),
            ],
        },
    )

    discover_new_products(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_products", PH_ONLY_BARCODE) == 1
    assert _product_row(conn, PH_ONLY_BARCODE) is None


def test_discover_pharmacy_barcode_already_in_products_is_untouched(
    conn, create_store, monkeypatch, tmp_path, pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    upsert_products(
        conn,
        [ProductRecord(PH_KNOWN_DB_BARCODE, "שם קיים", None, None, 1)],
    )
    conn.commit()

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(
                    PH_KNOWN_DB_BARCODE, "שם מבית מרקחת", PHARMACY_CHAIN, "001",
                ),
            ],
        },
    )

    discover_new_products(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_products", PH_KNOWN_DB_BARCODE) == 0

    name, _, _ = _product_row(conn, PH_KNOWN_DB_BARCODE)
    assert name == "שם קיים"


@pytest.mark.parametrize("pharmacy_first", [True, False])
def test_discover_pharmacy_barcode_with_supermarket_in_same_batch(
    pharmacy_first,
    conn, create_store, monkeypatch, tmp_path, pharmacy_clean,
):
    """
    A new barcode seen by both a pharmacy and a supermarket in one batch is
    inserted into products with the supermarket's name and is not
    quarantined, whatever the scan order.
    """
    create_store(SUPERMARKET_CHAIN, "1")
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        _ordered_files(
            pharmacy_first,
            (
                _feed_path(PHARMACY_CHAIN, "1"),
                [_fake_product(
                    PH_SHARED_BARCODE, "שם מבית מרקחת", PHARMACY_CHAIN, "001",
                )],
            ),
            (
                _feed_path(SUPERMARKET_CHAIN, "1"),
                [_fake_product(
                    PH_SHARED_BARCODE, "שם מהסופר", SUPERMARKET_CHAIN, "001",
                )],
            ),
        ),
    )

    discover_new_products(conn, filepaths, tmp_path)

    name, _, _ = _product_row(conn, PH_SHARED_BARCODE)
    assert name == "שם מהסופר"
    assert _count_rows(conn, "pharmacy_products", PH_SHARED_BARCODE) == 0


def test_discover_pharmacy_non_barcode_item_goes_to_pharmacy_store_products(
    conn, create_store, monkeypatch, tmp_path, pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_INTERNAL_CODE, "משחה", PHARMACY_CHAIN, "001"),
            ],
        },
    )

    discover_new_products(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_store_products", PH_INTERNAL_CODE) == 1
    assert _count_rows(conn, "store_products", PH_INTERNAL_CODE) == 0


def test_discover_pharmacy_scope_limited_to_listed_stores(
    conn, create_store, monkeypatch, tmp_path, pharmacy_clean,
):
    create_store(PHARMACY_CHAIN, "1")
    create_store(PHARMACY_CHAIN, "2")
    _patch_pharmacy_stores(monkeypatch, stores=["1"])

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(PHARMACY_CHAIN, "1"): [
                _fake_product(PH_ONLY_BARCODE, "שמפו", PHARMACY_CHAIN, "001"),
            ],
            _feed_path(PHARMACY_CHAIN, "2"): [
                _fake_product(
                    PH_OTHER_STORE_BARCODE, "חטיף", PHARMACY_CHAIN, "002",
                ),
            ],
        },
    )

    discover_new_products(conn, filepaths, tmp_path)

    assert _count_rows(conn, "pharmacy_products", PH_ONLY_BARCODE) == 1
    assert _product_row(conn, PH_ONLY_BARCODE) is None

    assert _product_row(conn, PH_OTHER_STORE_BARCODE) is not None
    assert _count_rows(conn, "pharmacy_products", PH_OTHER_STORE_BARCODE) == 0


def test_discover_supermarket_non_barcode_item_still_goes_to_store_products(
    conn, create_store, monkeypatch, tmp_path, pharmacy_clean,
):
    create_store(SUPERMARKET_CHAIN, "1")
    _patch_pharmacy_stores(monkeypatch)

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            _feed_path(SUPERMARKET_CHAIN, "1"): [
                _fake_product(
                    SUPER_INTERNAL_CODE, "עגבניה", SUPERMARKET_CHAIN, "001",
                ),
            ],
        },
    )

    discover_new_products(conn, filepaths, tmp_path)

    assert _count_rows(conn, "store_products", SUPER_INTERNAL_CODE) == 1
    assert _count_rows(conn, "pharmacy_store_products", SUPER_INTERNAL_CODE) == 0