from dataclasses import dataclass



@dataclass
class Store:
    chain_id: str
    store_id: str

    name: str

    address: str | None = None
    city: str | None = None
    zip_code: str | None = None

    latitude: float | None = None
    longitude: float | None = None