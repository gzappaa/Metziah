"""
models/chain.py

Defines the Chain data model used to represent supermarket chains.

Currently not used elsewhere in the project.
"""

from dataclasses import dataclass


@dataclass
class Chain:
    chain_id: str
    name: str