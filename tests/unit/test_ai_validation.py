"""``ai/validation.py``: normalize harmless formatting, then hard-validate a
provider's raw JSON output against the agreed proposal contract before any
UI response ever sees it (AI SEO implementation plan, PR3, item 5).

Every hard-validation reason is collected, not just the first -- the one
allowed same-provider repair (implementation plan, "Timeout and retries")
gets the best chance of fixing everything at once only if it is told
everything that was wrong. Trademark findings never raise: they attach as
warnings on the built proposal (settled decision: "Trademark findings are
warnings, not a hard refusal").
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from etsy_listings.ai.models import ProposalWarning
from etsy_listings.ai.validation import ProposalValidationError, validate_proposal
from etsy_listings.config.listing import MAX_TAG_LENGTH, MAX_TITLE_LENGTH


def _rationale(phrase: str = "retro hiking shirt", **overrides: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "phrase": phrase,
        "intent": "core_product",
        "reason": "names the product and its style directly",
        "used_in": ["title", "tags"],
    }
    item.update(overrides)
    return item


def _valid_raw(**overrides: object) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "titles": [
            "Retro Hiking Tee: Take a Hike Graphic T-Shirt",
            "Mountain Trail T-Shirt for Hikers",
            "Take a Hike Vintage Style Hiking Shirt",
        ],
        "tags": [f"hiking tag {i}" for i in range(20)],
        "description_leads": [
            "A relaxed heavyweight tee printed with a retro hiking graphic for the trail.",
            "This hiking t-shirt features a bold vintage-style mountain design on the chest.",
            "A soft cotton tee printed with a hand-drawn take a hike graphic for trail lovers.",
        ],
        "rationale": [_rationale(f"phrase {i}") for i in range(7)],
        "warnings": [],
        "observed_text": "TAKE A HIKE",
    }
    raw.update(overrides)
    return raw


def _assert_reason_matches(raw: Mapping[str, Any], *, contains: str) -> None:
    with pytest.raises(ProposalValidationError) as exc_info:
        validate_proposal(raw)
    assert any(contains in reason for reason in exc_info.value.reasons), exc_info.value.reasons


# --------------------------------------------------------------- a valid proposal


def test_a_valid_proposal_builds_the_full_contract_shape() -> None:
    proposal = validate_proposal(_valid_raw())

    assert len(proposal.titles) == 3
    assert len(proposal.tags) == 20
    assert len(proposal.description_leads) == 3
    assert len(proposal.rationale) == 7
    assert proposal.observed_text == "TAKE A HIKE"
    assert proposal.warnings == ()


def test_the_first_thirteen_tags_are_best_13_by_position() -> None:
    """Ranking is the tags array's own order -- there is no separate rank
    field to keep in sync with it."""
    raw = _valid_raw(tags=[f"tag {i:02d}" for i in range(20)])
    proposal = validate_proposal(raw)
    assert proposal.tags[:13] == tuple(f"tag {i:02d}" for i in range(13))


# --------------------------------------------------------------- normalization ("repairable")


def test_normalization_trims_whitespace_and_strips_wrapping_quotes() -> None:
    """A response that is only cosmetically malformed becomes valid without
    ever reaching a hard-validation failure or a repair round-trip."""
    raw = _valid_raw(
        titles=[
            '  "Retro Hiking Tee: Take a Hike Graphic T-Shirt"  ',
            "Mountain Trail T-Shirt for Hikers",
            "Take a Hike Vintage Style Hiking Shirt",
        ]
    )
    proposal = validate_proposal(raw)
    assert proposal.titles[0] == "Retro Hiking Tee: Take a Hike Graphic T-Shirt"


def test_normalization_collapses_internal_whitespace_runs() -> None:
    raw = _valid_raw(
        description_leads=[
            "A relaxed   heavyweight tee   printed with a retro hiking graphic for the trail.",
            "This hiking t-shirt features a bold vintage-style mountain design on the chest.",
            "A soft cotton tee printed with a hand-drawn take a hike graphic for trail lovers.",
        ]
    )
    proposal = validate_proposal(raw)
    assert "  " not in proposal.description_leads[0]


# --------------------------------------------------------------- exact counts


@pytest.mark.parametrize(
    ("field", "value", "contains"),
    [
        ("titles", ["only one"], "titles"),
        ("description_leads", ["one", "two"], "description_leads"),
        ("tags", [f"tag {i}" for i in range(19)], "tags"),
        ("rationale", [_rationale(f"p{i}") for i in range(6)], "rationale"),
    ],
)
def test_wrong_counts_are_hard_validation_failures(
    field: str, value: object, contains: str
) -> None:
    _assert_reason_matches(_valid_raw(**{field: value}), contains=contains)


# --------------------------------------------------------------- Etsy limits


def test_a_title_over_etsys_character_limit_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["titles"][0] = "x" * (MAX_TITLE_LENGTH + 1)
    _assert_reason_matches(raw, contains="140")


def test_a_tag_over_etsys_character_limit_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["tags"][0] = "x" * (MAX_TAG_LENGTH + 1)
    _assert_reason_matches(raw, contains="20")


def test_an_empty_title_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["titles"][0] = "   "
    _assert_reason_matches(raw, contains="titles[0]")


# --------------------------------------------------------------- uniqueness


def test_duplicate_tags_ignoring_case_are_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["tags"] = ["Hiking Tee", *[f"tag {i}" for i in range(18)], "hiking tee"]
    _assert_reason_matches(raw, contains="unique")


# --------------------------------------------------------------- rationale shape


def test_a_rationale_item_with_an_unknown_intent_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["rationale"][0]["intent"] = "clickbait"
    _assert_reason_matches(raw, contains="intent")


def test_a_rationale_item_with_an_unknown_used_in_value_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["rationale"][0]["used_in"] = ["homepage"]
    _assert_reason_matches(raw, contains="used_in")


def test_a_rationale_item_missing_a_phrase_is_a_hard_failure() -> None:
    raw = _valid_raw()
    del raw["rationale"][0]["phrase"]
    _assert_reason_matches(raw, contains="phrase")


def test_a_rationale_item_with_a_blank_reason_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["rationale"][0]["reason"] = "   "
    _assert_reason_matches(raw, contains="rationale[0].reason")


# --------------------------------------------------------------- affiliation/content


@pytest.mark.parametrize("term", ["official", "licensed", "endorsed", "authentic", "sponsored"])
def test_affiliation_claiming_words_are_a_hard_failure(term: str) -> None:
    raw = _valid_raw()
    raw["titles"][0] = f"Officially {term.title()} Hiking Tee"
    _assert_reason_matches(raw, contains="affiliation")


def test_affiliation_words_are_checked_case_insensitively_across_every_field() -> None:
    raw = _valid_raw()
    raw["description_leads"][1] = "This is the OFFICIAL hiking tee for trail lovers everywhere."
    _assert_reason_matches(raw, contains="affiliation")


def test_affiliation_words_in_tags_are_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["tags"][0] = "official hiking tee"
    _assert_reason_matches(raw, contains="tags: claims affiliation")


def test_affiliation_check_ignores_a_non_string_entry_in_titles_or_leads() -> None:
    """A wrong-typed entry is already reported by the shape check; the
    affiliation scan must skip it rather than crash on it."""
    raw = _valid_raw()
    raw["titles"][0] = 12345
    with pytest.raises(ProposalValidationError) as exc_info:
        validate_proposal(raw)
    assert not any("affiliation" in reason for reason in exc_info.value.reasons)


# --------------------------------------------------------------- trademark: warning only


def test_a_known_trademark_name_is_a_warning_not_a_failure() -> None:
    raw = _valid_raw()
    raw["titles"][0] = "Disney Hiking Tee: Take a Hike Graphic T-Shirt"

    proposal = validate_proposal(raw)

    assert any(w.kind == "trademark" for w in proposal.warnings)
    assert any("Disney" in w.message for w in proposal.warnings)


def test_provider_supplied_warnings_are_kept_as_general_warnings() -> None:
    raw = _valid_raw(warnings=["the intended recipient is not stated in the brief"])
    proposal = validate_proposal(raw)
    assert (
        ProposalWarning(message="the intended recipient is not stated in the brief", kind="general")
        in proposal.warnings
    )


def test_trademark_and_general_warnings_can_both_be_present() -> None:
    raw = _valid_raw(warnings=["uncertain about garment weight"])
    raw["tags"][0] = "nike style tee"

    proposal = validate_proposal(raw)

    kinds = {w.kind for w in proposal.warnings}
    assert kinds == {"trademark", "general"}


# --------------------------------------------------------------- structural / type failures


@pytest.mark.parametrize("field", ["titles", "tags", "description_leads", "warnings", "rationale"])
def test_a_field_that_is_not_a_list_at_all_is_a_hard_failure(field: str) -> None:
    """A provider that returns a single string, or an object, instead of an
    array must fail the same way a wrong-count array does, not raise a
    `TypeError` out of this module."""
    _assert_reason_matches(_valid_raw(**{field: "not a list"}), contains=field)


def test_a_rationale_entry_that_is_not_an_object_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["rationale"][0] = "just a phrase, not an object"
    _assert_reason_matches(raw, contains="rationale[0]")


def test_a_non_string_entry_inside_a_string_list_is_a_hard_failure() -> None:
    raw = _valid_raw()
    raw["tags"][0] = 42
    _assert_reason_matches(raw, contains="tags[0]")


def test_affiliation_check_skips_fields_that_are_not_lists() -> None:
    """The affiliation scan degrades gracefully when a field already failed
    its own shape check -- it must not itself raise while the rest of hard
    validation is still collecting every other reason."""
    raw = _valid_raw(titles="not a list", tags="not a list either")
    with pytest.raises(ProposalValidationError) as exc_info:
        validate_proposal(raw)
    assert not any("affiliation" in reason for reason in exc_info.value.reasons)


def test_a_missing_top_level_field_is_a_hard_failure() -> None:
    raw = _valid_raw()
    del raw["observed_text"]
    _assert_reason_matches(raw, contains="observed_text")


def test_a_non_string_observed_text_is_a_hard_failure() -> None:
    raw = _valid_raw(observed_text=None)
    _assert_reason_matches(raw, contains="observed_text")


def test_multiple_simultaneous_failures_are_all_collected() -> None:
    raw = _valid_raw(titles=["only one"], tags=[f"tag {i}" for i in range(19)])
    with pytest.raises(ProposalValidationError) as exc_info:
        validate_proposal(raw)
    reasons = exc_info.value.reasons
    assert any("titles" in r for r in reasons)
    assert any("tags" in r for r in reasons)
    assert len(reasons) >= 2


def test_validation_error_message_joins_every_reason() -> None:
    raw = _valid_raw(titles=["only one"])
    with pytest.raises(ProposalValidationError) as exc_info:
        validate_proposal(raw)
    for reason in exc_info.value.reasons:
        assert reason in str(exc_info.value)
