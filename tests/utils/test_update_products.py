from collections import defaultdict

from utils.resolve_canonical_name import resolve_canonical_name


def build_observations(products):
    """Build the same name/chain vote structure used by update_products."""
    observations = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    for product in products:
        observations[product["item_code"]][product["name"]][
            product["chain_id"]
        ] += 1

    return observations


def resolve_product_names(observations):
    """Resolve one canonical name for each item code."""
    return {
        item_code: resolve_canonical_name(name_chain_counts)
        for item_code, name_chain_counts in observations.items()
    }


def test_update_products_name_resolution():
    products = [
        {
            "item_code": "7290110115227",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_1",
        },
        {
            "item_code": "7290110115227",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_1",
        },
        {
            "item_code": "7290110115227",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_2",
        },
        {
            "item_code": "7290110115227",
            "name": "קולה זירו 1.5 ליטר",
            "chain_id": "chain_3",
        },
    ]

    observations = build_observations(products)
    canonical_names = resolve_product_names(observations)

    assert canonical_names["7290110115227"] == "קוקה קולה זירו 1.5 ליטר"


def test_update_products_chain_breadth_beats_store_frequency():
    products = [
        *[
            {
                "item_code": "ITEM_001",
                "name": "קוקה קולה זירו 1.5 ליטר",
                "chain_id": "chain_1",
            }
            for _ in range(100)
        ],
        {
            "item_code": "ITEM_001",
            "name": "קולה זירו 1.5 ליטר",
            "chain_id": "chain_2",
        },
        {
            "item_code": "ITEM_001",
            "name": "קולה זירו 1.5 ליטר",
            "chain_id": "chain_3",
        },
    ]

    observations = build_observations(products)
    canonical_names = resolve_product_names(observations)

    assert canonical_names["ITEM_001"] == "קולה זירו 1.5 ליטר"


def test_update_products_same_chain_accumulates_votes():
    products = [
        {
            "item_code": "ITEM_001",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_1",
        },
        {
            "item_code": "ITEM_001",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_1",
        },
        {
            "item_code": "ITEM_001",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_1",
        },
    ]

    observations = build_observations(products)

    assert (
        observations["ITEM_001"]["קוקה קולה זירו 1.5 ליטר"]["chain_1"]
        == 3
    )


def test_update_products_keeps_item_codes_separate():
    products = [
        {
            "item_code": "ITEM_001",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_1",
        },
        {
            "item_code": "ITEM_002",
            "name": "פפסי זירו 1.5 ליטר",
            "chain_id": "chain_1",
        },
    ]

    observations = build_observations(products)
    canonical_names = resolve_product_names(observations)

    assert canonical_names == {
        "ITEM_001": "קוקה קולה זירו 1.5 ליטר",
        "ITEM_002": "פפסי זירו 1.5 ליטר",
    }


def test_update_products_ignores_junk_name_when_valid_name_exists():
    products = [
        {
            "item_code": "ITEM_001",
            "name": "***",
            "chain_id": "chain_1",
        },
        {
            "item_code": "ITEM_001",
            "name": "קוקה קולה זירו 1.5 ליטר",
            "chain_id": "chain_2",
        },
    ]

    observations = build_observations(products)
    canonical_names = resolve_product_names(observations)

    assert canonical_names["ITEM_001"] == "קוקה קולה זירו 1.5 ליטר"