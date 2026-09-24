"""``ai/providers.py``: the narrow `AiProvider` protocol the Codex and Claude
adapters implement (PR4), and `FakeAiProvider`, the scriptable double this
PR's own contract fixtures and every orchestration test use instead
(implementation plan, item 6: "no real CLI call is needed in unit or CI
tests").

What crosses that protocol is a `ProviderTask` -- assembled prompt text, a
response schema and one image -- and nothing that says which AI feature
asked (PRD 68). These tests build tasks directly rather than through
`build_seo_task`/`build_brief_task`, since a provider is exactly the layer
that cannot tell the difference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.ai.models import Deadline, ProviderReadiness, ProviderTask
from etsy_listings.ai.providers import AiProvider, FakeAiProvider


def _task(prompt_text: str = "do the thing") -> ProviderTask:
    return ProviderTask(
        prompt_text=prompt_text,
        response_schema={"type": "object"},
        design_image=Path("designs/x.png"),
    )


def test_fake_provider_is_ready_by_default() -> None:
    provider = FakeAiProvider(name="codex")
    assert provider.readiness() == ProviderReadiness(ready=True)


def test_fake_provider_readiness_is_configurable() -> None:
    provider = FakeAiProvider(name="codex", ready=ProviderReadiness(ready=False, reason="no CLI"))
    assert provider.readiness() == ProviderReadiness(ready=False, reason="no CLI")


def test_fake_provider_returns_its_queued_response_and_records_the_task() -> None:
    provider = FakeAiProvider(name="claude", responses=["raw output"])
    task = _task()

    result = provider.generate(task, Deadline.starting_now(seconds=60))

    assert result.provider == "claude"
    assert result.raw_output == "raw output"
    assert provider.tasks == [task]


def test_fake_provider_pops_responses_in_order_for_repair_scenarios() -> None:
    """A malformed first response, then a repaired second one -- the shape
    the orchestration service's one-repair-attempt flow exercises."""
    provider = FakeAiProvider(name="codex", responses=["malformed", "{}"])
    deadline = Deadline.starting_now(seconds=60)

    first = provider.generate(_task(), deadline)
    second = provider.generate(_task(), deadline)

    assert first.raw_output == "malformed"
    assert second.raw_output == "{}"


def test_fake_provider_raises_when_asked_for_more_responses_than_queued() -> None:
    provider = FakeAiProvider(name="codex", responses=[])
    with pytest.raises(AssertionError):
        provider.generate(_task(), Deadline.starting_now(seconds=60))


def test_fake_provider_satisfies_the_provider_protocol() -> None:
    provider: AiProvider = FakeAiProvider(name="codex", responses=["{}"])
    assert isinstance(provider.readiness(), ProviderReadiness)
