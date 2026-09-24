from utils.resolve_canonical_name import resolve_canonical_name


def test_resolve_canonical_name_coke_variants():
    names = [
        "** קוקה קולה זירו בק",
        "ZERO קולה 1.5 ליטר פיקדון",
        "משקה קוקה קולה זירו",
        "קולה 1.5 ZERO ליטר פיקדון",
        "קולה 1.5 ליטר ZERO",
        "קולה ZERO 1.5 ליטר פיקדון",
        "קולה זירו 1.5 ל' ידני",
        "קולה זירו 1.5 ליטר",
        "קולה זירו 1.5 ליטר פ",
        "קוקה קולה  1.5 ליטר",
        "קוקה קולה 1.5 ZERO פ",
        "קוקה קולה זירו 1.5 ל",
        "קוקה קולה זירו 1.5 ליטר",
        "קוקה קולה זירו 1.5 ליטר.",
        "קוקה קולה זירו zero",
        "קוקה קולה זירו בקבוק",
        "קוקה קולה זירו בקבוק - 1.5 ליטר",
        "קוקה- קולה zero",
        "קוקה- קולה זירו 1.5",
        "קוקה-קולה זירו 1.5 ל",
        "קוקה-קולה זירו בקבוק",
    ]

    name_chain_counts = {
        name: {f"chain_{i}": 1}
        for i, name in enumerate(names)
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result
    assert result in names


def test_resolve_canonical_name_prefers_chain_breadth():
    name_chain_counts = {
        "קוקה קולה זירו 1.5 ליטר": {
            "chain_1": 10,
            "chain_2": 8,
        },
        "קולה זירו 1.5 ליטר": {
            "chain_3": 1,
        },
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == "קוקה קולה זירו 1.5 ליטר"


def test_resolve_canonical_name_prefers_votes_when_chain_breadth_ties():
    name_chain_counts = {
        "קוקה קולה זירו 1.5 ליטר": {
            "chain_1": 10,
        },
        "קולה זירו 1.5 ליטר": {
            "chain_2": 3,
        },
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == "קוקה קולה זירו 1.5 ליטר"


def test_resolve_canonical_name_rejects_all_junk():
    name_chain_counts = {
        "***": {"chain_1": 10},
        "###": {"chain_2": 5},
        "---": {"chain_3": 2},
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == ""


def test_resolve_canonical_name_empty_input():
    assert resolve_canonical_name({}) == ""


def test_resolve_canonical_name_single_candidate():
    name_chain_counts = {
        "קוקה קולה זירו 1.5 ליטר": {
            "chain_1": 1,
        }
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == "קוקה קולה זירו 1.5 ליטר"


def test_resolve_canonical_name_quality_prefers_better_name_in_same_cluster():
    name_chain_counts = {
        "** קוקה קולה זירו 1.5 ליטר": {
            "chain_1": 5,
        },
        "קוקה קולה זירו 1.5 ליטר": {
            "chain_1": 5,
        },
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == "קוקה קולה זירו 1.5 ליטר"


def test_resolve_canonical_name_quality_gate_removes_bad_candidate():
    name_chain_counts = {
        "***": {
            "chain_1": 100,
            "chain_2": 100,
        },
        "קוקה קולה זירו 1.5 ליטר": {
            "chain_3": 1,
        },
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == "קוקה קולה זירו 1.5 ליטר"


def test_resolve_canonical_name_combines_chain_breadth_across_token_order_variants():
    name_chain_counts = {
        "קולה זירו 1.5 ליטר": {
            "chain_1": 1,
        },
        "1.5 ליטר קולה זירו": {
            "chain_2": 1,
        },
        "מוצר פשוט": {
            "chain_3": 1,
        },
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result in {
        "קולה זירו 1.5 ליטר",
        "1.5 ליטר קולה זירו",
    }

def test_resolve_canonical_name_token_multiplicity_matters():
    name_chain_counts = {
        "קולה קולה זירו 1.5 ליטר": {
            "chain_1": 1,
            "chain_2": 1,
        },
        "קולה זירו 1.5 ליטר": {
            "chain_3": 1,
        },
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == "קולה קולה זירו 1.5 ליטר"



def test_resolve_canonical_name_chain_breadth_beats_quality():
    name_chain_counts = {
        "קולה": {
            "chain_1": 1,
            "chain_2": 1,
            "chain_3": 1,
        },
        "קוקה קולה זירו 1.5 ליטר": {
            "chain_4": 1,
        },
    }

    result = resolve_canonical_name(name_chain_counts)

    assert result == "קולה"