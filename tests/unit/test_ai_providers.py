"""``ai/providers.py``: the narrow `SeoProvider` protocol later PRs' Codex
and Claude adapters implement (PR4), and `FakeSeoProvider`, the scriptable
double this PR's own contract fixtures and every later PR's orchestration
tests use instead (implementation plan, item 6: "no real CLI call is needed
in unit or CI tests")."""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.ai.models import (
    Deadline,
    GarmentContext,
    ProviderReadiness,
    SeoRequest,
)
from etsy_listings.ai.providers import FakeSeoProvider, SeoProvider


def _request() -> SeoRequest:
    return SeoRequest(
        brief="brief",
        product_type="t-shirt",
        etsy_category="cat",
        materials=(),
        colors=(),
        garment=GarmentContext(brand="", model=""),
        design_image=Path("designs/x.png"),
    )


def test_fake_provider_is_ready_by_default() -> None:
    provider = FakeSeoProvider(name="codex")
    assert provider.readiness() == ProviderReadiness(ready=True)


def test_fake_provider_readiness_is_configurable() -> None:
    provider = FakeSeoProvider(name="codex", ready=ProviderReadiness(ready=False, reason="no CLI"))
    assert provider.readiness() == ProviderReadiness(ready=False, reason="no CLI")


def test_fake_provider_returns_its_queued_response_and_records_the_request() -> None:
    provider = FakeSeoProvider(name="claude", responses=["raw output"])
    request = _request()

    result = provider.generate(request, Deadline.starting_now(seconds=60))

    assert result.provider == "claude"
    assert result.raw_output == "raw output"
    assert provider.requests == [request]


def test_fake_provider_pops_responses_in_order_for_repair_scenarios() -> None:
    """A malformed first response, then a repaired second one -- the shape
    the orchestration service's one-repair-attempt flow (PR4/5) exercises."""
    provider = FakeSeoProvider(name="codex", responses=["malformed", "{}"])
    deadline = Deadline.starting_now(seconds=60)

    first = provider.generate(_request(), deadline)
    second = provider.generate(_request(), deadline)

    assert first.raw_output == "malformed"
    assert second.raw_output == "{}"


def test_fake_provider_raises_when_asked_for_more_responses_than_queued() -> None:
    provider = FakeSeoProvider(name="codex", responses=[])
    with pytest.raises(AssertionError):
        provider.generate(_request(), Deadline.starting_now(seconds=60))


def test_fake_provider_satisfies_the_seo_provider_protocol() -> None:
    provider: SeoProvider = FakeSeoProvider(name="codex", responses=["{}"])
    assert isinstance(provider.readiness(), ProviderReadiness)
