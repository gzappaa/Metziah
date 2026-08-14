import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree
from models.promo import Promotion, PromotionGroup, PromotionItem
from models.product import Product

logger = logging.getLogger(__name__)


class MachseneiXmlParser:

    def parse_price_file(self, xml_content):

        root = etree.fromstring(xml_content)

        products = []

        chain_id = root.findtext("ChainID")
        sub_chain_id = root.findtext("SubChainID")
        store_id = root.findtext("StoreID")

        for item in root.findall("./Items/Item"):

            item_code = item.findtext("ItemCode")

            try:
                item_type_text = item.findtext("ItemType")
                qty_in_package_text = item.findtext("QtyInPackage")

                products.append(
                    Product(
                        chain_id=chain_id,
                        sub_chain_id=sub_chain_id,
                        store_id=store_id,

                        item_code=item_code,
                        name=item.findtext("ItemName"),

                        price=self.parse_decimal(
                            item.findtext("ItemPrice"), "ItemPrice"
                        ),

                        unit_price=self.parse_decimal(
                            item.findtext("UnitOfMeasurePrice"), "UnitOfMeasurePrice"
                        ),

                        quantity=self.parse_decimal(
                            item.findtext("Quantity"), "Quantity"
                        ),

                        unit_qty=item.findtext("UnitQty"),
                        unit_measure=item.findtext("UnitOfMeasure"),

                        manufacturer=item.findtext("ManufactureName"),
                        manufacturer_country=item.findtext("ManufactureCountry"),

                        price_update_time=self.parse_datetime(
                            item.findtext("PriceUpdateTime")
                        ),

                        last_sale_datetime=self.parse_datetime(
                            item.findtext("LastSaleDateTime")
                        ),

                        weighted=item.findtext("bIsWeighted") == "1",

                        allow_discount=item.findtext("AllowDiscount") == "1",

                        # ItemType=0 is a real, common value (seen ~1600 times),
                        # so we distinguish "present with value 0" from "tag missing"
                        # using presence (is not None), not truthiness.
                        item_type=(
                            int(item_type_text)
                            if item_type_text is not None else None
                        ),

                        # QtyInPackage never legitimately appears as 0 in real data,
                        # so a missing/empty tag maps cleanly to None instead of a
                        # fake 0 that could be confused with a real value later.
                        package_quantity=(
                            int(qty_in_package_text)
                            if qty_in_package_text else None
                        ),

                        status=item.findtext("ItemStatus") or None,
                    )
                )
            except Exception as e:
                # One malformed <Item> shouldn't take down the whole file --
                # every other item in this store's price file is still good
                # data and shouldn't be thrown away over one bad row.
                logger.warning(
                    "Skipping malformed item (chain_id=%s store_id=%s item_code=%s): %s",
                    chain_id, store_id, item_code, e,
                )
                continue

        return products


    def parse_datetime(self, value):
        if not value:
            return None

        try:
            return datetime.fromisoformat(value)
        except ValueError:
            # Some feeds send garbage placeholder dates (e.g. all-zero
            # "0000-00-00 00:00:00") for fields like LastSaleDateTime when
            # an item has never sold. That's not a real date -- treat it
            # as missing rather than crashing over one field.
            return None

    def parse_decimal(self, value, field_name):
        try:
            return Decimal(value or "0")
        except InvalidOperation:
            raise ValueError(
                f"Invalid {field_name} format: {value!r}"
            )



    def parse_promo_file(self, xml_content):

        root = etree.fromstring(xml_content)

        chain_id = root.findtext("ChainID")
        store_id = root.findtext("StoreID")

        promotions: dict[str, Promotion] = {}
        groups_by_promo: dict[str, dict[str, PromotionGroup]] = {}

        for promo_el in root.findall(".//Promotions/Promotion"):

            promotion_id = promo_el.findtext("PromotionID")

            try:
                if promotion_id not in promotions:

                    promotions[promotion_id] = Promotion(
                        chain_id=chain_id,
                        promotion_id=promotion_id,
                        store_id=store_id,

                        description=promo_el.findtext("PromotionDescription"),

                        start_datetime=self.parse_datetime(
                            promo_el.findtext("PromotionStartDateTime")
                        ),
                        end_datetime=self.parse_datetime(
                            promo_el.findtext("PromotionEndDateTime")
                        ),
                        start_hour=promo_el.findtext("PromotionStartHour") or None,
                        end_hour=promo_el.findtext("PromotionEndHour") or None,
                        promotion_days=promo_el.findtext("PromotionDays") or None,

                        update_time=self.parse_datetime(
                            promo_el.findtext("PromotionUpdateTime")
                        ),

                        club_id=promo_el.findtext("ClubID"),
                        is_gift_item=promo_el.findtext("IsGiftItem"),

                        additional_is_coupon=promo_el.findtext("AdditionalIsCoupon") == "1",
                        allow_multiple_discounts=promo_el.findtext("AllowMultipleDiscounts") == "1",

                        redemption_limit=self.parse_int(
                            promo_el.findtext("RedemptionLimit")
                        ),
                        min_no_of_items_offered=self.parse_int(
                            promo_el.findtext("MinNoOfItemOffered")
                        ),

                        additional_restrictions=promo_el.findtext("AdditionalRestrictions") or None,
                        remarks=(promo_el.findtext("Remarks") or "").strip() or None,
                    )
                    groups_by_promo[promotion_id] = {}

                promotion = promotions[promotion_id]
                groups = groups_by_promo[promotion_id]

                for group_el in promo_el.findall("./Groups/Group"):

                    group_id = group_el.findtext("GroupID")

                    if group_id not in groups:

                        group = PromotionGroup(
                            chain_id=chain_id,
                            promotion_id=promotion_id,
                            store_id=store_id,
                            group_id=group_id,

                            min_purchase_amount=self.parse_optional_decimal(
                                group_el.findtext("MinPurchaseAmount")
                            ),
                            discount_type=group_el.findtext("DiscountType") or None,
                        )
                        groups[group_id] = group
                        promotion.groups.append(group)

                    else:
                        group = groups[group_id]

                    for item_el in group_el.findall("./PromotionItems/PromotionItem"):

                        item_type_text = item_el.findtext("ItemType")
                        reward_type_text = item_el.findtext("RewardType")

                        group.items.append(
                            PromotionItem(
                                chain_id=chain_id,
                                promotion_id=promotion_id,
                                store_id=store_id,
                                group_id=group_id,

                                item_code=item_el.findtext("ItemCode"),

                                item_type=(
                                    int(item_type_text)
                                    if item_type_text is not None else None
                                ),
                                reward_type=(
                                    int(reward_type_text)
                                    if reward_type_text is not None else None
                                ),

                                min_qty=self.parse_optional_decimal(
                                    item_el.findtext("MinQty")
                                ),
                                max_qty=self.parse_optional_decimal(
                                    item_el.findtext("MaxQty")
                                ),
                                discount_rate=self.parse_optional_decimal(
                                    item_el.findtext("DiscountRate")
                                ),
                                discounted_price=self.parse_optional_decimal(
                                    item_el.findtext("DiscountedPrice")
                                ),
                                discounted_price_per_mida=self.parse_optional_decimal(
                                    item_el.findtext("DiscountedPricePerMida")
                                ),

                                is_weighted=item_el.findtext("bIsWeighted") == "1",
                            )
                        )

            except Exception as e:
                # Same reasoning as parse_price_file -- one malformed
                # <Promotion> shouldn't take down every other promo in
                # this store's file.
                logger.warning(
                    "Skipping malformed promotion (chain_id=%s store_id=%s promotion_id=%s): %s",
                    chain_id, store_id, promotion_id, e,
                )
                continue

        return list(promotions.values())

    def parse_int(self, value):
        if not value:
            return None
        return int(value)

    def parse_optional_decimal(self, value):
        # Unlike parse_decimal (used for price fields, where blank means
        # "treat as 0"), promo fields like MinPurchaseAmount/MinQty need
        # to distinguish "blank" from "genuinely 0" -- 0 is a real,
        # meaningful value here (e.g. MinQty=0 seen under RewardType=0),
        # so blank maps to None, not 0.
        if not value:
            return None
        try:
            return Decimal(value)
        except InvalidOperation:
            return None