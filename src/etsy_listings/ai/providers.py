"""The narrow provider boundary the orchestration service (`ai/orchestrator.py`)
drives, and `FakeAiProvider`, the double every offline test runs against (AI
SEO implementation plan, "Provider adapters"; item 6: fake providers and
contract fixtures, no real CLI call in unit or CI tests).

An adapter owns its own CLI invocation, structured-output parsing down to raw
text, and provider-specific error classification -- it must not edit a
listing, assemble a prompt, or implement SEO validation.

`generate` takes a `ai/models.py.ProviderTask`, not a `SeoRequest`: PRD 68
gives this codebase a second AI feature (drafting a listing brief from its
design), and a provider was never the layer that knew which one it was
serving. Assembled prompt text, a response schema and one image is the whole
of what a CLI invocation needs, so that is the whole of what crosses this
boundary -- and both features then share one fallback order, one repair rule
and one deadline rather than growing a second copy of each.

`generate`'s ``repair`` keyword is why a same-provider repair call cannot be
expressed as a second, identical `generate(task, deadline)` call once a real
CLI adapter is behind it -- see `ai/models.py.RepairContext`. Its
``cancel_event`` keyword is where the settled "Cancellation" decision reaches
a running subprocess: both real adapters forward it to
`ai/process.py.run_managed`, which is what actually kills the tree. Both
default to `None`, so an ordinary first, uncancellable attempt says nothing.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from etsy_listings.ai.models import (
    Deadline,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
)


@runtime_checkable
class AiProvider(Protocol):
    """One provider's readiness check and its generation call.

    The orchestration service owns retry classification, the Codex-then-
    Claude fallback order, the shared 60-second deadline, and turning raw
    output into a validated result -- none of that belongs to an adapter,
    which is why this protocol is this small.
    """

    def readiness(self) -> ProviderReadiness: ...

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult: ...


@dataclass
class FakeAiProvider:
    """A scriptable `AiProvider` double, standing in for a real Codex or
    Claude adapter at the same seam the orchestration tests drive -- fallback
    ordering, one same-provider repair, and deadline handling can all be
    exercised entirely offline.

    ``responses`` is consumed in order, one raw-output string per
    :meth:`generate` call -- a two-entry queue is how a test represents "the
    first response was malformed, the repaired second one was not," without
    this double knowing anything about repair itself (that stays the
    orchestration service's decision). ``tasks`` records every `ProviderTask`
    this provider was asked to handle, for a test to assert on what the
    orchestrator actually sent; ``repairs`` records the matching ``repair``
    argument for each of those calls (``None`` for an ordinary first
    attempt), same length and order as ``tasks``. ``cancel_events`` records
    the matching ``cancel_event`` argument the same way, so a test can assert
    the orchestrator forwarded the one cancellation signal it was given
    rather than silently dropping it.
    """

    name: str
    responses: list[str] = field(default_factory=list)
    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    tasks: list[ProviderTask] = field(default_factory=list, init=False)
    repairs: list[RepairContext | None] = field(default_factory=list, init=False)
    cancel_events: list[threading.Event | None] = field(default_factory=list, init=False)

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        self.tasks.append(task)
        self.repairs.append(repair)
        self.cancel_events.append(cancel_event)
        if not self.responses:
            raise AssertionError(
                f"FakeAiProvider {self.name!r} was asked to generate with no queued "
                f"response left -- give it one more entry in `responses`"
            )
        return RawProviderResult(provider=self.name, raw_output=self.responses.pop(0))
