"""The request, task, proposal, rationale, warning, and readiness shapes one
AI Mode request passes between its layers (AI SEO implementation plan, PR3,
item 1; `docs/ui-listing-seo-interactions.md`).

Plain frozen dataclasses, not pydantic models. A `SeoProposal` is never
loaded from a config file -- it is built by `ai/validation.py` from a
provider's already-JSON-decoded output, field by field, collecting every
reason it is unusable rather than raising on the first (see that module's
own docstring). Pydantic's validate-on-construct is the wrong shape for that:
these types are the *destination* `validate_proposal` builds once normalizing
and hard-validating a raw mapping has already succeeded, not a schema it
validates against directly.

`Deadline` is the one shared clock this feature uses. The settled plan gives
the whole request -- provider call, one same-provider repair, and the
permitted Codex-to-Claude fallback -- a single 60-second budget; a `Deadline`
is what lets that budget be threaded through the orchestration service and
both provider adapters (PR4) as one value instead of each layer computing its
own remaining time from a start timestamp it has to be separately handed.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

RationaleIntent = Literal["core_product", "bottom_of_funnel", "style"]
RationaleField = Literal["title", "tags", "description_lead"]
WarningKind = Literal["general", "trademark"]


@dataclass(frozen=True)
class ProviderTask:
    """One complete unit of work for a provider CLI, with nothing in it that
    says which AI feature asked (PRD 68).

    This is the seam that lets brief drafting and SEO generation share one
    Codex adapter, one Claude adapter, one fallback order, one repair rule
    and one deadline. An adapter's job was always "run the CLI read-only
    against this prompt, hand it this schema, let it see this image, return
    what it printed" -- what made that look SEO-shaped was only that the
    adapter itself assembled the prompt from `prompts/seo.md`. Assembling it
    is the caller's now (`ai/prompt.py.build_seo_task`,
    `ai/brief.py.build_brief_task`), which also settles a question two
    readiness checks used to answer differently: a missing prompt file makes
    a *request* impossible, not a CLI unready, so it is no longer part of
    `readiness()`.

    ``prompt_text`` is already complete -- seller prose, delimited context,
    schema and all. A repair call appends to it (`ai/repair.py`); nothing
    else ever rewrites it.
    """

    prompt_text: str
    response_schema: Mapping[str, Any]
    design_image: Path


@dataclass(frozen=True)
class GarmentContext:
    """The garment facts the prompt's `listing.garment` object needs --
    brand and model only, mirroring `seo_prompt.md`'s drafted context shape
    exactly (see `ai/prompt.py`'s context payload). Nothing else about the
    garment profile is in scope for SEO copy."""

    brand: str
    model: str


@dataclass(frozen=True)
class SeoRequest:
    """The submitted generation inputs for one proposal request.

    This is the request-scoped snapshot `docs/ai-seo-implementation-plan.md`'s
    "Proposal and stale-state rules" describes: listing brief, garment
    context, and the other editable listing values relevant to SEO copy.
    `design_image` is a workspace-resolved path, handed to a provider adapter
    to read directly (PRD: "sends the design image") -- this type carries no
    image bytes, and no design *identity/content hash*: the request endpoint
    captures that alongside this provider-facing request before generation,
    so the browser can compare pending choices with the same saved inputs.

    Deliberately excludes an explicit "exact design text" field: the PRD's
    entry-point paragraph settles that the *brief* itself carries any
    design wording that stylised lettering might obscure from OCR ("the
    brief carries exact design text"), so `brief` alone covers input
    authority #2 in `seo_prompt.md`'s ranked list.
    """

    brief: str
    product_type: str
    etsy_category: str
    materials: tuple[str, ...]
    colors: tuple[str, ...]
    garment: GarmentContext
    design_image: Path
    market_block: str = ""
    """`market.market_block()`'s delimited market data (market-seo.md, *What
    the proposal sees*), appended after the listing context. Empty when a
    search found nothing comparable -- the one case a proposal goes ahead
    without market data -- and then no block is sent at all."""


@dataclass(frozen=True)
class PhraseRationale:
    """One of the proposal's exactly seven priority-phrase rationales
    (`seo_prompt.md`'s "Priority search phrases" section, `used_in` renamed
    from that draft's fixed enum values to match `RationaleField`)."""

    phrase: str
    intent: RationaleIntent
    reason: str
    used_in: tuple[RationaleField, ...]


@dataclass(frozen=True)
class ProposalWarning:
    """One disclosure attached to a proposal.

    `kind="trademark"` is `ai/validation.py`'s own addition -- a soft,
    non-blocking finding the hard-validation pass appends when copy mentions
    a name on its curated watch list (settled decision: "Trademark findings
    are warnings, not a hard refusal"). `kind="general"` (the default) covers
    everything else, including every warning the provider itself returned in
    its `warnings` array -- the model's own "missing information" disclosures
    (`seo_prompt.md`'s "Missing information" section) arrive with no kind of
    their own, and are not trademark findings.
    """

    message: str
    kind: WarningKind = "general"


@dataclass(frozen=True)
class SeoProposal:
    """A complete, hard-validated SEO proposal -- the only shape
    `ai/validation.py.validate_proposal` ever hands back, and the only shape
    later PRs' browser drawers (PR7) are built against.

    Exactly three titles, twenty unique ranked tags (the first thirteen are
    Best 13), three description leads, seven phrase rationales, warnings, and
    observed OCR text -- the settled "Proposal" row in the implementation
    plan's decision table. `tags` keeps its ranked order: index position *is*
    the rank, so "first thirteen" is simply `tags[:13]`, with no separate
    rank field to keep in sync.
    """

    titles: tuple[str, str, str]
    tags: tuple[str, ...]
    description_leads: tuple[str, str, str]
    rationale: tuple[PhraseRationale, ...]
    warnings: tuple[ProposalWarning, ...]
    observed_text: str


@dataclass(frozen=True)
class ProviderReadiness:
    """Whether one provider can be asked to generate a proposal right now.

    `reason` is set only when `ready` is `False` -- the sentence a caller
    surfaces (or, at the readiness-endpoint layer PR5 builds, folds into
    "AI Mode is hidden because ..."). A provider that cannot guarantee the
    agreed read-only execution boundary answers `ready=False` here rather
    than being launched writable (implementation plan, "Provider adapters").
    """

    ready: bool
    reason: str | None = None


@dataclass(frozen=True)
class RawProviderResult:
    """A provider's unparsed response, still just text.

    Decoding it as JSON, and everything downstream of that, is
    `ai/validation.py.validate_proposal`'s job -- an adapter's own concern
    stops at "the CLI ran and printed this" (implementation plan, "Provider
    adapters": an adapter owns CLI invocation and structured-output parsing
    down to text, never SEO validation itself).
    """

    provider: str
    raw_output: str


@dataclass(frozen=True)
class RepairContext:
    """What the orchestration service hands a provider for its one allowed
    same-provider repair call (AI SEO implementation plan, PR4, item 3: "one
    same-provider output repair").

    This is the genuine gap PR3's `SeoProvider.generate(request, deadline)`
    left open: a real Codex/Claude adapter runs one CLI invocation per call
    with no durable session (implementation plan: "no durable provider
    session"), so the repair turn has to carry everything the first call did
    *plus* what went wrong -- there is no prior turn for the CLI to remember.
    ``reasons`` is `ai/validation.py.ProposalValidationError.reasons` (or the
    orchestrator's own "not valid JSON"/"not a JSON object" reason when the
    first response could not even be decoded -- every malformed-response case
    is repaired identically, per the settled decision that any validation
    failure counts as malformed). ``prior_raw_output`` is the first call's
    unparsed text, so a repair prompt can show the model exactly what it
    produced rather than only describing the problem in the abstract.
    """

    prior_raw_output: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Deadline:
    """A fixed point in time, expressed as a remaining budget.

    Wraps `time.monotonic()` rather than `time.time()` -- a wall-clock
    adjustment mid-request must never shorten or extend the 60-second budget
    the settled plan promises. Construct with :meth:`starting_now`; the bare
    constructor exists for tests that want to pin `deadline_at` directly (see
    `field(compare=False)` below -- irrelevant here since there is only one
    field, kept for symmetry with how other frozen dataclasses in this
    codebase are written).
    """

    deadline_at: float = field(default=0.0)

    @classmethod
    def starting_now(cls, *, seconds: float) -> Deadline:
        return cls(deadline_at=time.monotonic() + seconds)

    def remaining_seconds(self) -> float:
        """Never negative -- callers pass this straight to a subprocess
        timeout, and a negative timeout is not "expire immediately" to every
        API, it is undefined behaviour."""
        return max(0.0, self.deadline_at - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining_seconds() <= 0.0
