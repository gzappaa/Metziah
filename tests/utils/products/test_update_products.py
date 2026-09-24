from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict

import pytest

import utils.products.update_products as module

from database.records import ProductRecord, StoreProductRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_product(
    *,
    item_code="7290000000001",
    name="Test Product",
    chain_id="999999999999",
    store_id="1",
    manufacturer="Manufacturer",
    manufacturer_country="Israel",
    item_type=1,
):
    return SimpleNamespace(
        item_code=item_code,
        name=name,
        chain_id=chain_id,
        store_id=store_id,
        manufacturer=manufacturer,
        manufacturer_country=manufacturer_country,
        item_type=item_type,
    )


def make_product_record(
    *,
    item_code="7290000000001",
    name="Test Product",
    manufacturer="Manufacturer",
    manufacturer_country="Israel",
    item_type=1,
):
    return ProductRecord(
        item_code=item_code,
        name=name,
        manufacturer=manufacturer,
        manufacturer_country=manufacturer_country,
        item_type=item_type,
    )


def make_store_product_record(
    *,
    item_code="12345",
    name="Store Product",
    manufacturer="Manufacturer",
    manufacturer_country="Israel",
    item_type=1,
    chain_id="999999999999",
    store_id="1",
):
    return StoreProductRecord(
        chain_id=chain_id,
        store_id=store_id,
        item_code=item_code,
        name=name,
        manufacturer=manufacturer,
        manufacturer_country=manufacturer_country,
        item_type=item_type,
    )


def pricefull_filepath(feeds_dir):
    return (
        feeds_dir
        / "999999999999"
        / "1"
        / "pricesfull"
        / "PriceFull9999999999999-001-001-20260101-000000.gz"
    )


def prices_filepath(feeds_dir):
    return (
        feeds_dir
        / "999999999999"
        / "1"
        / "prices"
        / "Price999999999999-001-001-20260101-000000.gz"
    )


class DummyCursor:
    def __init__(self, existing_codes=None):
        self.existing_codes = existing_codes or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, *args):
        self.execute_args = args

    def fetchall(self):
        return [(code,) for code in self.existing_codes]


class DummyConnection:
    def __init__(self, existing_codes=None):
        self.existing_codes = existing_codes or []
        self.rollback_count = 0
        self.commit_count = 0

    def cursor(self):
        return DummyCursor(self.existing_codes)

    def rollback(self):
        self.rollback_count += 1

    def commit(self):
        self.commit_count += 1


# ---------------------------------------------------------------------------
# normalize_metadata_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", ""),
        ("  Manufacturer  ", "Manufacturer"),
        ("לא יודע", None),
        ("  לא יודע  ", None),
        ("Israel", "Israel"),
    ],
)
def test_normalize_metadata_value(value, expected):
    assert module.normalize_metadata_value(value) == expected


# ---------------------------------------------------------------------------
# _add_product_observation
# ---------------------------------------------------------------------------


def test_add_product_observation():
    observations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(int)
        )
    )

    record = make_product_record(
        item_code="123",
        name="Coke",
    )

    module._add_product_observation(
        observations,
        record,
        "chain1",
    )

    assert observations["123"]["Coke"]["chain1"] == 1


def test_add_product_observation_accumulates():
    observations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(int)
        )
    )

    record = make_product_record(
        item_code="123",
        name="Coke",
    )

    module._add_product_observation(observations, record, "chain1")
    module._add_product_observation(observations, record, "chain1")
    module._add_product_observation(observations, record, "chain2")

    assert observations["123"]["Coke"]["chain1"] == 2
    assert observations["123"]["Coke"]["chain2"] == 1


def test_add_product_observation_ignores_none():
    observations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(int)
        )
    )

    module._add_product_observation(
        observations,
        None,
        "chain1",
    )

    assert dict(observations) == {}


def test_add_product_observation_ignores_empty_name():
    observations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(int)
        )
    )

    record = make_product_record(
        item_code="123",
        name="",
    )

    module._add_product_observation(
        observations,
        record,
        "chain1",
    )

    assert dict(observations) == {}


# ---------------------------------------------------------------------------
# _merge_product_metadata
# ---------------------------------------------------------------------------


