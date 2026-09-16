import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree
from models.promo import Promotion, PromotionGroup, PromotionItem
from models.product import Product

logger = logging.getLogger(__name__)


class StoreXmlParser:

    def parse_price_file(self, xml_content):
        root = etree.fromstring(xml_content)

        products = []

        chain_id = (
            root.findtext("ChainID")
            or root.findtext("ChainId")
        )

        sub_chain_id = (
            root.findtext("SubChainID")
            or root.findtext("SubChainId")
        )

        store_id = (
            root.findtext("StoreID")
            or root.findtext("StoreId")
        )

        chain_id = chain_id.strip() if chain_id else None
        sub_chain_id = (
            sub_chain_id.strip()
            if sub_chain_id
            else None
        )
        store_id = store_id.strip() if store_id else None

        for item in root.findall("./Items/Item"):

            item_code = item.findtext("ItemCode")

            try:
                products.append(
                    Product(
                        chain_id=chain_id,
                        sub_chain_id=sub_chain_id,
                        store_id=store_id,

                        item_code=item_code,
                        name=item.findtext("ItemName"),

                        price=self.parse_decimal(
                            item.findtext("ItemPrice"),
                            "ItemPrice",
                        ),

                        unit_price=self.parse_decimal(
                            item.findtext("UnitOfMeasurePrice"),
                            "UnitOfMeasurePrice",
                        ),

                        quantity=self.parse_decimal(
                            item.findtext("Quantity"),
                            "Quantity",
                        ),

                        unit_qty=item.findtext("UnitQty"),
                        unit_measure=item.findtext("UnitOfMeasure"),

                        manufacturer=item.findtext("ManufactureName"),
                        manufacturer_country=item.findtext(
                            "ManufactureCountry"
                        ),

                        price_update_time=self.parse_datetime(
                            item.findtext("PriceUpdateTime")
                        ),

                        last_sale_datetime=self.parse_datetime(
                            item.findtext("LastSaleDateTime")
                        ),

                        weighted=(
                            item.findtext("bIsWeighted") == "1"
                        ),

                        allow_discount=(
                            item.findtext("AllowDiscount") == "1"
                        ),

                        # Feed placeholders such as "לא ידוע"
                        # represent missing integer data.
                        item_type=self.parse_int(
                            item.findtext("ItemType")
                        ),

                        # Unknown or missing package quantities become None.
                        package_quantity=self.parse_int(
                            item.findtext("QtyInPackage")
                        ),

                        status=item.findtext("ItemStatus") or None,
                    )
                )

            except Exception as e:
                # A malformed item should not discard the entire file.
                logger.warning(
                    "Skipping malformed item "
                    "(chain_id=%s store_id=%s item_code=%s): %s",
                    chain_id,
                    store_id,
                    item_code,
                    e,
                )
                continue

        return products

    def parse_datetime(self, value):
        if not value:
            return None

        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            # Some feeds use invalid placeholder dates such as
            # 0000-00-00 00:00:00. Treat them as missing.
            return None

    def parse_decimal(self, value, field_name="Decimal"):
        """
        Convert a feed value to Decimal.

        Some feeds prefix quantities with the Hebrew character "כ".
        It is feed formatting and is not part of the numeric value.
        """
        if value is None:
            return Decimal("0")

        value = value.strip()

        if not value:
            return Decimal("0")

        value = value.removeprefix("כ").strip()

        try:
            return Decimal(value)
        except InvalidOperation:
            raise ValueError(
                f"Invalid {field_name} format: {value!r}"
            )

    def parse_promo_file(self, xml_content):
        root = etree.fromstring(xml_content)

        chain_id = (
            root.findtext("ChainID")
            or root.findtext("ChainId")
        )

        sub_chain_id = (
            root.findtext("SubChainID")
            or root.findtext("SubChainId")
        )

        store_id = (
            root.findtext("StoreID")
            or root.findtext("StoreId")
        )

        chain_id = chain_id.strip() if chain_id else None
        sub_chain_id = (
            sub_chain_id.strip()
            if sub_chain_id
            else None
        )
        store_id = store_id.strip() if store_id else None

        promotions: dict[str, Promotion] = {}
        groups_by_promo: dict[
            str,
            dict[str, PromotionGroup],
        ] = {}

        for promo_el in root.findall(
            ".//Promotions/Promotion"
        ):

            promotion_id = promo_el.findtext(
                "PromotionID"
            )

            try:
                if promotion_id not in promotions:

                    promotions[promotion_id] = Promotion(
                        chain_id=chain_id,
                        promotion_id=promotion_id,
                        store_id=store_id,

                        description=promo_el.findtext(
                            "PromotionDescription"
                        ),

                        start_datetime=self.parse_datetime(
                            promo_el.findtext(
                                "PromotionStartDateTime"
                            )
                        ),

                        end_datetime=self.parse_datetime(
                            promo_el.findtext(
                                "PromotionEndDateTime"
                            )
                        ),

                        start_hour=(
                            promo_el.findtext(
                                "PromotionStartHour"
                            )
                            or None
                        ),

                        end_hour=(
                            promo_el.findtext(
                                "PromotionEndHour"
                            )
                            or None
                        ),

                        promotion_days=(
                            promo_el.findtext(
                                "PromotionDays"
                            )
                            or None
                        ),

                        update_time=self.parse_datetime(
                            promo_el.findtext(
                                "PromotionUpdateTime"
                            )
                        ),

                        club_id=promo_el.findtext("ClubID"),
                        is_gift_item=promo_el.findtext(
                            "IsGiftItem"
                        ),

                        additional_is_coupon=(
                            promo_el.findtext(
                                "AdditionalIsCoupon"
                            )
                            == "1"
                        ),

                        allow_multiple_discounts=(
                            promo_el.findtext(
                                "AllowMultipleDiscounts"
                            )
                            == "1"
                        ),

                        redemption_limit=self.parse_int(
                            promo_el.findtext(
                                "RedemptionLimit"
                            )
                        ),

                        min_no_of_items_offered=self.parse_int(
                            promo_el.findtext(
                                "MinNoOfItemOffered"
                            )
                        ),

                        additional_restrictions=(
                            promo_el.findtext(
                                "AdditionalRestrictions"
                            )
                            or None
                        ),

                        remarks=(
                            promo_el.findtext("Remarks")
                            or ""
                        ).strip() or None,
                    )

                    groups_by_promo[promotion_id] = {}

                promotion = promotions[promotion_id]
                groups = groups_by_promo[promotion_id]

                for group_el in promo_el.findall(
                    "./Groups/Group"
                ):

                    group_id = group_el.findtext(
                        "GroupID"
                    )

                    if group_id not in groups:

                        group = PromotionGroup(
                            chain_id=chain_id,
                            promotion_id=promotion_id,
                            store_id=store_id,
                            group_id=group_id,

                            min_purchase_amount=(
                                self.parse_optional_decimal(
                                    group_el.findtext(
                                        "MinPurchaseAmount"
                                    )
                                )
                            ),

                            discount_type=(
                                group_el.findtext(
                                    "DiscountType"
                                )
                                or None
                            ),
                        )

                        groups[group_id] = group
                        promotion.groups.append(group)

                    else:
                        group = groups[group_id]

                    for item_el in group_el.findall(
                        "./PromotionItems/PromotionItem"
                    ):
                        try:
                            group.items.append(
                                PromotionItem(
                                    chain_id=chain_id,
                                    promotion_id=promotion_id,
                                    store_id=store_id,
                                    group_id=group_id,

                                    item_code=item_el.findtext(
                                        "ItemCode"
                                    ),

                                    # "לא ידוע" becomes None.
                                    item_type=self.parse_int(
                                        item_el.findtext(
                                            "ItemType"
                                        )
                                    ),

                                    reward_type=self.parse_int(
                                        item_el.findtext(
                                            "RewardType"
                                        )
                                    ),

                                    min_qty=(
                                        self.parse_optional_decimal(
                                            item_el.findtext(
                                                "MinQty"
                                            )
                                        )
                                    ),

                                    max_qty=(
                                        self.parse_optional_decimal(
                                            item_el.findtext(
                                                "MaxQty"
                                            )
                                        )
                                    ),

                                    discount_rate=(
                                        self.parse_optional_decimal(
                                            item_el.findtext(
                                                "DiscountRate"
                                            )
                                        )
                                    ),

                                    discounted_price=(
                                        self.parse_optional_decimal(
                                            item_el.findtext(
                                                "DiscountedPrice"
                                            )
                                        )
                                    ),

                                    discounted_price_per_mida=(
                                        self.parse_optional_decimal(
                                            item_el.findtext(
                                                "DiscountedPricePerMida"
                                            )
                                        )
                                    ),

                                    is_weighted=(
                                        item_el.findtext(
                                            "bIsWeighted"
                                        )
                                        == "1"
                                    ),
                                )
                            )

                        except Exception as e:
                            logger.warning(
                                "Skipping malformed promotion item "
                                "(chain_id=%s store_id=%s "
                                "promotion_id=%s group_id=%s "
                                "item_code=%s): %s",
                                chain_id,
                                store_id,
                                promotion_id,
                                group_id,
                                item_el.findtext("ItemCode"),
                                e,
                            )
                            continue

            except Exception as e:
                # One malformed promotion should not discard
                # the rest of the file.
                logger.warning(
                    "Skipping malformed promotion "
                    "(chain_id=%s store_id=%s promotion_id=%s): %s",
                    chain_id,
                    store_id,
                    promotion_id,
                    e,
                )
                continue

        return list(promotions.values())

    def parse_int(self, value):
        """
        Convert a feed value to an integer when possible.

        Feed placeholders such as "לא ידוע" represent missing
        numeric data and therefore become None.
        """
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def parse_optional_decimal(self, value):
        """
        Parse optional decimal fields.

        Unlike parse_decimal(), blank values become None because
        these fields distinguish missing from an actual zero.
        """
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        # Some feeds may use the same "כ" prefix in quantity-like
        # decimal fields.
        value = value.removeprefix("כ").strip()

        try:
            return Decimal(value)
        except InvalidOperation:
            return None