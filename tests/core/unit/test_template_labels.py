"""The label rules (spec *Labels*): what a new label is saved as, what refuses
it, and why a label the template already holds is left alone. Messages are the
spec's words, which the Labels bar shows the seller."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etsy_listings.core.config.template_labels import (
    TemplateLabelRefusedError,
    saved_labels,
)

CHARACTERS = "Letters, numbers, spaces, hyphens and colons only"
LENGTH = "Labels can be up to 30 characters"
COLON = "Use one colon with text on both sides, like theme:christmas"
COUNT = "Templates hold up to 10 labels"


@pytest.mark.parametrize(
    ("typed", "saved"),
    [
        ("Theme:Christmas", "theme:christmas"),
        ("  flat lay  ", "flat lay"),
        ("shot:flat   lay", "shot:flat lay"),
        ("t-shirt", "t-shirt"),
        ("2 for 1", "2 for 1"),
    ],
)
def test_a_new_label_is_saved_lower_case_with_its_spaces_tidied(typed: str, saved: str) -> None:
    assert saved_labels([typed], held=[]) == [saved]


@pytest.mark.parametrize(
    ("typed", "message"),
    [
        ("santa!", CHARACTERS),
        ("café", CHARACTERS),
        ("snake_case", CHARACTERS),
        ("   ", CHARACTERS),
        ("a" * 31, LENGTH),
        ("theme:", COLON),
        (":christmas", COLON),
        (":", COLON),
        ("theme: ", COLON),
        ("a:b:c", COLON),
    ],
)
def test_a_new_label_breaking_a_rule_is_refused_naming_it(typed: str, message: str) -> None:
    with pytest.raises(TemplateLabelRefusedError) as refused:
        saved_labels([typed], held=[])

    assert str(refused.value) == message


def test_the_length_limit_is_read_after_tidying() -> None:
    assert saved_labels(["  " + "a" * 30 + "  "], held=[]) == ["a" * 30]


def test_the_eleventh_label_is_refused() -> None:
    ten = [f"label {number}" for number in range(10)]

    with pytest.raises(TemplateLabelRefusedError) as refused:
        saved_labels([*ten, "one more"], held=ten)

    assert str(refused.value) == COUNT


def test_ten_labels_fit() -> None:
    ten = [f"label {number}" for number in range(10)]

    assert saved_labels(ten, held=[]) == ten


def test_duplicates_are_dropped_keeping_the_first_in_place() -> None:
    assert saved_labels(["cosy", "Cosy", "model:male", " cosy "], held=[]) == ["cosy", "model:male"]


def test_a_new_label_tidying_to_a_held_one_is_a_duplicate() -> None:
    assert saved_labels(["cosy", "COSY"], held=["cosy"]) == ["cosy"]


def test_a_duplicate_does_not_count_towards_the_limit() -> None:
    ten = [f"label {number}" for number in range(10)]

    assert saved_labels([*ten, "LABEL 3"], held=ten) == ten


def test_a_held_label_breaking_the_rules_is_kept_as_written() -> None:
    """A hand edit must never block a save: only what the template did not
    already hold is tidied or checked (spec *Storage*)."""
    assert saved_labels(["Bad_Label!", "cosy"], held=["Bad_Label!"]) == ["Bad_Label!", "cosy"]


def test_a_template_over_the_limit_by_hand_still_saves_and_can_lose_labels() -> None:
    twelve = [f"label {number}" for number in range(12)]

    assert saved_labels(twelve, held=twelve) == twelve
    assert saved_labels(twelve[:11], held=twelve) == twelve[:11]


def test_a_template_over_the_limit_by_hand_takes_no_new_label() -> None:
    twelve = [f"label {number}" for number in range(12)]

    with pytest.raises(TemplateLabelRefusedError) as refused:
        saved_labels([*twelve[:11], "new"], held=twelve)

    assert str(refused.value) == COUNT


def test_removing_every_label_saves_none() -> None:
    assert saved_labels([], held=["cosy"]) == []


RULES = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "label_rules.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(("typed", "saved"), RULES["saved"])
def test_the_shared_cases_save_as_the_labels_bar_expects(typed: str, saved: str) -> None:
    assert saved_labels([typed], held=[]) == [saved]


@pytest.mark.parametrize(("typed", "message"), RULES["refused"])
def test_the_shared_cases_refuse_as_the_labels_bar_expects(typed: str, message: str) -> None:
    with pytest.raises(TemplateLabelRefusedError) as refused:
        saved_labels([typed], held=[])

    assert str(refused.value) == message


def test_the_shared_cap_message_is_the_servers() -> None:
    labels = [f"label {number}" for number in range(11)]

    with pytest.raises(TemplateLabelRefusedError) as refused:
        saved_labels(labels, held=[])

    assert str(refused.value) == RULES["cap_message"]
