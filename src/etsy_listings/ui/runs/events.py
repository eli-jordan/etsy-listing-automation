"""The ``RunEvent`` union the SSE route streams, and how a ``Plan``/``StagePlan``
turns into JSON (A33, decision 7).

Two things are true about the engine's own ``Plan``/``StagePlan``/``Change``
types that make them unfit to serialise directly. They are plain dataclasses,
some of them carrying a :class:`~etsy_listings.config.money.Money` or a nested
pydantic ``snapshot`` model -- neither JSON nor an untyped pydantic field
converts on its own, so ``json.dumps`` would raise on the first price this run
had ever compared. And the four ``Change`` shapes (``FieldChange``,
``ListChange``, ``PriceChange``, ``MediaChange``) are a plain union with no
field a frontend union type could discriminate on -- exactly the ambiguity
``StagePlan.blocked``/``Verdict.refused`` already solved once for "why didn't
this run" (see ``engine/stage.py``'s docstring) by picking one vocabulary
rather than reusing whatever shape happened to be lying around.

So every engine type gains a small DTO mirror here, each with an explicit
``kind``/``type`` literal a frontend can switch on, built by walking the real
value once (:func:`_jsonable`) rather than leaning on pydantic to already know
what a ``Money`` is. This is *not* :func:`~etsy_listings.engine.run._canonical`
reused: that helper exists to drop ``snapshot`` for the plan fingerprint (A31)
and must never be tempted to keep it; this one exists to keep it, because the
whole reason a plan run streams a ``listing_planned`` event is to show the
snapshot the fingerprint is not allowed to see.

**Why the union lives here and not beside each engine type.** ``engine``
computes a diff and is not allowed to know anyone is going to serialise it
over a socket (`plan.py`'s own docstring: only ``engine`` computes one, and
the CLI renderer and the UI's serialiser both consume the result without
re-deriving it). A DTO next to ``FieldChange`` would be exactly the drift this
module's docstring elsewhere warns about -- one shape, two owners.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from etsy_listings.config.money import Money
from etsy_listings.engine.change import (
    Action,
    Change,
    Drift,
    FieldChange,
    ListChange,
    MediaChange,
    Plan,
    PriceChange,
    StagePlan,
)

RunKind = Literal["plan", "apply"]
RunScope = Literal["listings", "workspace"]

RunPhase = Literal[
    "queued",
    "planning",
    "planned",
    "previewing",
    "ready",
    "applying",
    "applied",
    "failed",
    "stale",
    "cancelled",
]
"""Every phase a run can be in, across both kinds (A33, decision 7). A plan
run only ever reaches ``queued``/``planning``/``planned``/``previewing``/
``ready``/``cancelled``; an apply run only ever reaches
``queued``/``applying``/``applied``/``failed``/``stale``. One ``Literal``
rather than two, because :class:`Run` (``registry.py``) is one class for both
kinds and a single ``phase`` field is simpler than a kind-keyed union that
buys nothing here -- nothing reads ``Run.phase`` without already knowing
``Run.kind``."""

TERMINAL_PHASES: frozenset[RunPhase] = frozenset(
    {"ready", "applied", "failed", "stale", "cancelled"}
)
"""A run in one of these will never emit another event. The SSE route polls
this to know when to close the stream (``api/runs.py``); the registry polls it
to know a listing's lock may be released."""


def _jsonable(value: Any) -> Any:  # noqa: ANN401 - a generic tree walk, by construction
    """``value``, turned into something ``BaseModel`` can hold in an ``Any``
    field and get back out again as plain JSON.

    Handles exactly the shapes a ``Change``/``Drift``'s ``before``/``after``/
    ``last_applied``/``live`` or a stage's ``snapshot`` can actually be: a
    :class:`Money`, a nested pydantic model (a snapshot, or a snapshot field
    that is itself one), a dataclass, a ``Path``, an ``Enum``, a
    list/tuple/dict of any of those, or a plain JSON scalar already. Unlike
    :func:`~etsy_listings.engine.run._canonical`, this keeps every field by
    name (including one literally called ``snapshot``) -- there is no
    fingerprint here for a snapshot to spoil.
    """
    if isinstance(value, Money):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


