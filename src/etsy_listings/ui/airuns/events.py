"""The AI run's wire shapes: its events, and the summary and detail the
endpoints return (market-seo.md, *AI runs*; the implementation plan's *Run
contract*).

Every event carries ``type``, the SSE ``event:`` name a client switches on,
and ``seq``, the SSE ``id:`` a reconnect sends back as ``Last-Event-ID``. The
sequence number is not called ``id`` because a ``step`` event's ``id`` is
already the node it moves (``brief``, ``market`` or ``seo``): a step event is
a :class:`WorkflowStep` plus those two fields, so the browser can reduce the
latest one per node straight into its indicator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from etsy_listings.market.snapshot import MarketSnapshot
from etsy_listings.ui.api.schemas import SeoProposalResponse

StepId = Literal["brief", "market", "seo"]
StepState = Literal["pending", "active", "done", "skipped", "warning", "failed"]
TerminalPhase = Literal["done", "failed", "cancelled"]
AiRunPhase = Literal["running", "done", "failed", "cancelled"]

STEP_IDS: tuple[StepId, ...] = ("brief", "market", "seo")


class WorkflowStep(BaseModel):
    """One node of the three-node indicator (``AiWorkflowIndicator.tsx``'s
    ``WorkflowStep``)."""

    id: StepId
    state: StepState
    detail: str | None = None


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


class AiProposalEvent(SeoProposalResponse):
    """The validated proposal: :class:`SeoProposalResponse` unchanged, plus
    ``type`` and ``seq``."""

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


class CreateAiRunRequest(BaseModel):
    listing: str
    draft_brief: bool = False
    """Draft the brief first. Only honoured while the saved brief is empty;
    a run whose listing already has one skips the Brief node."""


class AiRunRefusal(BaseModel):
    """A ``409`` from ``POST /api/ai/runs``: exactly one of the two is set.
    ``active_run`` names the run to reattach to; ``reason`` says which
    readiness rule failed."""

    active_run: str | None = None
    reason: str | None = None


class AiRunSummary(BaseModel):
    id: str
    listing: str
    draft_brief: bool
    phase: AiRunPhase
    steps: list[WorkflowStep]
    created_at: datetime
    finished_at: datetime | None


class AiRunDetail(AiRunSummary):
    events: list[AiRunEvent]