def test_merge_product_metadata_keeps_existing_values():
    existing = make_product_record(
        item_code="123",
        name="Old Name",
        manufacturer="Old Manufacturer",
        manufacturer_country="Israel",
        item_type="Food",
    )

    incoming = make_product_record(
        item_code="123",
        name="New Name",
        manufacturer="New Manufacturer",
        manufacturer_country="USA",
        item_type="Drink",
    )

    result = module._merge_product_metadata(
        existing,
        incoming,
    )

    assert result.item_code == "123"
    assert result.name == "Old Name"
    assert result.manufacturer == "Old Manufacturer"
    assert result.manufacturer_country == "Israel"
    assert result.item_type == "Drink"


def test_merge_product_metadata_fills_missing_metadata():
    existing = make_product_record(
        item_code="123",
        name="Product",
        manufacturer=None,
        manufacturer_country=None,
        item_type=None,
    )

    incoming = make_product_record(
        item_code="123",
        name="Other Name",
        manufacturer="Manufacturer",
        manufacturer_country="Israel",
        item_type="Food",
    )

    result = module._merge_product_metadata(
        existing,
        incoming,
    )

    assert result.manufacturer == "Manufacturer"
    assert result.manufacturer_country == "Israel"
    assert result.item_type == "Food"
    assert result.name == "Product"


# ---------------------------------------------------------------------------
# _resolve_product_records
# ---------------------------------------------------------------------------


def test_resolve_product_records_uses_canonical_name(monkeypatch):
    observations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(int)
        )
    )

    observations["123"]["Raw Name"]["chain1"] = 3

    record = make_product_record(
        item_code="123",
        name="Raw Name",
    )

    product_metadata = {
        "123": {
            "record": record,
            "fallback_name": "Raw Name",
        }
    }

    monkeypatch.setattr(
        module,
        "resolve_canonical_name",
        lambda counts: "Canonical Name",
    )

    result = module._resolve_product_records(
        observations,
        product_metadata,
    )

    assert len(result) == 1
    assert result[0].item_code == "123"
    assert result[0].name == "Canonical Name"


def test_resolve_product_records_uses_fallback(monkeypatch):
    observations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(int)
        )
    )

    observations["123"]["Raw Name"]["chain1"] = 1

    record = make_product_record(
        item_code="123",
        name="Raw Name",
    )

    product_metadata = {
        "123": {
            "record": record,
            "fallback_name": "Raw Name",
        }
    }

    monkeypatch.setattr(
        module,
        "resolve_canonical_name",
        lambda counts: None,
    )

    result = module._resolve_product_records(
        observations,
        product_metadata,
    )

    assert result[0].name == "Raw Name"


# ---------------------------------------------------------------------------
# _load_chain_metadata
# ---------------------------------------------------------------------------


def test_load_chain_metadata_merges_extra(monkeypatch, tmp_path):
    chains_file = tmp_path / "chains.json"
    extra_file = tmp_path / "chains_extra.json"

    chains_file.write_text(
        '{"1": {"name_en_normalized": "Main"}}',
        encoding="utf-8",
    )

    extra_file.write_text(
        '{"2": {"name_en_normalized": "Extra"}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "CHAINS_FILE", chains_file)
    monkeypatch.setattr(module, "CHAINS_EXTRA_FILE", extra_file)

    result = module._load_chain_metadata()

    assert result == {
        "1": {"name_en_normalized": "Main"},
        "2": {"name_en_normalized": "Extra"},
    }


def test_load_chain_metadata_extra_overrides_main(
    monkeypatch,
    tmp_path,
):
    chains_file = tmp_path / "chains.json"
    extra_file = tmp_path / "chains_extra.json"

    chains_file.write_text(
        '{"1": {"name_en_normalized": "Main"}}',
        encoding="utf-8",
    )

    extra_file.write_text(
        '{"1": {"name_en_normalized": "Extra"}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "CHAINS_FILE", chains_file)
    monkeypatch.setattr(module, "CHAINS_EXTRA_FILE", extra_file)

    result = module._load_chain_metadata()

    assert result["1"]["name_en_normalized"] == "Extra"


# ---------------------------------------------------------------------------
# load_files
# ---------------------------------------------------------------------------


def test_load_files_processes_products(monkeypatch, tmp_path):
    feeds_dir = tmp_path / "feeds"
    filepath = pricefull_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    chain_id = "999999999999"
    store_id = "1"

    product = make_product(
        item_code="7290000000001",
        name="Coke",
        chain_id=chain_id,
        store_id=store_id,
    )

    product_record = make_product_record(
        item_code="7290000000001",
        name="Coke",
    )

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {
            chain_id: {
                "name_he_normalized": "רשת",
                "name_en_normalized": "Chain",
            }
        },
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product],
    )

    monkeypatch.setattr(
        module,
        "split_product",
        lambda product, chain_id, store_id: (
            product_record,
            None,
            None,
        ),
    )

    monkeypatch.setattr(
        module,
        "resolve_canonical_name",
        lambda observations: "Canonical Coke",
    )

    ensured = []
    upserted_products = []
    upserted_store_products = []
    subchains = []

    monkeypatch.setattr(
        module,
        "ensure_chain",
        lambda conn, *args: ensured.append(args),
    )

    monkeypatch.setattr(
        module,
        "update_store_subchain",
        lambda conn, *args: subchains.append(args),
    )

    monkeypatch.setattr(
        module,
        "upsert_products",
        lambda conn, records: upserted_products.extend(records),
    )

    monkeypatch.setattr(
        module,
        "upsert_store_products",
        lambda conn, records: upserted_store_products.extend(records),
    )

    conn = DummyConnection()

    result = module.load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert result == [filepath]

    assert ensured == [
        (
            chain_id,
            "רשת",
            "Chain",
        )
    ]

    assert subchains == [
        (
            chain_id,
            store_id,
            "001",
        )
    ]

    assert len(upserted_products) == 1
    assert upserted_products[0].item_code == "7290000000001"
    assert upserted_products[0].name == "Canonical Coke"

    assert upserted_store_products == []
    assert conn.commit_count == 1


