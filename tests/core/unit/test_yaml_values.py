"""`yaml_values`: comparing and three-way merging parsed YAML as a reader sees it."""

from __future__ import annotations

from etsy_listings.core.workspace.yaml_values import merge, same


def test_one_one_point_oh_and_true_are_three_different_values_in_a_file() -> None:
    assert not same(1, 1.0)
    assert not same(1, True)
    assert not same({"a": [1]}, {"a": [1.0]})


def test_key_order_is_not_a_difference() -> None:
    assert same({"a": 1, "b": 2}, {"b": 2, "a": 1})


def test_a_merge_keeps_what_the_seller_wrote_that_the_change_did_not_touch() -> None:
    source = {"price": 25, "note": "mine"}
    before = {"price": "25.00"}

    assert merge(source, before, {"price": "25.00"}) is source
    assert merge(source, before, {"price": "30.00"}) == {"price": "30.00", "note": "mine"}


def test_a_key_the_change_adds_lands_after_its_nearest_present_predecessor() -> None:
    source = {"a": 1, "c": 3, "z": 26}
    before = {"a": 1, "c": 3}

    merged = merge(source, before, {"a": 1, "b": 2, "c": 3})

    assert list(merged) == ["a", "b", "c", "z"]


def test_a_key_with_no_present_predecessor_lands_last() -> None:
    merged = merge({"z": 26}, {}, {"a": 1})

    assert list(merged) == ["z", "a"]
