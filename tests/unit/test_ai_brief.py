"""``ai/brief.py``: the packaged default `prompts/brief.md`, the task a
provider is handed, and the hard validation a drafted brief passes before it
can reach a listing's Brief field (PRD 68).

Pure string/JSON assembly and validation, so it is tested directly against
fixtures rather than a workspace -- the same split `test_ai_prompt.py` draws
for the SEO side. What a *provider* does with the task is
`test_ai_codex.py`/`test_ai_claude.py`'s subject, and what the chain does
around it is `test_ai_orchestrator.py`'s.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.ai.brief import (
    BRIEF_RESPONSE_SCHEMA,
    MAX_BRIEF_LENGTH,
    BriefRequest,
    BriefValidationError,
    DesignBrief,
    build_brief_task,
    default_brief_prompt_text,
    validate_brief,
)
from etsy_listings.ai.prompt import CONTEXT_BEGIN, CONTEXT_END, SCHEMA_BEGIN, SCHEMA_END


def _request() -> BriefRequest:
    return BriefRequest(design_image=Path("designs/take-a-hike.png"))


# ------------------------------------------------------------ packaged prompt


def test_the_packaged_prompt_is_plain_seller_editable_prose() -> None:
    text = default_brief_prompt_text()

    assert text.strip()
    # No placeholder syntax: the settled "Prompt" decision is that the
    # application *appends* delimited context, never substitutes into the
    # seller's own text.
    assert "{{" not in text
    assert CONTEXT_BEGIN not in text


def test_the_packaged_prompt_asks_for_the_design_text_verbatim() -> None:
    """The one thing this brief exists to capture that OCR alone gets wrong
    -- `ai/models.py.SeoRequest` leans on the brief for exactly this."""
    assert "exactly" in default_brief_prompt_text().lower()


def test_the_packaged_prompt_is_read_fresh_each_call() -> None:
    assert default_brief_prompt_text() == default_brief_prompt_text()


# ---------------------------------------------------------------------- task


def test_the_task_carries_the_seller_prompt_the_context_and_the_schema() -> None:
    task = build_brief_task("My house style.", _request())

    assert task.prompt_text.startswith("My house style.")
    assert SCHEMA_BEGIN in task.prompt_text
    assert SCHEMA_END in task.prompt_text
    assert task.response_schema == BRIEF_RESPONSE_SCHEMA
    assert task.design_image == Path("designs/take-a-hike.png")


def test_the_image_is_the_whole_input() -> None:
    """A brief describes the artwork, so nothing about the listing -- not its
    colours, not its category, and not its garment -- goes in with it. The
    garment used to, and it made a garment profile a hard prerequisite for a
    draft the prompt forbade from mentioning the garment at all. There is no
    context block rather than an empty one: an empty delimited block is one
    more thing for a model to decide means something."""
    task = build_brief_task("prompt", _request())

    assert CONTEXT_BEGIN not in task.prompt_text
    assert CONTEXT_END not in task.prompt_text


# ---------------------------------------------------------------- validation


def test_a_well_formed_response_becomes_a_design_brief() -> None:
    brief = validate_brief({"brief": 'Retro sunset mountains reading "TAKE A HIKE".'})

    assert brief == DesignBrief(brief='Retro sunset mountains reading "TAKE A HIKE".')


def test_surrounding_and_internal_whitespace_is_normalised_away() -> None:
    """A leading newline, or a model that wrapped its paragraph, is a
    formatting difference -- not something worth spending the one repair
    attempt on."""
    brief = validate_brief({"brief": "\n  Retro sunset\n  mountains.  \n"})

    assert brief.brief == "Retro sunset mountains."


def test_a_non_object_response_is_refused() -> None:
    with pytest.raises(BriefValidationError) as excinfo:
        validate_brief(["brief"])

    assert excinfo.value.reasons == ("response: expected a JSON object",)


def test_a_missing_or_non_string_brief_is_refused() -> None:
    with pytest.raises(BriefValidationError) as excinfo:
        validate_brief({"brief": 12})

    assert excinfo.value.reasons == ("brief: expected a string",)

    with pytest.raises(BriefValidationError):
        validate_brief({})


def test_an_empty_brief_is_refused_rather_than_written_to_the_listing() -> None:
    with pytest.raises(BriefValidationError) as excinfo:
        validate_brief({"brief": "   \n "})

    assert excinfo.value.reasons == ("brief: must not be empty",)


def test_an_over_long_brief_is_refused_rather_than_truncated() -> None:
    """A truncated brief reads as a complete one, and would be silently
    wrong about the design."""
    with pytest.raises(BriefValidationError) as excinfo:
        validate_brief({"brief": "x" * (MAX_BRIEF_LENGTH + 1)})

    assert "over the" in excinfo.value.reasons[0]
    assert str(MAX_BRIEF_LENGTH) in excinfo.value.reasons[0]


def test_a_brief_exactly_at_the_limit_is_accepted() -> None:
    assert validate_brief({"brief": "x" * MAX_BRIEF_LENGTH}).brief == "x" * MAX_BRIEF_LENGTH
