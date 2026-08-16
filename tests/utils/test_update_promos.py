import gzip
from pathlib import Path
from decimal import Decimal

from utils.update_promos import load_files


CHAIN_ID = "7290661400001"
STORE_ID = "097"
PROMOTION_ID = "1462415"
ITEM_CODE = "7290008464598"


def create_promo_xml(
    path: Path,
    update_time: str = "2026-08-16T12:00:00.000",
    discounted_price: str = "5.01",
    discount_rate: str = "40.00",
    discounted_price_per_mida: str = "1.52",
):
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Root>
    <ChainID>{CHAIN_ID}</ChainID>
    <SubChainID>003</SubChainID>
    <StoreID>{STORE_ID}</StoreID>
    <BikoretNo>0</BikoretNo>

    <Promotions>
        <Promotion>
            <PromotionUpdateTime>{update_time}</PromotionUpdateTime>
            <AllowMultipleDiscounts>0</AllowMultipleDiscounts>
            <PromotionID>{PROMOTION_ID}</PromotionID>
            <PromotionDescription>*TEST PROMOTION</PromotionDescription>
            <PromotionStartDateTime>2026-08-16T00:00:00.000</PromotionStartDateTime>
            <PromotionEndDateTime>2026-08-21T00:00:00.000</PromotionEndDateTime>
            <PromotionStartHour/>
            <PromotionEndHour/>
            <PromotionDays/>
            <RedemptionLimit>4</RedemptionLimit>
            <MinNoOfItemOffered>10</MinNoOfItemOffered>
            <ClubID>0</ClubID>
            <IsGiftItem>4</IsGiftItem>
            <AdditionalIsCoupon>0</AdditionalIsCoupon>
            <AdditionalRestrictions/>
            <Remarks/>

            <Groups>
                <Group>
                    <GroupID>1</GroupID>
                    <MinPurchaseAmount>0</MinPurchaseAmount>
                    <DiscountType/>

                    <PromotionItems>
                        <PromotionItem>
                            <ItemCode>{ITEM_CODE}</ItemCode>
                            <ItemType>1</ItemType>
                            <RewardType>3</RewardType>
                            <MinQty>1</MinQty>
                            <MaxQty/>
                            <DiscountRate>{discount_rate}</DiscountRate>
                            <DiscountedPrice>{discounted_price}</DiscountedPrice>
                            <DiscountedPricePerMida>{discounted_price_per_mida}</DiscountedPricePerMida>
                            <bIsWeighted>0</bIsWeighted>
                        </PromotionItem>
                    </PromotionItems>
                </Group>
            </Groups>
        </Promotion>
    </Promotions>
</Root>
"""

    with gzip.open(path, "wb") as f:
        f.write(xml.encode("utf-8"))


def test_promo_updates_existing_promotion_item(conn, tmp_path):
    feeds_dir = tmp_path / "feeds"

    promo_dir = (
        feeds_dir
        / CHAIN_ID
        / "003"
        / STORE_ID
        / "promos"
    )

    promo_dir.mkdir(parents=True)

    filepath = (
        promo_dir
        / "Promo7290661400001-003-097-20260816-120000.gz"
    )

    create_promo_xml(filepath)

    # Prepare deterministic initial promotion state.
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE promotion_items
            SET
                discounted_price = %s,
                discount_rate = %s
            WHERE chain_id = %s
              AND store_id = %s
              AND promotion_id = %s
              AND group_id = %s
              AND item_code = %s
            """,
            (
                Decimal("4.20"),
                Decimal("52.44"),
                CHAIN_ID,
                STORE_ID,
                PROMOTION_ID,
                "1",
                ITEM_CODE,
            ),
        )

    conn.commit()

    # Verify initial promotion state.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT discounted_price
            FROM promotion_items
            WHERE chain_id = %s
              AND store_id = %s
              AND promotion_id = %s
              AND group_id = %s
              AND item_code = %s
            """,
            (
                CHAIN_ID,
                STORE_ID,
                PROMOTION_ID,
                "1",
                ITEM_CODE,
            ),
        )

        row = cur.fetchone()

    assert row is not None
    assert row[0] == Decimal("4.20")

    # Verify regular price before Promo loading.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT price
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                CHAIN_ID,
                STORE_ID,
                ITEM_CODE,
            ),
        )

        row = cur.fetchone()

    assert row is not None
    assert row[0] == Decimal("8.50")

    # Run the real Promo loader.
    loaded_files = load_files(
        conn,
        [(filepath, "Promo")],
        feeds_dir,
        log_changes=False,
    )

    assert loaded_files == [filepath]

    # Verify promotion was updated.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                discounted_price,
                discount_rate
            FROM promotion_items
            WHERE chain_id = %s
              AND store_id = %s
              AND promotion_id = %s
              AND group_id = %s
              AND item_code = %s
            """,
            (
                CHAIN_ID,
                STORE_ID,
                PROMOTION_ID,
                "1",
                ITEM_CODE,
            ),
        )

        row = cur.fetchone()

    assert row is not None

    discounted_price, discount_rate = row

    assert discounted_price == Decimal("5.01")
    assert discount_rate == Decimal("40.00")

    # Promo loading must NOT modify the regular product price.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT price
            FROM prices
            WHERE chain_id = %s
              AND store_id = %s
              AND item_code = %s
            """,
            (
                CHAIN_ID,
                STORE_ID,
                ITEM_CODE,
            ),
        )

        row = cur.fetchone()

    assert row is not None
    assert row[0] == Decimal("8.50")


def test_promo_multiple_updates_keep_latest_values(conn, tmp_path):
    feeds_dir = tmp_path / "feeds"

    promo_dir = (
        feeds_dir
        / CHAIN_ID
        / "003"
        / STORE_ID
        / "promos"
    )

    promo_dir.mkdir(parents=True)

    # First Promo: 10:00
    filepath_1 = (
        promo_dir
        / "Promo7290661400001-003-097-20260816-100000.gz"
    )

    create_promo_xml(
        filepath_1,
        update_time="2026-08-16T10:00:00.000",
        discounted_price="5.01",
        discount_rate="40.00",
        discounted_price_per_mida="1.52",
    )

    # Second Promo: 11:00
    filepath_2 = (
        promo_dir
        / "Promo7290661400001-003-097-20260816-110000.gz"
    )

    create_promo_xml(
        filepath_2,
        update_time="2026-08-16T11:00:00.000",
        discounted_price="4.50",
        discount_rate="50.00",
        discounted_price_per_mida="1.36",
    )

    # Load both Promo files in chronological order.
    loaded_files = load_files(
        conn,
        [
            (filepath_1, "Promo"),
            (filepath_2, "Promo"),
        ],
        feeds_dir,
        log_changes=False,
    )

    assert loaded_files == [
        filepath_1,
        filepath_2,
    ]

    # The latest Promo must be the final database state.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                discounted_price,
                discount_rate,
                discounted_price_per_mida
            FROM promotion_items
            WHERE chain_id = %s
              AND store_id = %s
              AND promotion_id = %s
              AND group_id = %s
              AND item_code = %s
            """,
            (
                CHAIN_ID,
                STORE_ID,
                PROMOTION_ID,
                "1",
                ITEM_CODE,
            ),
        )

        row = cur.fetchone()

    assert row is not None

    discounted_price, discount_rate, discounted_price_per_mida = row

    assert discounted_price == Decimal("4.50")
    assert discount_rate == Decimal("50.00")
    assert discounted_price_per_mida == Decimal("1.36")