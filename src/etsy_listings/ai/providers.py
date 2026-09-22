"""The narrow provider boundary the orchestration service (PR5) drives, and
`FakeSeoProvider`, the one implementation this PR ships (AI SEO
implementation plan, "Provider adapters"; item 6: fake providers and
contract fixtures, no real CLI call in unit or CI tests).

`SeoProvider` is exactly the protocol the plan already sketches: an adapter
owns its own CLI invocation, structured-output parsing down to raw text, and
provider-specific error classification -- it must not edit a listing or
implement SEO validation. The Codex and Claude adapters behind it are PR4's
job; nothing here launches a subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from etsy_listings.ai.models import Deadline, ProviderReadiness, RawProviderResult, SeoRequest


@runtime_checkable
class SeoProvider(Protocol):
    """One provider's readiness check and its one generation call.

    The orchestration service owns retry classification, the Codex-then-
    Claude fallback order, the shared 60-second deadline, and turning raw
    output into a validated `SeoProposal` (via `ai/validation.py`) -- none of
    that belongs to an adapter, which is why this protocol is this small.
    """

    def readiness(self) -> ProviderReadiness: ...

    def generate(self, request: SeoRequest, deadline: Deadline) -> RawProviderResult: ...


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
    what the orchestrator actually sent.
    """

    name: str
    responses: list[str] = field(default_factory=list)
    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    requests: list[SeoRequest] = field(default_factory=list, init=False)

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def generate(self, request: SeoRequest, deadline: Deadline) -> RawProviderResult:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(
                f"FakeSeoProvider {self.name!r} was asked to generate with no queued "
                f"response left -- give it one more entry in `responses`"
            )
        return RawProviderResult(provider=self.name, raw_output=self.responses.pop(0))
