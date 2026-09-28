from decimal import Decimal
from pathlib import Path

import pytest

from parsers.xml import StoreXmlParser
from utils.prices.update_prices import load_files, load_one_file


def _prices(conn, chain_id, store_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_code, price FROM prices "
            "WHERE chain_id = %s AND store_id = %s",
            (chain_id, store_id),
        )
        return dict(cur.fetchall())


def test_pricefull_then_delta_updates_and_adds_without_removing(
    conn, feeds_dir, mock_chain_metadata, create_store, test_price_partitions,
):
    """
    PriceFull seeds 5 items. The Price delta changes item 1's price and
    adds a brand-new item 10. Loaded as a delta (snapshot=False), items
    2-5 must survive even though they're absent from the delta file.
    """
    chain_id = "9999999999999"
    store_id = "1"
    create_store(chain_id, store_id)

    files = [
        (
            feeds_dir / chain_id / store_id / "pricesfull"
            / "PriceFull9999999999999-001-001-20260101-000000.xml",
            "PriceFull",
            False,
        ),
        (
            feeds_dir / chain_id / store_id / "prices"
            / "Price9999999999999-001-001-20260101-000001.xml",
            "Price",
            False,
        ),
    ]

    loaded = load_files(conn, files, feeds_dir, log_changes=False)
    assert len(loaded) == 2

    assert _prices(conn, chain_id, store_id) == {
        "7290000000001": Decimal("11.00"),  # changed
        "7290000000002": Decimal("8.90"),   # untouched
        "7290000000003": Decimal("14.90"),  # untouched
        "7290000000004": Decimal("12.90"),  # untouched
        "7290000000005": Decimal("9.90"),   # untouched
        "7290000000010": Decimal("9.90"),   # added
    }


def test_price_snapshot_true_reconciles_missing_items(
    conn, feeds_dir, mock_chain_metadata, create_store, test_price_partitions,
):
    """
    Same two files, but the delta is now asserted to be a full snapshot
    (snapshot=True). Items 2-5, absent from that file, must be removed.
    """
    chain_id = "9999999999999"
    store_id = "1"
    create_store(chain_id, store_id)
    parser = StoreXmlParser()

    load_one_file(
        conn, parser,
        feeds_dir / chain_id / store_id / "pricesfull"
        / "PriceFull9999999999999-001-001-20260101-000000.xml",
        feeds_dir, mock_chain_metadata, "PriceFull",
        log_changes=False,
    )

    load_one_file(
        conn, parser,
        feeds_dir / chain_id / store_id / "prices"
        / "Price9999999999999-001-001-20260101-000001.xml",
        feeds_dir, mock_chain_metadata, "Price",
        snapshot=True,
        log_changes=False,
    )

    assert _prices(conn, chain_id, store_id) == {
        "7290000000001": Decimal("11.00"),
        "7290000000010": Decimal("9.90"),
    }


def test_pricefull_snapshot_then_single_item_delta_for_second_chain(
    conn, feeds_dir, mock_chain_metadata, create_store, test_price_partitions,
):
    chain_id = "8888888888888"
    store_id = "1"
    create_store(chain_id, store_id)
    parser = StoreXmlParser()

    load_one_file(
        conn, parser,
        feeds_dir / chain_id / store_id / "pricesfull"
        / "PriceFull8888888888888-001-001-20260101-000000.xml",
        feeds_dir, mock_chain_metadata, "PriceFull",
        log_changes=False,
    )

    assert _prices(conn, chain_id, store_id) == {
        "7290000000001": Decimal("7.90"),
        "7290000000002": Decimal("8.90"),
        "7290000000003": Decimal("14.90"),
        "7290000000004": Decimal("12.90"),
        "7290000000005": Decimal("9.90"),
    }

    load_one_file(
        conn, parser,
        feeds_dir / chain_id / store_id / "prices"
        / "Price8888888888888-001-001-20260101-000001.xml",
        feeds_dir, mock_chain_metadata, "Price",
        snapshot=False,
        log_changes=False,
    )

    prices = _prices(conn, chain_id, store_id)
    assert prices["7290000000001"] == Decimal("11.00")
    assert prices["7290000000002"] == Decimal("8.90")  # not reconciled, delta


