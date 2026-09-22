"""The narrow provider boundary the orchestration service (`ai/orchestrator.py`,
PR4) drives, and `FakeSeoProvider`, the one implementation PR3 shipped (AI SEO
implementation plan, "Provider adapters"; item 6: fake providers and
contract fixtures, no real CLI call in unit or CI tests).

`SeoProvider` is exactly the protocol the plan already sketches: an adapter
owns its own CLI invocation, structured-output parsing down to raw text, and
provider-specific error classification -- it must not edit a listing or
implement SEO validation. The Codex and Claude adapters behind it are PR4's
job; nothing here launches a subprocess.

`generate`'s ``repair`` keyword is PR4's one addition to this protocol -- see
`ai/models.py.RepairContext` for why a same-provider repair call cannot be
expressed as a second, identical `generate(request, deadline)` call once a
real CLI adapter is behind it. It defaults to `None`, so every PR3 call site
that only ever wanted a first attempt is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from etsy_listings.ai.models import (
    Deadline,
    ProviderReadiness,
    RawProviderResult,
    RepairContext,
    SeoRequest,
)


@runtime_checkable
class SeoProvider(Protocol):
    """One provider's readiness check and its generation call.

    The orchestration service owns retry classification, the Codex-then-
    Claude fallback order, the shared 60-second deadline, and turning raw
    output into a validated `SeoProposal` (via `ai/validation.py`) -- none of
    that belongs to an adapter, which is why this protocol is this small.
    """

    def readiness(self) -> ProviderReadiness: ...

    def generate(
        self,
        request: SeoRequest,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
    ) -> RawProviderResult: ...


@dataclass
class FakeSeoProvider:
    """A scriptable `SeoProvider` double, standing in for a real Codex or
    Claude adapter at the same seam later PRs drive their orchestration
    tests through -- fallback ordering, one same-provider repair, and
    deadline handling can all be exercised entirely offline.

    ``responses`` is consumed in order, one raw-output string per
    :meth:`generate` call -- a two-entry queue is how a test represents "the
    first response was malformed, the repaired second one was not," without
    this double knowing anything about repair itself (that stays the
    orchestration service's decision). ``requests`` records every
    `SeoRequest` this provider was asked to handle, for a test to assert on
    what the orchestrator actually sent; ``repairs`` records the matching
    ``repair`` argument for each of those calls (``None`` for an ordinary
    first attempt), same length and order as ``requests``.
    """

    name: str
    responses: list[str] = field(default_factory=list)
    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    requests: list[SeoRequest] = field(default_factory=list, init=False)
    repairs: list[RepairContext | None] = field(default_factory=list, init=False)

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def generate(
        self,
        request: SeoRequest,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
    ) -> RawProviderResult:
        self.requests.append(request)
        self.repairs.append(repair)
        if not self.responses:
            raise AssertionError(
                f"FakeSeoProvider {self.name!r} was asked to generate with no queued "
                f"response left -- give it one more entry in `responses`"
            )
        return RawProviderResult(provider=self.name, raw_output=self.responses.pop(0))
