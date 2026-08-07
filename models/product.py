from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class Product:
    chain_id: str
    sub_chain_id: str
    store_id: str

    item_code: str
    name: str

    price: Decimal
    unit_price: Decimal

    quantity: Decimal
    unit_qty: str
    unit_measure: str

    manufacturer: str | None
    manufacturer_country: str | None

    price_update_time: datetime | None
    last_sale_datetime: datetime | None

    weighted: bool
    allow_discount: bool

    item_type: int | None
    package_quantity: int | None
    status: str | None