# ------------------------------------------------------------------ Change


class FieldChangeDTO(BaseModel):
    kind: Literal["field"] = "field"
    path: str
    before: Any
    after: Any


class ListChangeDTO(BaseModel):
    kind: Literal["list"] = "list"
    path: str
    added: tuple[Any, ...]
    removed: tuple[Any, ...]
    reordered: bool


class PriceChangeDTO(BaseModel):
    kind: Literal["price"] = "price"
    size: str
    before: str
    after: str
    color: str | None = None


class MediaChangeDTO(BaseModel):
    kind: Literal["media"] = "media"
    rank: int
    before: str | None
    after: str | None


ChangeDTO = Annotated[
    FieldChangeDTO | ListChangeDTO | PriceChangeDTO | MediaChangeDTO,
    Field(discriminator="kind"),
]


def _change_dto(change: Change) -> FieldChangeDTO | ListChangeDTO | PriceChangeDTO | MediaChangeDTO:
    if isinstance(change, FieldChange):
        return FieldChangeDTO(
            path=change.path, before=_jsonable(change.before), after=_jsonable(change.after)
        )
    if isinstance(change, ListChange):
        return ListChangeDTO(
            path=change.path,
            added=tuple(_jsonable(item) for item in change.added),
            removed=tuple(_jsonable(item) for item in change.removed),
            reordered=change.reordered,
        )
    if isinstance(change, PriceChange):
        return PriceChangeDTO(
            size=change.size,
            before=str(change.before),
            after=str(change.after),
            color=change.color,
        )
    assert isinstance(change, MediaChange)  # noqa: S101 - `Change` has exactly four members
    return MediaChangeDTO(rank=change.rank, before=change.before, after=change.after)


class DriftDTO(BaseModel):
    path: str
    last_applied: Any
    live: Any
    last_applied_label: str | None = None
    live_label: str | None = None


def _drift_dto(drift: Drift) -> DriftDTO:
    return DriftDTO(
        path=drift.path,
        last_applied=_jsonable(drift.last_applied),
        live=_jsonable(drift.live),
        last_applied_label=drift.last_applied_label,
        live_label=drift.live_label,
    )


class ActionDTO(BaseModel):
    description: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    missing_outputs: tuple[str, ...]


def _action_dto(action: Action) -> ActionDTO:
    return ActionDTO(
        description=action.description,
        inputs=action.inputs,
        outputs=action.outputs,
        missing_outputs=action.missing_outputs,
    )


# --------------------------------------------------------------- StagePlan/Plan


class StagePlanDTO(BaseModel):
    stage: str
    will_run: bool
    changes: tuple[ChangeDTO, ...] = ()
    drift: tuple[DriftDTO, ...] = ()
    reason: str | None = None
    actions: tuple[ActionDTO, ...] = ()
    blocked: str | None = None
    snapshot: dict[str, Any] | None = None
    """A stage's own ``snapshot()`` model, dumped generically (A30) --
    ``RenderSnapshot``, ``PrintifyProductSnapshot`` and the rest are each the
    producing stage's own type, and this module has no business importing
    five stage modules to name them. A frontend already has to know one
    stage's snapshot shape from another; this only spares it a sixth import
    that gains nothing over reading the field names off the wire."""


def stage_plan_dto(stage_plan: StagePlan) -> StagePlanDTO:
    return StagePlanDTO(
        stage=stage_plan.stage,
        will_run=stage_plan.will_run,
        changes=tuple(_change_dto(c) for c in stage_plan.changes),
        drift=tuple(_drift_dto(d) for d in stage_plan.drift),
        reason=stage_plan.reason,
        actions=tuple(_action_dto(a) for a in stage_plan.actions),
        blocked=stage_plan.blocked,
        snapshot=_jsonable(stage_plan.snapshot) if stage_plan.snapshot is not None else None,
    )


