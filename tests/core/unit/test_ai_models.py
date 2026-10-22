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

from pathlib import Path
from types import SimpleNamespace

import pytest

from etsy_listings.core.ai import models as models_module
from etsy_listings.core.ai.models import (
    Deadline,
    GarmentContext,
    ProposalWarning,
    ProviderReadiness,
    RawProviderResult,
    SeoRequest,
)

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


# --------------------------------------------------------------- ProposalWarning


def test_proposal_warning_defaults_to_general_kind() -> None:
    warning = ProposalWarning(message="uncertain about the intended recipient")
    assert warning.kind == "general"


def test_proposal_warning_can_be_a_trademark_kind() -> None:
    warning = ProposalWarning(message="mentions a third-party character name", kind="trademark")
    assert warning.kind == "trademark"


# --------------------------------------------------------------- Deadline


class _Clock:
    """A monotonic clock the test moves by hand: no sleeps, no epsilons."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock(1_000.0)
    monkeypatch.setattr(models_module, "time", SimpleNamespace(monotonic=fake))
    return fake


def test_deadline_starting_now_has_the_full_budget_remaining(clock: _Clock) -> None:
    deadline = Deadline.starting_now(seconds=60)

    assert deadline.remaining_seconds() == 60.0
    assert not deadline.expired


def test_deadline_counts_down_on_the_monotonic_clock(clock: _Clock) -> None:
    deadline = Deadline.starting_now(seconds=60)

    clock.now = 1_059.5  # just before the cutoff
    assert deadline.remaining_seconds() == 0.5
    assert not deadline.expired


def test_deadline_expires_exactly_at_its_cutoff(clock: _Clock) -> None:
    deadline = Deadline.starting_now(seconds=60)

    clock.now = 1_060.0
    assert deadline.remaining_seconds() == 0.0
    assert deadline.expired


def test_deadline_remaining_seconds_never_goes_negative(clock: _Clock) -> None:
    deadline = Deadline.starting_now(seconds=60)

    clock.now = 1_075.0  # well past the cutoff
    assert deadline.remaining_seconds() == 0.0
    assert deadline.expired
    assert Deadline.starting_now(seconds=-5).remaining_seconds() == 0.0


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
