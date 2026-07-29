from dataclasses import dataclass


@dataclass
class Product:
    chain_id: str
    barcode: str
    name: str
    price: float
    unit: str | None = None