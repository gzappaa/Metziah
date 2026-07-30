from dataclasses import dataclass


@dataclass
class Product:
    chain_id: str
    sub_chain_id: str
    store_id: str
    item_code: str
    name: str
    price: float
    unit: str | None