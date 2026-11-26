"""``parent_of``: the mapping a dotted settings key's last part lives in."""

from __future__ import annotations

from typing import Any

from etsy_listings.core.application.dotted_keys import parent_of


def test_an_existing_parent_is_answered_in_place() -> None:
    document: dict[str, Any] = {"batch_ai": {"concurrency": 2, "other": 1}}

    node, leaf = parent_of(document, "batch_ai.concurrency")

    assert leaf == "concurrency"
    assert node is document["batch_ai"]


def test_a_missing_parent_is_created_on_the_way_down() -> None:
    document: dict[str, Any] = {}

    node, leaf = parent_of(document, "a.b.c")
    node[leaf] = 1

    assert document == {"a": {"b": {"c": 1}}}


def test_a_parent_that_is_not_a_mapping_is_replaced_by_an_empty_one() -> None:
    document: dict[str, Any] = {"a": "scalar", "kept": True}

    node, leaf = parent_of(document, "a.b")
    node[leaf] = 1

    assert document == {"a": {"b": 1}, "kept": True}


def test_a_key_without_dots_lives_in_the_document_itself() -> None:
    document: dict[str, Any] = {}

    node, leaf = parent_of(document, "top")

    assert node is document
    assert leaf == "top"
