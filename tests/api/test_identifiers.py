"""Tests for shopper-facing product identifiers."""

import pytest

from api.service import (
    make_fresh_identifier,
    make_store_product_identifier,
    parse_product_identifier,
)


def test_fresh_identifier_round_trip() -> None:
    identifier = make_fresh_identifier("7290012345678")

    assert identifier == "fresh:7290012345678"
    assert parse_product_identifier(identifier) == {
        "type": "fresh",
        "item_code": "7290012345678",
    }


def test_store_product_identifier_round_trip() -> None:
    identifier = make_store_product_identifier(
        "7290661400001",
        "123",
        "item-456",
    )

    assert identifier == "sp:7290661400001:123:item-456"
    assert parse_product_identifier(identifier) == {
        "type": "store_product",
        "chain_id": "7290661400001",
        "store_id": "123",
        "item_code": "item-456",
    }


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "fresh:",
        "sp:",
        "sp:chain:store",
        "unknown:123",
        "fresh:7290012345678:extra",
        "sp::123:item",
        "sp:chain::item",
        "sp:chain:store:",
    ],
)
def test_invalid_identifiers_are_rejected(identifier: str) -> None:
    with pytest.raises(ValueError):
        parse_product_identifier(identifier)


@pytest.mark.parametrize("item_code", ["", " ", "item:extra"])
def test_fresh_identifier_rejects_invalid_item_code(
    item_code: str,
) -> None:
    with pytest.raises(ValueError):
        make_fresh_identifier(item_code)


@pytest.mark.parametrize(
    ("chain_id", "store_id", "item_code"),
    [
        ("", "123", "item"),
        ("chain", "", "item"),
        ("chain", "123", ""),
        ("chain:extra", "123", "item"),
        ("chain", "123:extra", "item"),
        ("chain", "123", "item:extra"),
    ],
)
def test_store_product_identifier_rejects_invalid_parts(
    chain_id: str,
    store_id: str,
    item_code: str,
) -> None:
    with pytest.raises(ValueError):
        make_store_product_identifier(chain_id, store_id, item_code)