def test_load_files_creates_store_product_records(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = pricefull_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    product = make_product(
        chain_id="999999999999",
        store_id="1",
    )

    store_product = make_store_product_record()

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {
            "999999999999": {
                "name_he_normalized": "רשת",
                "name_en_normalized": "Chain",
            }
        },
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product],
    )

    monkeypatch.setattr(
        module,
        "split_product",
        lambda product, chain_id, store_id: (
            None,
            store_product,
            None,
        ),
    )

    upserted = []

    monkeypatch.setattr(
        module,
        "ensure_chain",
        lambda *args: None,
    )

    monkeypatch.setattr(
        module,
        "update_store_subchain",
        lambda *args: None,
    )

    monkeypatch.setattr(
        module,
        "upsert_store_products",
        lambda conn, records: upserted.extend(records),
    )

    monkeypatch.setattr(
        module,
        "upsert_products",
        lambda *args: None,
    )

    conn = DummyConnection()

    module.load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert len(upserted) == 1
    assert upserted[0].chain_id == "999999999999"
    assert upserted[0].store_id == "1"
    assert conn.commit_count == 1


def test_load_files_skips_unknown_chain(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = pricefull_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    product = make_product(
        chain_id="999999999999",
        store_id="1",
    )

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {},
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product],
    )

    conn = DummyConnection()

    result = module.load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert result == []
    assert conn.rollback_count == 1
    assert conn.commit_count == 1


def test_load_files_skips_file_with_no_products(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = pricefull_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {},
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [],
    )

    conn = DummyConnection()

    result = module.load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert result == []
    assert conn.commit_count == 1


def test_load_files_normalizes_unknown_metadata(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = pricefull_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    product = make_product(
        chain_id="999999999999",
        store_id="1",
        manufacturer=" לא יודע ",
        manufacturer_country=" Israel ",
    )

    product_record = make_product_record(
        manufacturer=None,
        manufacturer_country=None,
    )

    monkeypatch.setattr(
        module,
        "_load_chain_metadata",
        lambda: {
            "999999999999": {
                "name_he_normalized": "רשת",
                "name_en_normalized": "Chain",
            }
        },
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product],
    )

    captured = []

    def fake_split(product, chain_id, store_id):
        captured.append(product)
        return product_record, None, None

    monkeypatch.setattr(module, "split_product", fake_split)
    monkeypatch.setattr(
        module,
        "resolve_canonical_name",
        lambda x: "Product",
    )

    monkeypatch.setattr(module, "ensure_chain", lambda *args: None)
    monkeypatch.setattr(
        module,
        "update_store_subchain",
        lambda *args: None,
    )
    monkeypatch.setattr(
        module,
        "upsert_products",
        lambda *args: None,
    )

    conn = DummyConnection()

    module.load_files(
        conn,
        [filepath],
        feeds_dir,
    )

    assert captured[0].manufacturer is None
    assert captured[0].manufacturer_country == "Israel"


