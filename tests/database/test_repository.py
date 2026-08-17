from database.repository import (
    _resolve_fill_only,
    _resolve_name,
)


def test_resolve_name_blank_incoming():
    assert _resolve_name("Original", 3, "") == ("Original", 3)
    assert _resolve_name("Original", 3, None) == ("Original", 3)


def test_resolve_name_matching_incoming():
    assert _resolve_name("Original", 3, "Original") == ("Original", 4)


def test_resolve_name_different_incoming():
    assert _resolve_name("Original", 3, "New") == ("Original", 2)


def test_resolve_name_switches_when_count_reaches_zero():
    assert _resolve_name("Original", 1, "New") == ("New", 1)


def test_resolve_name_empty_existing():
    assert _resolve_name(None, 0, "New") == ("New", 1)


def test_resolve_fill_only_keeps_existing_value():
    assert _resolve_fill_only("Original", "New") == "Original"


def test_resolve_fill_only_accepts_incoming_when_empty():
    assert _resolve_fill_only(None, "New") == "New"


def test_resolve_fill_only_ignores_blank_incoming():
    assert _resolve_fill_only("Original", "") == "Original"
    assert _resolve_fill_only(None, "") is None





