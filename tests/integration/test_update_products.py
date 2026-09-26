from decimal import Decimal
from types import SimpleNamespace

import pytest

from parsers.xml import StoreXmlParser
from utils.products.update_products import load_files, discover_new_products
from utils.resolve_canonical_name import resolve_canonical_name


# Valid GTIN-13 required to exercise the products/canonical-name path.

VALID_BARCODE = "4006381333931"
DISCOVER_BARCODE = "4006381333948"

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


def test_discover_new_products_inserts_new_item_with_canonical_name(
    conn, create_store, monkeypatch, tmp_path,
):
    create_store("9999999999999", "1")

    filepaths = _write_and_patch(
        monkeypatch, tmp_path,
        {
            "9999999999999/1/pricesfull/PriceFull9999999999999-001-001-20260101-000000.xml": [
                _fake_product(DISCOVER_BARCODE, "שם מלוכלך גולמי", "9999999999999", "001"),
            ],
        },
    )

    discover_new_products(conn, filepaths, tmp_path)

    name, _, _ = _product_row(conn, DISCOVER_BARCODE)
    assert name == "שם קנוני שנבחר"


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