# ---------------------------------------------------------------------------
# discover_new_products
# ---------------------------------------------------------------------------


def test_discover_new_products_inserts_only_new_products(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = prices_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    product_a = make_product(
        item_code="111",
        name="Product A",
    )

    product_b = make_product(
        item_code="222",
        name="Product B",
    )

    record_a = make_product_record(
        item_code="111",
        name="Product A",
    )

    record_b = make_product_record(
        item_code="222",
        name="Product B",
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product_a, product_b],
    )

    def fake_split(product, chain_id, store_id):
        if product.item_code == "111":
            return record_a, None, None
        return record_b, None, None

    monkeypatch.setattr(module, "split_product", fake_split)

    upserted = []

    monkeypatch.setattr(
        module,
        "upsert_products",
        lambda conn, records: upserted.extend(records),
    )

    monkeypatch.setattr(
        module,
        "upsert_store_products",
        lambda *args: None,
    )

    conn = DummyConnection(existing_codes=["111"])

    module.discover_new_products(
        conn,
        [filepath],
        feeds_dir,
    )

    assert len(upserted) == 1
    assert upserted[0].item_code == "222"
    assert conn.commit_count == 1


def test_discover_new_products_upserts_store_products(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = prices_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    product = make_product()

    store_product = make_store_product_record()

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product],
    )

    monkeypatch.setattr(
        module,
        "split_product",
        lambda product, chain_id, store_id: (
            None,
            store_product,
            None,
        ),
    )

    upserted = []

    monkeypatch.setattr(
        module,
        "upsert_store_products",
        lambda conn, records: upserted.extend(records),
    )

    monkeypatch.setattr(
        module,
        "upsert_products",
        lambda *args: None,
    )

    conn = DummyConnection()

    module.discover_new_products(
        conn,
        [filepath],
        feeds_dir,
    )

    assert len(upserted) == 1
    assert upserted[0].chain_id == "999999999999"
    assert upserted[0].store_id == "1"
    assert conn.commit_count == 1


def test_discover_new_products_does_not_duplicate_candidate_item_code(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = prices_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    product_a = make_product(
        item_code="111",
        name="First Name",
    )

    product_b = make_product(
        item_code="111",
        name="Second Name",
    )

    record_a = make_product_record(
        item_code="111",
        name="First Name",
    )

    record_b = make_product_record(
        item_code="111",
        name="Second Name",
    )

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product_a, product_b],
    )

    def fake_split(product, chain_id, store_id):
        if product.name == "First Name":
            return record_a, None, None
        return record_b, None, None

    monkeypatch.setattr(module, "split_product", fake_split)

    upserted = []

    monkeypatch.setattr(
        module,
        "upsert_products",
        lambda conn, records: upserted.extend(records),
    )

    conn = DummyConnection()

    module.discover_new_products(
        conn,
        [filepath],
        feeds_dir,
    )

    assert len(upserted) == 1
    assert upserted[0].name == "First Name"


def test_discover_new_products_handles_bad_file(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = prices_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: (_ for _ in ()).throw(
            RuntimeError("bad XML")
        ),
    )

    conn = DummyConnection()

    module.discover_new_products(
        conn,
        [filepath],
        feeds_dir,
    )

    assert conn.commit_count == 1


def test_discover_new_products_normalizes_metadata(
    monkeypatch,
    tmp_path,
):
    feeds_dir = tmp_path / "feeds"
    filepath = prices_filepath(feeds_dir)
    filepath.parent.mkdir(parents=True)
    filepath.write_bytes(b"<xml/>")

    product = make_product(
        manufacturer=" לא יודע ",
        manufacturer_country=" Israel ",
    )

    captured = []

    monkeypatch.setattr(
        module,
        "iter_xml_from_path",
        lambda path: [b"<xml/>"],
    )

    monkeypatch.setattr(
        module.StoreXmlParser,
        "parse_price_file",
        lambda self, xml: [product],
    )

    def fake_split(product, chain_id, store_id):
        captured.append(product)
        return None, None, None

    monkeypatch.setattr(module, "split_product", fake_split)

    conn = DummyConnection()

    module.discover_new_products(
        conn,
        [filepath],
        feeds_dir,
    )

    assert captured[0].manufacturer is None
    assert captured[0].manufacturer_country == "Israel"