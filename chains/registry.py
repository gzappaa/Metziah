# chains/registry.py
from dataclasses import dataclass


@dataclass(frozen=True)
class ChainConfig:
    chain_id: str
    name: str
    method: str = "api"  # "api" or "ftp" (Phase 3)


CHAINS = {
    "machsenei_hashuk": ChainConfig(
        chain_id="7290661400001",
        name="Machsenei Hashuk",
    ),
}