def test_dedupe_keeps_latest_price_update_time(
    conn, mock_chain_metadata, create_store, tmp_path, test_price_partitions,
):
    chain_id = "9999999999999"
    store_id = "1"
    create_store(chain_id, store_id)

    xml = """<Root>
<ChainID>9999999999999</ChainID>
<SubChainID>001</SubChainID>
<StoreID>001</StoreID>
<BikoretNo>1</BikoretNo>
<Items>
<Item>
<PriceUpdateTime>2026-09-23T01:00:00</PriceUpdateTime>
<ItemCode>7290000000099</ItemCode>
<LastSaleDateTime>2026-09-23T01:00:00</LastSaleDateTime>
<ItemType>1</ItemType>
<ItemName>test dedupe</ItemName>
<ManufactureName>x</ManufactureName>
<ManufactureCountry>IL</ManufactureCountry>
<ManufactureItemDescription>x</ManufactureItemDescription>
<UnitQty>יחידה</UnitQty>
<Quantity>1.00</Quantity>
<UnitOfMeasure>יחידה</UnitOfMeasure>
<bIsWeighted>0</bIsWeighted>
<QtyInPackage>1</QtyInPackage>
<ItemPrice>5.00</ItemPrice>
<UnitOfMeasurePrice>5.00</UnitOfMeasurePrice>
<AllowDiscount>1</AllowDiscount>
<ItemStatus>1</ItemStatus>
</Item>
<Item>
<PriceUpdateTime>2026-09-23T02:00:00</PriceUpdateTime>
<ItemCode>7290000000099</ItemCode>
<LastSaleDateTime>2026-09-23T02:00:00</LastSaleDateTime>
<ItemType>1</ItemType>
<ItemName>test dedupe</ItemName>
<ManufactureName>x</ManufactureName>
<ManufactureCountry>IL</ManufactureCountry>
<ManufactureItemDescription>x</ManufactureItemDescription>
<UnitQty>יחידה</UnitQty>
<Quantity>1.00</Quantity>
<UnitOfMeasure>יחידה</UnitOfMeasure>
<bIsWeighted>0</bIsWeighted>
<QtyInPackage>1</QtyInPackage>
<ItemPrice>7.00</ItemPrice>
<UnitOfMeasurePrice>7.00</UnitOfMeasurePrice>
<AllowDiscount>1</AllowDiscount>
<ItemStatus>1</ItemStatus>
</Item>
</Items>
</Root>"""

    filepath = (
        tmp_path / chain_id / store_id / "prices"
        / "Price9999999999999-001-001-20260101-000002.xml"
    )
    filepath.parent.mkdir(parents=True)
    filepath.write_text(xml, encoding="utf-8")

    load_one_file(
        conn, StoreXmlParser(), filepath, tmp_path, mock_chain_metadata,
        "Price", snapshot=False, log_changes=False,
    )

    assert _prices(conn, chain_id, store_id)["7290000000099"] == Decimal("7.00")


def test_unsupported_file_type_raises(conn, mock_chain_metadata):
    with pytest.raises(ValueError):
        load_one_file(
            conn, StoreXmlParser(), Path("irrelevant.xml"),
            Path("."), mock_chain_metadata, "Bogus",
        )


def test_unknown_chain_is_skipped_not_raised(
    conn, mock_chain_metadata, tmp_path,
):
    xml = """<Root>
<ChainID>1231231231231</ChainID>
<SubChainID>001</SubChainID>
<StoreID>001</StoreID>
<BikoretNo>1</BikoretNo>
<Items>
<Item>
<PriceUpdateTime>2026-09-23T01:00:00</PriceUpdateTime>
<ItemCode>7290000000077</ItemCode>
<LastSaleDateTime>2026-09-23T01:00:00</LastSaleDateTime>
<ItemType>1</ItemType>
<ItemName>test</ItemName>
<ManufactureName>x</ManufactureName>
<ManufactureCountry>IL</ManufactureCountry>
<ManufactureItemDescription>x</ManufactureItemDescription>
<UnitQty>יחידה</UnitQty>
<Quantity>1.00</Quantity>
<UnitOfMeasure>יחידה</UnitOfMeasure>
<bIsWeighted>0</bIsWeighted>
<QtyInPackage>1</QtyInPackage>
<ItemPrice>5.00</ItemPrice>
<UnitOfMeasurePrice>5.00</UnitOfMeasurePrice>
<AllowDiscount>1</AllowDiscount>
<ItemStatus>1</ItemStatus>
</Item>
</Items>
</Root>"""

    filepath = (
        tmp_path / "1231231231231" / "1" / "prices"
        / "Price1231231231231-001-001-20260101-000000.xml"
    )
    filepath.parent.mkdir(parents=True)
    filepath.write_text(xml, encoding="utf-8")

    loaded = load_files(
        conn, [(filepath, "Price", False)], tmp_path, log_changes=False,
    )

    assert loaded == []