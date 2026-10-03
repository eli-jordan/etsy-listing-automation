"""An AI run's events and the indicator nodes they move
(features/market-seo-20260924/spec.md, *AI runs*; the implementation plan's
*Run contract*).

Transport-independent models, so the same models are the SSE payload rather
than a second representation (module-structure spec, *Responsibility and
dependency rules*). The request, refusal and summaries only the HTTP
endpoints use are the server's (``server/api/schemas.py``).

Every event carries ``type``, the SSE ``event:`` name a client switches on,
and ``seq``, the SSE ``id:`` a reconnect sends back as ``Last-Event-ID``. The
sequence number is not called ``id`` because a ``step`` event's ``id`` is
already the node it moves (``brief``, ``market`` or ``seo``): a step event is
a :class:`WorkflowStep` plus those two fields, so the browser can reduce the
latest one per node straight into its indicator.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from etsy_listings.core.ai.proposals import ListingProposal
from etsy_listings.core.market.snapshot import MarketSnapshot

StepId = Literal["brief", "market", "seo"]
StepState = Literal["pending", "active", "done", "skipped", "warning", "failed"]


class WorkflowStep(BaseModel):
    """One node of the three-node indicator (``AiWorkflowIndicator.tsx``'s
    ``WorkflowStep``): an AI run's, or a batch row's."""

    id: StepId
    state: StepState
    detail: str | None = None


TerminalPhase = Literal["done", "failed", "cancelled"]
AiRunPhase = Literal["running", "done", "failed", "cancelled"]

STEP_IDS: tuple[StepId, ...] = ("brief", "market", "seo")


class AiStepEvent(WorkflowStep):
    """A node changed. The first three events of a run set each node's
    initial state."""

    type: Literal["step"] = "step"
    seq: int


class AiBriefEvent(BaseModel):
    """The brief was drafted. ``written`` is false when the seller filled the
    field in the meantime, so their text was kept."""

    type: Literal["brief"] = "brief"
    seq: int
    text: str
    written: bool


class AiQueriesEvent(BaseModel):
    """The three buyer searches extraction chose."""

    type: Literal["queries"] = "queries"
    seq: int
    queries: list[str] = Field(min_length=3, max_length=3)


class AiMarketEvent(BaseModel):
    """A successful or empty search, once its snapshot is saved."""

    type: Literal["market"] = "market"
    seq: int
    snapshot: MarketSnapshot


class AiProposalEvent(ListingProposal):
    """The validated proposal, once it is cached: what ``GET
    /api/listings/{name}/proposal`` answers at that moment, plus ``type``
    and ``seq``."""

    type: Literal["proposal"] = "proposal"
    seq: int


class AiPhaseEvent(BaseModel):
    """Terminal, and always the run's last event."""

    type: Literal["phase"] = "phase"
    seq: int
    phase: TerminalPhase
    message: str | None = None


AnyAiRunEvent = (
    AiStepEvent | AiBriefEvent | AiQueriesEvent | AiMarketEvent | AiProposalEvent | AiPhaseEvent
)
AiRunEvent = Annotated[AnyAiRunEvent, Field(discriminator="type")]
