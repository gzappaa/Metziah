import json
from dataclasses import asdict
from pathlib import Path

import pytest

from models.store import Store
from utils.stores import get_stores


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "9999999999999"
    / "stores"
    / "Stores9999999999999-000-20260101-000000.xml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def stores_xml():
    return FIXTURE.read_bytes()


@pytest.fixture
def parsed_stores(stores_xml):
    return get_stores.parse_stores_xml(
        stores_xml,
        "9999999999999",
    )


# ---------------------------------------------------------------------------
# findtext_any
# ---------------------------------------------------------------------------

def test_findtext_any_returns_first_matching_tag():
    from lxml import etree

    root = etree.fromstring(
        b"<Root><ChainId>123</ChainId><ChainID>456</ChainID></Root>"
    )

    assert get_stores.findtext_any(
        root,
        ("ChainID", "ChainId"),
    ) == "456"


def test_findtext_any_returns_none_when_missing():
    from lxml import etree

    root = etree.fromstring(b"<Root><Name>Test</Name></Root>")

    assert get_stores.findtext_any(
        root,
        ("ChainID", "ChainId"),
    ) is None


# ---------------------------------------------------------------------------
# clean_address
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (None, None),
        ("", None),
        ("123 Main St", "123 Main St"),
        ("123   Main    St", "123 Main St"),
        ("123 Main https://example.com St", "123 Main St"),
        ("123 Main http://example.com", "123 Main"),
        ("  123   Main   St  ", "123 Main St"),
    ],
)
def test_clean_address(address, expected):
    assert get_stores.clean_address(address) == expected


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------

def test_sanitize_filename_removes_invalid_characters():
    assert (
        get_stores.sanitize_filename(
            '  Test: Chain / "Name"?  '
        )
        == "Test Chain Name"
    )


def test_sanitize_filename_collapses_whitespace():
    assert (
        get_stores.sanitize_filename(
            "  Test    Chain   Name  "
        )
        == "Test Chain Name"
    )


# ---------------------------------------------------------------------------
# normalize_store_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("002", "2"),
        ("02", "2"),
        ("2", "2"),
        ("006", "6"),
        ("06", "6"),
        ("6", "6"),
        ("000", "0"),
        (" 002 ", "2"),
        (2, "2"),
        ("ABC", "ABC"),
        (" ABC ", "ABC"),
    ],
)
def test_normalize_store_id(value, expected):
    assert get_stores.normalize_store_id(value) == expected


# ---------------------------------------------------------------------------
# find_stores_file
# ---------------------------------------------------------------------------

def test_find_stores_file_returns_none_when_directory_missing(tmp_path):
    assert get_stores.find_stores_file(
        tmp_path / "missing"
    ) is None


def test_find_stores_file_returns_none_when_no_stores_files(tmp_path):
    chain_dir = tmp_path / "123"
    (chain_dir / "stores").mkdir(parents=True)

    (
        chain_dir / "stores" / "other.xml"
    ).write_text(
        "<xml/>",
        encoding="utf-8",
    )

    assert get_stores.find_stores_file(chain_dir) is None


def test_find_stores_file_finds_stores_file(tmp_path):
    chain_dir = tmp_path / "123"
    stores_dir = chain_dir / "stores"
    stores_dir.mkdir(parents=True)

    expected = stores_dir / "Stores123.xml"
    expected.write_text("<xml/>", encoding="utf-8")

    assert get_stores.find_stores_file(chain_dir) == expected


def test_find_stores_file_ignores_colon_filename(tmp_path):
    chain_dir = tmp_path / "123"
    stores_dir = chain_dir / "stores"
    stores_dir.mkdir(parents=True)

    (
        stores_dir / "Stores:123.xml"
    ).write_text(
        "<xml/>",
        encoding="utf-8",
    )

    assert get_stores.find_stores_file(chain_dir) is None


def test_find_stores_file_uses_most_recent(tmp_path):
    chain_dir = tmp_path / "123"
    stores_dir = chain_dir / "stores"
    stores_dir.mkdir(parents=True)

    old_file = stores_dir / "Stores-old.xml"
    new_file = stores_dir / "Stores-new.xml"

    old_file.write_text("<old/>", encoding="utf-8")
    new_file.write_text("<new/>", encoding="utf-8")

    old_file.touch()
    new_file.touch()

    import os

    os.utime(old_file, (1000, 1000))
    os.utime(new_file, (2000, 2000))

    assert get_stores.find_stores_file(chain_dir) == new_file


# ---------------------------------------------------------------------------
# read_xml_content
# ---------------------------------------------------------------------------

def test_read_xml_content_reads_fixture(stores_xml, tmp_path):
    path = tmp_path / "stores.xml"
    path.write_bytes(stores_xml)

    assert get_stores.read_xml_content(path) == stores_xml


def test_read_xml_content_reads_gzip(stores_xml, tmp_path):
    import gzip

    path = tmp_path / "stores.xml.gz"
    path.write_bytes(gzip.compress(stores_xml))

    assert get_stores.read_xml_content(path) == stores_xml


def test_read_xml_content_reads_zip(stores_xml, tmp_path):
    import io
    import zipfile

    path = tmp_path / "stores.zip"

    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zf:
        zf.writestr("stores.xml", stores_xml)

    path.write_bytes(buffer.getvalue())

    assert get_stores.read_xml_content(path) == stores_xml


def test_read_xml_content_strips_utf8_bom(
    stores_xml,
    tmp_path,
):
    path = tmp_path / "stores.xml"

    path.write_bytes(b"\xef\xbb\xbf" + stores_xml)

    assert get_stores.read_xml_content(path) == stores_xml


