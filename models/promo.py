from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class Promotion:
    chain_id: str
    promotion_id: str

    description: str | None

    start_datetime: datetime | None
    end_datetime: datetime | None
    start_hour: str | None
    end_hour: str | None
    promotion_days: str | None
    update_time: datetime | None

    club_id: str | None
    is_gift_item: str | None  # kept as str -- unexplained decimal values (e.g. '3.4') pending investigation

    additional_is_coupon: bool | None
    allow_multiple_discounts: bool | None

    redemption_limit: int | None
    min_no_of_items_offered: int | None

    additional_restrictions: str | None
    remarks: str | None

    groups: list["PromotionGroup"] = field(default_factory=list)


@dataclass
class PromotionGroup:
    chain_id: str
    promotion_id: str
    store_id: str
    group_id: str

    min_purchase_amount: Decimal | None
    discount_type: str | None

    items: list["PromotionItem"] = field(default_factory=list)


@dataclass
class PromotionItem:
    chain_id: str
    promotion_id: str
    store_id: str
    group_id: str

    item_code: str
    item_type: int | None
    reward_type: int | None

    min_qty: Decimal | None
    max_qty: Decimal | None

    discount_rate: Decimal | None
    discounted_price: Decimal | None
    discounted_price_per_mida: Decimal | None

    is_weighted: bool | None