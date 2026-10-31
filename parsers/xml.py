"""
parsers/xml.py

Parses supermarket XML feed files into Metziah domain models.

Handles:
- Price files into Product objects
- Promotion files into Promotion, PromotionGroup, and PromotionItem objects
- Multiple retailer-specific promotion XML layouts normalized into one model
- Case-insensitive XML tag normalization
- Feed-specific decimal, integer, and datetime normalization
- Malformed item/promotion handling without discarding the entire file
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from models.promo import Promotion, PromotionGroup, PromotionItem
from models.product import Product


logger = logging.getLogger(__name__)


class StoreXmlParser:

    @staticmethod
    def normalize_xml_tags(root):
        """
        Normalize all XML element tag names to lowercase.

        This makes the parser accept inconsistent capitalization such as:
        - PromotionID
        - PromotionId
        - promotionid
        - Promotionid

        All become:
            promotionid
        """
        for element in root.iter():
            if isinstance(element.tag, str):
                element.tag = element.tag.lower()

    def parse_price_file(self, xml_content):
        root = etree.fromstring(xml_content)
        self.normalize_xml_tags(root)

        products = []

        chain_id = root.findtext("chainid")
        sub_chain_id = root.findtext("subchainid")
        store_id = root.findtext("storeid")

        chain_id = chain_id.strip() if chain_id else None
        sub_chain_id = (
            sub_chain_id.strip()
            if sub_chain_id
            else None
        )
        store_id = store_id.strip() if store_id else None

        for item in root.findall("./items/item"):

            item_code = item.findtext("itemcode")

            try:
                products.append(
                    Product(
                        chain_id=chain_id,
                        sub_chain_id=sub_chain_id,
                        store_id=store_id,

                        item_code=item_code,
                        name=item.findtext("itemname"),

                        price=self.parse_decimal(
                            item.findtext("itemprice"),
                            "ItemPrice",
                        ),

                        unit_price=self.parse_decimal(
                            item.findtext("unitofmeasureprice"),
                            "UnitOfMeasurePrice",
                        ),

                        quantity=self.parse_decimal(
                            item.findtext("quantity"),
                            "Quantity",
                        ),

                        unit_qty=item.findtext("unitqty"),
                        unit_measure=item.findtext("unitofmeasure"),

                        manufacturer=item.findtext("manufacturename"),
                        manufacturer_country=item.findtext(
                            "manufacturecountry"
                        ),

                        price_update_time=self.parse_datetime(
                            item.findtext("priceupdatetime")
                        ),

                        last_sale_datetime=self.parse_datetime(
                            item.findtext("lastsaledatetime")
                        ),

                        weighted=(
                            item.findtext("bisweighted") == "1"
                        ),

                        allow_discount=(
                            item.findtext("allowdiscount") == "1"
                        ),

                        item_type=self.parse_int(
                            item.findtext("itemtype")
                        ),

                        package_quantity=self.parse_int(
                            item.findtext("qtyinpackage")
                        ),

                        status=item.findtext("itemstatus") or None,
                    )
                )

            except Exception as e:
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

    def parse_promo_file(self, xml_content):
        root = etree.fromstring(xml_content)
        self.normalize_xml_tags(root)

        chain_id = root.findtext("chainid")
        sub_chain_id = root.findtext("subchainid")
        store_id = root.findtext("storeid")

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
            ".//promotions/promotion"
        ):

            promotion_id = promo_el.findtext("promotionid")

            try:
                if not promotion_id:
                    logger.warning(
                        "Skipping promotion with missing promotion_id "
                        "(chain_id=%s store_id=%s description=%s)",
                        chain_id,
                        store_id,
                        promo_el.findtext(
                            "promotiondescription"
                        ),
                    )
                    continue

                if promotion_id not in promotions:

                    start_datetime = self.parse_datetime(
                        promo_el.findtext(
                            "promotionstartdatetime"
                        )
                    )

                    if start_datetime is None:
                        start_datetime = self.parse_date_and_hour(
                            promo_el.findtext(
                                "promotionstartdate"
                            ),
                            promo_el.findtext(
                                "promotionstarthour"
                            ),
                        )

                    end_datetime = self.parse_datetime(
                        promo_el.findtext(
                            "promotionenddatetime"
                        )
                    )

                    if end_datetime is None:
                        end_datetime = self.parse_date_and_hour(
                            promo_el.findtext(
                                "promotionenddate"
                            ),
                            promo_el.findtext(
                                "promotionendhour"
                            ),
                        )

                    update_time = self.parse_datetime(
                        promo_el.findtext(
                            "promotionupdatetime"
                        )
                    )

                    if update_time is None:
                        update_time = self.parse_datetime(
                            promo_el.findtext(
                                "promotionupdatedate"
                            )
                        )

                    min_no_of_items_offered = (
                        self.parse_int(
                            promo_el.findtext(
                                "minnoofitemoffered"
                            )
                        )
                        or self.parse_int(
                            promo_el.findtext(
                                "minnoofitemsoffered"
                            )
                        )
                        or self.parse_int(
                            promo_el.findtext(
                                "minnoofitemofered"
                            )
                        )
                    )

                    promotions[promotion_id] = Promotion(
                        chain_id=chain_id,
                        promotion_id=promotion_id,
                        store_id=store_id,

                        description=promo_el.findtext(
                            "promotiondescription"
                        ),

                        start_datetime=start_datetime,
                        end_datetime=end_datetime,

                        start_hour=(
                            promo_el.findtext(
                                "promotionstarthour"
                            )
                            or None
                        ),

                        end_hour=(
                            promo_el.findtext(
                                "promotionendhour"
                            )
                            or None
                        ),

                        promotion_days=(
                            promo_el.findtext(
                                "promotiondays"
                            )
                            or None
                        ),

                        update_time=update_time,

                        club_id=promo_el.findtext(
                            "clubid"
                        ),

                        is_gift_item=promo_el.findtext(
                            "isgiftitem"
                        ),

                        additional_is_coupon=(
                            promo_el.findtext(
                                "additionaliscoupon"
                            )
                            == "1"
                        ),

                        allow_multiple_discounts=(
                            promo_el.findtext(
                                "allowmultiplediscounts"
                            )
                            == "1"
                        ),

                        redemption_limit=self.parse_int(
                            promo_el.findtext(
                                "redemptionlimit"
                            )
                        ),

                        min_no_of_items_offered=(
                            min_no_of_items_offered
                        ),

                        additional_restrictions=(
                            promo_el.findtext(
                                "additionalrestrictions"
                            )
                            or None
                        ),

                        remarks=(
                            promo_el.findtext(
                                "remarks"
                            )
                            or ""
                        ).strip() or None,
                    )

                    groups_by_promo[promotion_id] = {}

                promotion = promotions[promotion_id]
                groups = groups_by_promo[promotion_id]

                # ----------------------------------------------------
                # Schema 1:
                #
                # Promotion
                #   Groups
                #     Group
                #       GroupID
                #       PromotionItems
                #         PromotionItem
                #
                # Preserve explicit group IDs.
                # ----------------------------------------------------

                group_elements = promo_el.findall(
                    "./groups/group"
                )

                if group_elements:

                    for group_el in group_elements:

                        group_id = group_el.findtext(
                            "groupid"
                        )

                        # A group without an ID cannot be represented
                        # directly by the database model. Normalize it
                        # into synthetic group 1.
                        if not group_id:
                            group_id = "1"

                        if group_id not in groups:

                            group = PromotionGroup(
                                chain_id=chain_id,
                                promotion_id=promotion_id,
                                store_id=store_id,
                                group_id=group_id,

                                min_purchase_amount=(
                                    self.parse_optional_decimal(
                                        group_el.findtext(
                                            "minpurchaseamount"
                                        )
                                    )
                                ),

                                discount_type=(
                                    group_el.findtext(
                                        "discounttype"
                                    )
                                    or None
                                ),
                            )

                            groups[group_id] = group
                            promotion.groups.append(group)

                        else:
                            group = groups[group_id]

                        for item_el in group_el.findall(
                            "./promotionitems/promotionitem"
                        ):
                            self._append_promotion_item(
                                group=group,
                                item_el=item_el,
                                chain_id=chain_id,
                                promotion_id=promotion_id,
                                store_id=store_id,
                            )

                else:
                    # ------------------------------------------------
                    # Schemas 2 and 3:
                    #
                    # Promotion
                    #   PromotionItems
                    #     PromotionItem
                    #
                    # or:
                    #
                    # Promotion
                    #   PromotionItems
                    #     Item
                    #
                    # Neither provides an explicit group ID.
                    # Normalize all items into group 1.
                    # ------------------------------------------------

                    item_elements = promo_el.findall(
                        "./promotionitems/promotionitem"
                    )

                    item_elements.extend(
                        promo_el.findall(
                            "./promotionitems/item"
                        )
                    )

                    if item_elements:

                        group_id = "1"

                        group = groups.get(group_id)

                        if group is None:

                            min_purchase_amount = (
                                self.parse_optional_decimal(
                                    promo_el.findtext(
                                        "minpurchaseamount"
                                    )
                                )

                                or self.parse_optional_decimal(
                                    promo_el.findtext(
                                        "minpurchaseamnt"
                                    )
                                )
                            )

                            group = PromotionGroup(
                                chain_id=chain_id,
                                promotion_id=promotion_id,
                                store_id=store_id,
                                group_id=group_id,
                                min_purchase_amount=(
                                    min_purchase_amount
                                ),
                                discount_type=(
                                    promo_el.findtext(
                                        "discounttype"
                                    )
                                    or None
                                ),
                            )

                            groups[group_id] = group
                            promotion.groups.append(group)

                        for item_el in item_elements:

                            self._append_promotion_item(
                                group=group,
                                item_el=item_el,
                                chain_id=chain_id,
                                promotion_id=promotion_id,
                                store_id=store_id,
                                promotion_el=promo_el,
                            )

            except Exception as e:
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

    def _append_promotion_item(
        self,
        group,
        item_el,
        chain_id,
        promotion_id,
        store_id,
        promotion_el=None,
    ):
        """
        Parse a promotion item and append it to an existing group.

        Some feeds store promotion values directly on PromotionItem,
        while other feeds store them on the parent Promotion and only
        provide ItemCode/ItemType on the individual Item element.
        """

        try:

            def findtext(name):
                value = item_el.findtext(name)

                if value is None and promotion_el is not None:
                    value = promotion_el.findtext(name)

                return value

            is_weighted = (
                item_el.findtext("bisweighted")
                or item_el.findtext("blsweighted")
            )

            if is_weighted is None and promotion_el is not None:
                is_weighted = promotion_el.findtext(
                    "isweightedpromo"
                )

            group.items.append(
                PromotionItem(
                    chain_id=chain_id,
                    promotion_id=promotion_id,
                    store_id=store_id,
                    group_id=group.group_id,

                    item_code=findtext(
                        "itemcode"
                    ),

                    item_type=self.parse_int(
                        findtext("itemtype")
                    ),

                    reward_type=self.parse_int(
                        findtext("rewardtype")
                    ),

                    min_qty=self.parse_optional_decimal(
                        findtext("minqty")
                    ),

                    max_qty=self.parse_optional_decimal(
                        findtext("maxqty")
                    ),

                    discount_rate=self.parse_optional_decimal(
                        findtext("discountrate")
                    ),

                    discounted_price=(
                        self.parse_optional_decimal(
                            findtext("discountedprice")
                        )
                    ),

                    discounted_price_per_mida=(
                        self.parse_optional_decimal(
                            findtext(
                                "discountedpricepermida"
                            )
                        )
                    ),

                    is_weighted=(
                        is_weighted == "1"
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
                group.group_id,
                item_el.findtext("itemcode"),
                e,
            )

    def parse_datetime(self, value):
        if not value:
            return None

        value = value.strip()

        if not value:
            return None

        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def parse_date_and_hour(
        self,
        date_value,
        hour_value,
    ):
        if not date_value:
            return None

        date_value = date_value.strip()

        if not date_value:
            return None

        hour_value = (
            hour_value.strip()
            if hour_value
            else "00:00:00"
        )

        if not hour_value:
            hour_value = "00:00:00"

        value = f"{date_value} {hour_value}"

        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ):
            try:
                return datetime.strptime(
                    value,
                    fmt,
                )
            except ValueError:
                continue

        return None

    def parse_decimal(
        self,
        value,
        field_name="Decimal",
    ):
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

    def parse_int(self, value):
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
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        value = value.removeprefix("כ").strip()

        try:
            return Decimal(value)
        except InvalidOperation:
            return None