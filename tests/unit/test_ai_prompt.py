"""``ai/prompt.py``: the packaged default prompt, the setup seed operation,
and delimited-context prompt assembly (AI SEO implementation plan, PR3,
items 2-4).

`seed_prompt` is the one seam `setupcmd` needs (see
`test_setup_logic.py`'s own AI-prompt tests): create a prompt file when
absent, warn and leave a seller's file exactly alone otherwise. Everything
else here is pure string/JSON assembly, so it is tested directly against
string fixtures rather than a workspace.
"""

from __future__ import annotations

import json
from pathlib import Path

from etsy_listings.ai.models import GarmentContext, SeoRequest
from etsy_listings.ai.prompt import (
    CONTEXT_BEGIN,
    CONTEXT_END,
    RESPONSE_SCHEMA,
    SCHEMA_BEGIN,
    SCHEMA_END,
    SeedResult,
    build_prompt,
    build_repair_prompt,
    default_seo_prompt_text,
    seed_prompt,
)


def _request(**overrides: object) -> SeoRequest:
    defaults: dict[str, object] = {
        "brief": "A retro hiking tee that says TAKE A HIKE across the chest.",
        "product_type": "t-shirt",
        "etsy_category": "Clothing > Unisex Adult Clothing > Shirts",
        "materials": ("cotton",),
        "colors": ("black", "forest green"),
        "garment": GarmentContext(brand="Comfort Colors", model="1717"),
        "design_image": Path("designs/take-a-hike.png"),
    }
    defaults.update(overrides)
    return SeoRequest(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------- default prompt text


def test_default_seo_prompt_text_requires_the_complete_proposal_contract() -> None:
    """Item 2: the packaged default is updated from the `seo_prompt.md` draft
    to ask for the full contract -- three titles, 20 tags, three leads, seven
    rationale entries, warnings, and observed OCR text -- not the draft's
    single title/13-tag/one-sentence shape."""
    text = default_seo_prompt_text()
    assert "three independent title options" in text
    assert "exactly 20 tags" in text
    assert "three independent description-lead options" in text
    assert "exactly seven priority search phrases" in text
    assert '"titles"' in text
    assert '"tags"' in text
    assert '"description_leads"' in text
    assert '"rationale"' in text
    assert '"warnings"' in text
    assert '"observed_text"' in text


def test_default_seo_prompt_text_is_stable_plain_text_not_a_template() -> None:
    """The application appends context; the prompt itself supports no
    placeholders or executable prompt code (implementation plan, "Prompt")."""
    text = default_seo_prompt_text()
    assert "{" not in text.split("# Output", 1)[0]
    assert text == default_seo_prompt_text()


# --------------------------------------------------------------- seeding


def test_seed_prompt_creates_the_file_when_absent(tmp_path: Path) -> None:
    target = tmp_path / "prompts" / "seo.md"

    result = seed_prompt(target, default_seo_prompt_text())

    assert result == SeedResult(created=True, path=target)
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == default_seo_prompt_text()


def test_seed_prompt_leaves_a_sellers_file_exactly_alone(tmp_path: Path) -> None:
    target = tmp_path / "prompts" / "seo.md"
    target.parent.mkdir(parents=True)
    target.write_text("My own house style.\n", encoding="utf-8")

    result = seed_prompt(target, default_seo_prompt_text())

    assert result == SeedResult(created=False, path=target)
    assert target.read_text(encoding="utf-8") == "My own house style.\n"


def test_seed_prompt_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "prompts" / "seo.md"

    first = seed_prompt(target, default_seo_prompt_text())
    second = seed_prompt(target, default_seo_prompt_text())

    assert first.created
    assert not second.created


# --------------------------------------------------------------- prompt assembly


def test_build_prompt_wraps_the_context_in_its_own_delimiters() -> None:
    prompt = build_prompt("Seller instructions.", _request())

    assert prompt.startswith("Seller instructions.")
    assert CONTEXT_BEGIN in prompt
    assert CONTEXT_END in prompt
    assert prompt.index(CONTEXT_BEGIN) < prompt.index(CONTEXT_END)


def test_build_prompt_context_matches_the_drafted_listing_shape() -> None:
    prompt = build_prompt("Seller instructions.", _request())
    raw_context = prompt.split(CONTEXT_BEGIN, 1)[1].split(CONTEXT_END, 1)[0].strip()
    context = json.loads(raw_context)

    assert context == {
        "listing": {
            "brief": "A retro hiking tee that says TAKE A HIKE across the chest.",
            "product_type": "t-shirt",
            "etsy_category": "Clothing > Unisex Adult Clothing > Shirts",
            "materials": ["cotton"],
            "colors": ["black", "forest green"],
            "garment": {"brand": "Comfort Colors", "model": "1717"},
        }
    }


def test_build_prompt_appends_the_response_schema() -> None:
    prompt = build_prompt("Seller instructions.", _request())

    assert SCHEMA_BEGIN in prompt
    assert SCHEMA_END in prompt
    raw_schema = prompt.split(SCHEMA_BEGIN, 1)[1].split(SCHEMA_END, 1)[0].strip()
    assert json.loads(raw_schema) == RESPONSE_SCHEMA


def test_response_schema_requires_every_contract_field() -> None:
    assert set(RESPONSE_SCHEMA["required"]) == {
        "titles",
        "tags",
        "description_leads",
        "rationale",
        "warnings",
        "observed_text",
    }
    assert RESPONSE_SCHEMA["properties"]["titles"]["minItems"] == 3
    assert RESPONSE_SCHEMA["properties"]["titles"]["maxItems"] == 3
    assert RESPONSE_SCHEMA["properties"]["tags"]["minItems"] == 20
    assert RESPONSE_SCHEMA["properties"]["tags"]["maxItems"] == 20
    assert RESPONSE_SCHEMA["properties"]["description_leads"]["minItems"] == 3
    assert RESPONSE_SCHEMA["properties"]["rationale"]["minItems"] == 7
    assert RESPONSE_SCHEMA["properties"]["rationale"]["maxItems"] == 7


def test_build_prompt_uses_the_sellers_prompt_text_verbatim_not_the_default() -> None:
    """`prompts/seo.md` is seller-editable; the application must never
    silently fall back to the packaged default when a seller's own prompt is
    handed in (implementation plan, "Prompt")."""
    prompt = build_prompt("Completely different house rules.", _request())
    assert "Completely different house rules." in prompt
    assert "You create SEO copy proposals" not in prompt


# --------------------------------------------------------------- repair prompt


def test_build_repair_prompt_lists_every_reason() -> None:
    reasons = ["tags: expected exactly 20 unique tags, got 19", "titles[1]: empty"]
    repair = build_repair_prompt(reasons)

    for reason in reasons:
        assert reason in repair


def test_build_repair_prompt_asks_for_json_only() -> None:
    repair = build_repair_prompt(["some reason"])
    assert "JSON" in repair