def test_read_xml_content_raises_for_unknown_format(tmp_path):
    path = tmp_path / "stores.dat"
    path.write_bytes(b"not xml")

    with pytest.raises(
        ValueError,
        match="Unrecognized file format",
    ):
        get_stores.read_xml_content(path)


# ---------------------------------------------------------------------------
# find_store_elements
# ---------------------------------------------------------------------------

def test_find_store_elements_finds_fixture_store(stores_xml):
    from lxml import etree

    root = etree.fromstring(stores_xml)

    elements = get_stores.find_store_elements(root)

    assert len(elements) == 1
    assert elements[0].findtext("StoreID") == "001"


# ---------------------------------------------------------------------------
# parse_stores_xml
# ---------------------------------------------------------------------------

def test_parse_stores_xml_fixture(parsed_stores):
    chain_info, stores = parsed_stores

    assert chain_info == {
        "chain_id": "9999999999999",
        "chain_name": "test",
        "last_update_date": "2026-01-01",
        "last_update_time": "00:00:00.211",
    }

    assert len(stores) == 1

    assert asdict(stores[0]) == {
        "chain_id": "9999999999999",
        "store_id": "001",
        "name": "test",
        "address": "test",
        "city": "5000",
        "zip_code": "00000000",
        "latitude": None,
        "longitude": None,
    }


def test_parse_stores_xml_uses_fallback_chain_id():
    xml = b"""
    <Root>
        <Store>
            <StoreID>001</StoreID>
            <StoreName>test</StoreName>
        </Store>
    </Root>
    """

    chain_info, stores = get_stores.parse_stores_xml(
        xml,
        "fallback-chain",
    )

    assert chain_info["chain_id"] == "fallback-chain"
    assert stores[0].chain_id == "fallback-chain"


# ---------------------------------------------------------------------------
# load_existing
# ---------------------------------------------------------------------------

def test_load_existing_returns_empty_for_missing_file(tmp_path):
    assert get_stores.load_existing(
        tmp_path / "missing.json"
    ) == {}


def test_load_existing_normalizes_ids_for_matching(tmp_path):
    path = tmp_path / "stores.json"

    path.write_text(
        json.dumps(
            [
                {
                    "store_id": "002",
                    "name": "Store Two",
                },
                {
                    "store_id": "006",
                    "name": "Store Six",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = get_stores.load_existing(path)

    assert set(result) == {"2", "6"}
    assert result["2"]["store_id"] == "002"
    assert result["6"]["store_id"] == "006"


# ---------------------------------------------------------------------------
# compare_stores
# ---------------------------------------------------------------------------

def test_compare_stores_detects_new_and_removed(parsed_stores):
    _, stores = parsed_stores

    old = {
        "1": {
            "store_id": "001",
            "name": "Old Store",
        },
        "2": {
            "store_id": "002",
            "name": "Removed Store",
        },
    }

    changes = get_stores.compare_stores(
        old,
        stores,
    )

    assert "NEW STORE: 1" not in changes
    assert "REMOVED STORE: 2" in changes


def test_compare_stores_treats_padded_ids_as_same(parsed_stores):
    _, stores = parsed_stores

    old = {
        "1": {
            "store_id": "001",
            "name": "Store",
        },
    }

    assert get_stores.compare_stores(
        old,
        stores,
    ) == []


# ---------------------------------------------------------------------------
# merge_stores
# ---------------------------------------------------------------------------

def test_merge_stores_keeps_existing_store_unchanged(
    parsed_stores,
):
    _, stores = parsed_stores

    old = {
        "1": {
            "store_id": "001",
            "name": "Original Name",
            "address": "Original Address",
        },
    }

    merged = get_stores.merge_stores(
        old,
        stores,
    )

    assert merged == [
        {
            "store_id": "001",
            "name": "Original Name",
            "address": "Original Address",
        }
    ]


def test_merge_stores_marks_missing_store_as_new(
    parsed_stores,
):
    _, stores = parsed_stores

    old = {
        "999": {
            "store_id": "999",
            "name": "Missing Store",
        },
    }

    merged = get_stores.merge_stores(
        old,
        stores,
    )

    missing = next(
        store
        for store in merged
        if store["store_id"] == "999"
    )

    assert missing["name"] == "[N] Missing Store"


def test_merge_stores_does_not_duplicate_new_marker(
    parsed_stores,
):
    _, stores = parsed_stores

    old = {
        "999": {
            "store_id": "999",
            "name": "[N] Missing Store",
        },
    }

    merged = get_stores.merge_stores(
        old,
        stores,
    )

    missing = next(
        store
        for store in merged
        if store["store_id"] == "999"
    )

    assert missing["name"] == "[N] Missing Store"


def test_merge_stores_appends_genuinely_new_store(
    parsed_stores,
):
    _, stores = parsed_stores

    old = {}

    merged = get_stores.merge_stores(
        old,
        stores,
    )

    assert len(merged) == 1

    assert merged[0] == {
        "chain_id": "9999999999999",
        "store_id": "001",
        "name": "test",
        "address": "test",
        "city": "5000",
        "zip_code": "00000000",
        "latitude": None,
        "longitude": None,
    }



def test_merge_stores_matches_padded_and_unpadded_ids(
    parsed_stores,
):
    _, stores = parsed_stores

    old = {
        "1": {
            "store_id": "001",
            "name": "Original",
        },
    }

    merged = get_stores.merge_stores(
        old,
        stores,
    )

    assert merged == [
        {
            "store_id": "001",
            "name": "Original",
        }
    ]