class PlanDTO(BaseModel):
    listing: str
    is_live: bool
    etsy_listing_id: int | None
    stage_plans: tuple[StagePlanDTO, ...]


def plan_dto(plan: Plan) -> PlanDTO:
    return PlanDTO(
        listing=plan.listing,
        is_live=plan.is_live,
        etsy_listing_id=plan.etsy_listing_id,
        stage_plans=tuple(stage_plan_dto(sp) for sp in plan.stage_plans),
    )


# ----------------------------------------------------------------------- events


class PhaseEvent(BaseModel):
    """The run (or one of the two run kinds) moved to a new phase. Always the
    first event of a run and always its last, whichever phase that turns out
    to be (A33, decision 7)."""

    type: Literal["phase"] = "phase"
    id: int
    phase: RunPhase
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StageCheckingEvent(BaseModel):
    type: Literal["stage_checking"] = "stage_checking"
    id: int
    listing: str
    stage: str


class StagePlannedEvent(BaseModel):
    type: Literal["stage_planned"] = "stage_planned"
    id: int
    listing: str
    stage_plan: StagePlanDTO


class ListingPlannedEvent(BaseModel):
    type: Literal["listing_planned"] = "listing_planned"
    id: int
    listing: str
    plan: PlanDTO
    fingerprint: str


class PreviewRenderedEvent(BaseModel):
    type: Literal["preview_rendered"] = "preview_rendered"
    id: int
    listing: str
    template: str
    colour: str | None


class StageApplyingEvent(BaseModel):
    type: Literal["stage_applying"] = "stage_applying"
    id: int
    listing: str
    stage: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProgressEvent(BaseModel):
    """``ctx.emit``'s ``Event``, tagged with whatever stage
    :class:`StageApplyingEvent` last named for this listing -- no stage
    changes how it reports progress (A33, decision 7)."""

    type: Literal["progress"] = "progress"
    id: int
    listing: str
    stage: str | None
    message: str
    swatches: tuple[tuple[int, int, int], ...] = ()


class StageAppliedEvent(BaseModel):
    type: Literal["stage_applied"] = "stage_applied"
    id: int
    listing: str
    stage: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StageFailedEvent(BaseModel):
    type: Literal["stage_failed"] = "stage_failed"
    id: int
    listing: str
    stage: str
    message: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ListingFailedEvent(BaseModel):
    """The run's ``RunObserver.on_failure`` twin. ``message`` is the
    :class:`~etsy_listings.errors.UserFacingError`'s own text, word for word
    (decision 5) -- never the generic internal-error text, which belongs to a
    :class:`PhaseEvent` naming the whole run ``failed`` instead, since a
    defect is not about any one listing. ``stale_plan`` is set only when the
    error was a :class:`~etsy_listings.engine.run.StalePlanError`."""

    type: Literal["listing_failed"] = "listing_failed"
    id: int
    listing: str
    message: str
    stale_plan: PlanDTO | None = None


AnyRunEvent = (
    PhaseEvent
    | StageCheckingEvent
    | StagePlannedEvent
    | ListingPlannedEvent
    | PreviewRenderedEvent
    | StageApplyingEvent
    | ProgressEvent
    | StageAppliedEvent
    | StageFailedEvent
    | ListingFailedEvent
)
"""The plain union, for internal storage (``registry.Run.events``) where no
discriminator annotation is needed to construct or inspect one."""

RunEvent = Annotated[AnyRunEvent, Field(discriminator="type")]
"""The typed union :class:`~etsy_listings.ui.api.schemas.RunDetail` exposes,
so ``openapi.json`` -- and ``gen:api`` after it -- carries every event shape a
frontend needs to switch on by ``type`` (A33, decision 7)."""
