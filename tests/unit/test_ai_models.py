"""``ai/models.py``: the request, proposal, rationale, warning, and readiness
shapes the AI SEO feature passes between its own layers (AI SEO implementation
plan, PR3, item 1).

These are plain frozen dataclasses, not pydantic models: nothing here is
loaded from YAML or a config file (that is what earns pydantic its keep
elsewhere in this codebase, e.g. `config/listing.py`) -- a `SeoProposal` is
built by `ai/validation.py` from an already-parsed JSON mapping, one field at
a time, with its own multi-reason error reporting. A dataclass also makes
`Deadline`'s clock-dependent behaviour easy to test without pydantic's
validate-on-construct getting in the way.
"""

from __future__ import annotations

import time
from pathlib import Path

from etsy_listings.ai.models import (
    Deadline,
    GarmentContext,
    PhraseRationale,
    ProposalWarning,
    ProviderReadiness,
    RawProviderResult,
    SeoProposal,
    SeoRequest,
)


def _rationale(**overrides: object) -> PhraseRationale:
    defaults: dict[str, object] = {
        "phrase": "retro hiking shirt",
        "intent": "core_product",
        "reason": "names the product and its style directly",
        "used_in": ("title", "tags"),
    }
    defaults.update(overrides)
    return PhraseRationale(**defaults)  # type: ignore[arg-type]


def _proposal(**overrides: object) -> SeoProposal:
    defaults: dict[str, object] = {
        "titles": ("A", "B", "C"),
        "tags": tuple(f"tag {i}" for i in range(20)),
        "description_leads": ("lead one", "lead two", "lead three"),
        "rationale": tuple(_rationale() for _ in range(7)),
        "warnings": (),
        "observed_text": "",
    }
    defaults.update(overrides)
    return SeoProposal(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------- SeoRequest


def test_seo_request_carries_the_listing_context_the_prompt_needs() -> None:
    request = SeoRequest(
        brief="A retro hiking tee for trail lovers.",
        product_type="t-shirt",
        etsy_category="Clothing > Unisex Adult Clothing > Shirts",
        materials=("cotton",),
        colors=("black", "forest green"),
        garment=GarmentContext(brand="Comfort Colors", model="1717"),
        design_image=Path("designs/take-a-hike.png"),
    )
    assert request.garment.brand == "Comfort Colors"
    assert request.materials == ("cotton",)
    assert request.design_image == Path("designs/take-a-hike.png")


def test_seo_request_is_frozen() -> None:
    request = SeoRequest(
        brief="brief",
        product_type="t-shirt",
        etsy_category="cat",
        materials=(),
        colors=(),
        garment=GarmentContext(brand="", model=""),
        design_image=Path("designs/x.png"),
    )
    try:
        request.brief = "changed"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("SeoRequest must be immutable")


# --------------------------------------------------------------- SeoProposal


def test_seo_proposal_holds_exactly_the_agreed_shape() -> None:
    proposal = _proposal()
    assert len(proposal.titles) == 3
    assert len(proposal.tags) == 20
    assert len(proposal.description_leads) == 3
    assert len(proposal.rationale) == 7
    assert proposal.warnings == ()
    assert proposal.observed_text == ""


def test_proposal_warning_defaults_to_general_kind() -> None:
    warning = ProposalWarning(message="uncertain about the intended recipient")
    assert warning.kind == "general"


def test_proposal_warning_can_be_a_trademark_kind() -> None:
    warning = ProposalWarning(message="mentions a third-party character name", kind="trademark")
    assert warning.kind == "trademark"


# --------------------------------------------------------------- Deadline


def test_deadline_starting_now_has_the_full_budget_remaining() -> None:
    # A tiny epsilon on the upper bound: `deadline_at` is `time.monotonic() +
    # 60` computed once, then `remaining_seconds()` subtracts a *second*,
    # slightly later `time.monotonic()` reading from it. The true result is
    # always < 60, but float64 rounding of that first addition (monotonic()
    # on a long-uptime machine is already a large number of seconds, so `+
    # 60` loses precision in its low bits) can round the difference a few
    # ULPs *above* 60.0 even though it is mathematically smaller -- a real,
    # previously-observed flake (e.g. `60.00000000000006 <= 60.0`), not a
    # sign of a slow test runner.
    deadline = Deadline.starting_now(seconds=60)
    assert 59.0 < deadline.remaining_seconds() <= 60.0 + 1e-6
    assert not deadline.expired


def test_deadline_reports_expired_once_its_budget_has_passed() -> None:
    deadline = Deadline.starting_now(seconds=0)
    time.sleep(0.01)
    assert deadline.expired
    assert deadline.remaining_seconds() == 0.0


def test_deadline_remaining_seconds_never_goes_negative() -> None:
    deadline = Deadline.starting_now(seconds=-5)
    assert deadline.remaining_seconds() == 0.0


# --------------------------------------------------------------- readiness / raw result


def test_provider_readiness_ready_carries_no_reason_by_default() -> None:
    readiness = ProviderReadiness(ready=True)
    assert readiness.reason is None


def test_provider_readiness_not_ready_names_why() -> None:
    readiness = ProviderReadiness(ready=False, reason="codex executable not found on PATH")
    assert not readiness.ready
    assert "codex" in (readiness.reason or "")


def test_raw_provider_result_carries_the_provider_name_and_its_raw_output() -> None:
    result = RawProviderResult(provider="codex", raw_output='{"titles": []}')
    assert result.provider == "codex"
    assert result.raw_output == '{"titles": []}'
