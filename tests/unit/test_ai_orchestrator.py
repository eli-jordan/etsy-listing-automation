"""``ai/orchestrator.py``: the Codex-then-Claude chain, one same-provider
repair attempt, and the shared 60-second deadline (AI SEO implementation
plan, PR4, item 3).

Exercised entirely against `FakeAiProvider` (PR3) -- never a real Codex or
Claude adapter -- exactly as that double's own docstring says it exists for:
"fallback ordering, one same-provider repair, and deadline handling can all
be exercised entirely offline". This is also what keeps CI fake-provider-only
for this seam.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from etsy_listings.ai import orchestrator
from etsy_listings.ai.brief import BriefRequest, build_brief_task
from etsy_listings.ai.errors import (
    ProviderCancelledError,
    SeoAllProvidersUnavailableError,
    SeoDeadlineExceededError,
    SeoTryAgainError,
)
from etsy_listings.ai.models import (
    Deadline,
    GarmentContext,
    ProviderReadiness,
    ProviderTask,
    SeoRequest,
)
from etsy_listings.ai.prompt import build_seo_task
from etsy_listings.ai.providers import FakeAiProvider

_PROMPT = "Write SEO copy.\n"
"""Stands in for the seller's `prompts/seo.md`. The orchestrator takes the
text rather than a path (PRD 68 moved prompt assembly out of the adapters),
so these tests need no workspace at all."""


def _request() -> SeoRequest:
    return SeoRequest(
        brief="A retro sunset tee.",
        product_type="t-shirt",
        etsy_category="Clothing",
        materials=("Comfort Colors 1717",),
        colors=("navy",),
        garment=GarmentContext(brand="Comfort Colors", model="1717"),
        design_image=Path("designs/front.png"),
    )


def _seo_task() -> ProviderTask:
    """What `generate_proposal` hands a provider for `_request()` -- the
    assertion subject wherever a test used to compare recorded `SeoRequest`s."""
    return build_seo_task(_PROMPT, _request())


def _valid_payload() -> str:
    import json

    return json.dumps(
        {
            "titles": ["a" * 10, "b" * 10, "c" * 10],
            "tags": [f"tag{i}" for i in range(20)],
            "description_leads": ["lead one", "lead two", "lead three"],
            "rationale": [
                {
                    "phrase": f"phrase {i}",
                    "intent": "core_product",
                    "reason": "because",
                    "used_in": ["title"],
                }
                for i in range(7)
            ],
            "warnings": [],
            "observed_text": "",
        }
    )


def test_first_provider_success_returns_its_proposal_without_touching_the_second() -> None:
    codex = FakeAiProvider(name="codex", responses=[_valid_payload()])
    fallback = FakeAiProvider(name="claude", responses=[])

    proposal = orchestrator.generate_proposal(_request(), _PROMPT, [codex, fallback])

    assert proposal.titles[0] == "a" * 10
    assert fallback.tasks == []


def test_unavailable_first_provider_falls_through_to_the_second() -> None:
    codex = FakeAiProvider(
        name="codex", ready=ProviderReadiness(ready=False, reason="not authenticated")
    )
    codex.generate = _raise_unavailable("codex")  # type: ignore[method-assign]
    claude = FakeAiProvider(name="claude", responses=[_valid_payload()])

    proposal = orchestrator.generate_proposal(_request(), _PROMPT, [codex, claude])

    assert proposal.titles[0] == "a" * 10
    assert claude.tasks == [_seo_task()]


def _raise_unavailable(provider: str):  # noqa: ANN201 - test helper
    from etsy_listings.ai.errors import ProviderUnavailableError

    def _generate(request, deadline, *, repair=None, cancel_event=None):  # noqa: ANN001, ANN202
        raise ProviderUnavailableError(provider, "not authenticated")

    return _generate


def test_all_providers_unavailable_raises_all_providers_unavailable() -> None:
    codex = FakeAiProvider(name="codex")
    codex.generate = _raise_unavailable("codex")  # type: ignore[method-assign]
    claude = FakeAiProvider(name="claude")
    claude.generate = _raise_unavailable("claude")  # type: ignore[method-assign]

    with pytest.raises(SeoAllProvidersUnavailableError) as excinfo:
        orchestrator.generate_proposal(_request(), _PROMPT, [codex, claude])

    assert "codex" in str(excinfo.value)
    assert "claude" in str(excinfo.value)


def test_malformed_first_response_triggers_one_same_provider_repair() -> None:
    codex = FakeAiProvider(name="codex", responses=["not json", _valid_payload()])

    proposal = orchestrator.generate_proposal(_request(), _PROMPT, [codex])

    assert proposal.titles[0] == "a" * 10
    assert len(codex.tasks) == 2
    assert codex.repairs[0] is None
    assert codex.repairs[1] is not None
    assert "not valid JSON" in " ".join(codex.repairs[1].reasons) or codex.repairs[1].reasons


def test_repair_prompt_carries_the_prior_output_and_reasons() -> None:
    codex = FakeAiProvider(name="codex", responses=['{"titles": []}', _valid_payload()])

    orchestrator.generate_proposal(_request(), _PROMPT, [codex])

    repair = codex.repairs[1]
    assert repair is not None
    assert repair.prior_raw_output == '{"titles": []}'
    assert any("titles" in reason for reason in repair.reasons)


def test_repair_still_malformed_surfaces_as_try_again_not_fallback() -> None:
    codex = FakeAiProvider(name="codex", responses=["not json", "still not json"])
    claude = FakeAiProvider(name="claude", responses=[_valid_payload()])

    with pytest.raises(SeoTryAgainError):
        orchestrator.generate_proposal(_request(), _PROMPT, [codex, claude])

    assert claude.tasks == []  # no fallback after a failed repair


def test_valid_first_response_never_requests_a_repair() -> None:
    codex = FakeAiProvider(name="codex", responses=[_valid_payload()])

    orchestrator.generate_proposal(_request(), _PROMPT, [codex])

    assert codex.repairs == [None]


def test_deadline_exceeded_before_any_provider_is_tried() -> None:
    codex = FakeAiProvider(name="codex", responses=[_valid_payload()])
    already_expired = Deadline(deadline_at=time.monotonic() - 1)

    with pytest.raises(SeoDeadlineExceededError):
        orchestrator.generate_proposal(_request(), _PROMPT, [codex], deadline=already_expired)

    assert codex.tasks == []


def test_deadline_exceeded_skips_repair_and_surfaces_try_again() -> None:
    codex = FakeAiProvider(name="codex", responses=["not json"])

    class _ExpiringDeadline:
        """A deadline that reports not-expired for the first check (letting
        the initial `generate` call happen) and expired from then on -- the
        shape a real 60-second budget takes once the first call alone
        consumed it."""

        def __init__(self) -> None:
            self.calls = 0

        @property
        def expired(self) -> bool:
            self.calls += 1
            return self.calls > 1

        def remaining_seconds(self) -> float:
            return 0.0 if self.expired else 60.0

    with pytest.raises(SeoDeadlineExceededError):
        orchestrator.generate_proposal(_request(), _PROMPT, [codex], deadline=_ExpiringDeadline())  # type: ignore[arg-type]

    assert len(codex.tasks) == 1  # the repair call never happened


def test_cancelled_error_propagates_without_becoming_try_again() -> None:
    codex = FakeAiProvider(name="codex")

    def _generate(request, deadline, *, repair=None, cancel_event=None):  # noqa: ANN001, ANN202
        raise ProviderCancelledError("codex")

    codex.generate = _generate  # type: ignore[method-assign]

    with pytest.raises(ProviderCancelledError):
        orchestrator.generate_proposal(_request(), _PROMPT, [codex])


def test_cancel_event_is_forwarded_to_the_provider() -> None:
    """`generate_proposal` is the "SEO service" the runtime design says owns
    cancellation -- it must actually pass the one `threading.Event` PR5's
    disconnect/Cancel handling will set down to the provider, not merely
    accept it and drop it on the floor."""
    codex = FakeAiProvider(name="codex", responses=[_valid_payload()])
    cancel_event = threading.Event()

    orchestrator.generate_proposal(_request(), _PROMPT, [codex], cancel_event=cancel_event)

    assert codex.cancel_events == [cancel_event]


def test_cancel_event_is_forwarded_to_a_repair_call_too() -> None:
    codex = FakeAiProvider(name="codex", responses=["not json", _valid_payload()])
    cancel_event = threading.Event()

    orchestrator.generate_proposal(_request(), _PROMPT, [codex], cancel_event=cancel_event)

    assert codex.cancel_events == [cancel_event, cancel_event]


def test_no_cancel_event_means_generation_proceeds_uncancelled() -> None:
    codex = FakeAiProvider(name="codex", responses=[_valid_payload()])

    orchestrator.generate_proposal(_request(), _PROMPT, [codex])

    assert codex.cancel_events == [None]


def test_no_providers_configured_raises_all_providers_unavailable() -> None:
    with pytest.raises(SeoAllProvidersUnavailableError):
        orchestrator.generate_proposal(_request(), _PROMPT, [])


def test_valid_json_that_is_not_an_object_is_treated_as_malformed() -> None:
    codex = FakeAiProvider(name="codex", responses=["[1, 2, 3]", _valid_payload()])

    proposal = orchestrator.generate_proposal(_request(), _PROMPT, [codex])

    assert proposal.titles[0] == "a" * 10
    assert any("expected a JSON object" in reason for reason in codex.repairs[1].reasons)  # type: ignore[union-attr]


def test_provider_becoming_unavailable_during_repair_surfaces_as_try_again() -> None:
    from etsy_listings.ai.errors import ProviderUnavailableError

    codex = FakeAiProvider(name="codex", responses=["not json"])
    calls = {"count": 0}
    original_generate = codex.generate

    def _generate(request, deadline, *, repair=None, cancel_event=None):  # noqa: ANN001, ANN202
        calls["count"] += 1
        if repair is not None:
            raise ProviderUnavailableError("codex", "quota exhausted mid-repair")
        return original_generate(request, deadline, repair=repair, cancel_event=cancel_event)

    codex.generate = _generate  # type: ignore[method-assign]
    claude = FakeAiProvider(name="claude", responses=[_valid_payload()])

    with pytest.raises(SeoTryAgainError):
        orchestrator.generate_proposal(_request(), _PROMPT, [codex, claude])

    assert claude.tasks == []  # still no fallback -- the chain already committed to codex


# --------------------------------------------------------------- brief drafting
#
# `generate_brief` is the same `run_task` under a different decoder (PRD 68),
# so these do not re-test fallback, repair or the deadline -- every case
# above already covers those once. What is worth asserting is exactly what
# differs: which task a provider is handed, and that a brief-shaped response
# is what comes back.


def _brief_request() -> BriefRequest:
    return BriefRequest(
        design_image=Path("designs/front.png"),
        product_type="t-shirt",
        garment=GarmentContext(brand="Comfort Colors", model="1717"),
    )


def test_generate_brief_hands_the_provider_the_brief_task_and_returns_its_text() -> None:
    codex = FakeAiProvider(name="codex", responses=['{"brief": "Retro sunset mountains."}'])

    drafted = orchestrator.generate_brief(_brief_request(), "Describe it.", [codex])

    assert drafted.brief == "Retro sunset mountains."
    assert codex.tasks == [build_brief_task("Describe it.", _brief_request())]


def test_a_malformed_brief_gets_the_same_one_repair_attempt() -> None:
    codex = FakeAiProvider(name="codex", responses=["not json", '{"brief": "Repaired."}'])

    drafted = orchestrator.generate_brief(_brief_request(), "Describe it.", [codex])

    assert drafted.brief == "Repaired."
    assert codex.repairs[0] is None
    assert codex.repairs[1] is not None


def test_an_invalid_brief_that_survives_repair_surfaces_as_try_again() -> None:
    """The validation reason reaches the repair prompt, which is the whole
    point of `ai/brief.py.BriefValidationError` carrying reasons at all."""
    codex = FakeAiProvider(name="codex", responses=['{"brief": ""}', '{"brief": "  "}'])

    with pytest.raises(SeoTryAgainError):
        orchestrator.generate_brief(_brief_request(), "Describe it.", [codex])

    assert any("must not be empty" in reason for reason in codex.repairs[1].reasons)  # type: ignore[union-attr]


def test_brief_drafting_falls_through_to_the_second_provider_too() -> None:
    codex = FakeAiProvider(
        name="codex",
        ready=ProviderReadiness(ready=True),
        responses=[],
    )

    def _unavailable(task, deadline, *, repair=None, cancel_event=None):  # noqa: ANN001, ANN202
        from etsy_listings.ai.errors import ProviderUnavailableError

        raise ProviderUnavailableError("codex", "not signed in")

    codex.generate = _unavailable  # type: ignore[method-assign]
    claude = FakeAiProvider(name="claude", responses=['{"brief": "From Claude."}'])

    drafted = orchestrator.generate_brief(_brief_request(), "Describe it.", [codex, claude])

    assert drafted.brief == "From Claude."
