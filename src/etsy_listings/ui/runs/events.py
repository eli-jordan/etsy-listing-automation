"""The ``RunEvent`` union the SSE route streams, and how a ``Plan``/``StagePlan``
turns into JSON (A33, decision 7).

Two things are true about the engine's own ``Plan``/``StagePlan``/``Change``
types that make them unfit to serialise directly. They are plain dataclasses,
and changes may carry a :class:`~etsy_listings.config.money.Money` that JSON
does not convert on its own. And the four ``Change`` shapes (``FieldChange``,
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

from pydantic import BaseModel, ConfigDict, Field

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
from etsy_listings.engine.stages.etsy_listing import EtsyListingSnapshot
from etsy_listings.engine.stages.etsy_media import EtsyMediaSnapshot
from etsy_listings.engine.stages.printify_product import ProductSnapshot
from etsy_listings.engine.stages.publish import PublishSnapshot
from etsy_listings.engine.stages.render import RenderSnapshot

RunKind = Literal["plan", "apply"]
RunScope = Literal["listings", "workspace"]

PlanRunPhase = Literal[
    "queued",
    "planning",
    "planned",
    "previewing",
    "ready",
    "failed",
    "cancelled",
]
ApplyRunPhase = Literal[
    "queued",
    "applying",
    "applied",
    "failed",
    "stale",
]
RunPhase = PlanRunPhase | ApplyRunPhase
"""The public union of two state machines. Registry state keeps the narrower
phase beside its matching command, so cross-kind transitions are rejected."""

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


class _StageOutcomeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdleOutcomeDTO(_StageOutcomeDTO):
    type: Literal["idle"] = "idle"


class WorkOutcomeDTO(_StageOutcomeDTO):
    type: Literal["work"] = "work"
    reason: str
    changes: tuple[ChangeDTO, ...] = ()
    actions: tuple[ActionDTO, ...] = ()


class BlockedOutcomeDTO(_StageOutcomeDTO):
    type: Literal["blocked"] = "blocked"
    message: str


StageOutcomeDTO = Annotated[
    IdleOutcomeDTO | WorkOutcomeDTO | BlockedOutcomeDTO,
    Field(discriminator="type"),
]


class _StagePlanDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: StageOutcomeDTO
    drift: tuple[DriftDTO, ...] = ()
    group: str | None = None
    """The stage this one is shown under -- the engine's answer, carried
    so the review nests ``etsy_videos`` under ``etsy_media`` without
    inferring it from a name (PRD 71)."""


class RenderStagePlanDTO(_StagePlanDTO):
    stage: Literal["render"] = "render"
    snapshot: RenderSnapshot | None = None


class ProductStagePlanDTO(_StagePlanDTO):
    stage: Literal["printify_product"] = "printify_product"
    snapshot: ProductSnapshot | None = None


class PublishStagePlanDTO(_StagePlanDTO):
    stage: Literal["publish"] = "publish"
    snapshot: PublishSnapshot | None = None


class EtsyListingStagePlanDTO(_StagePlanDTO):
    stage: Literal["etsy_listing"] = "etsy_listing"
    snapshot: EtsyListingSnapshot | None = None


class EtsyMediaStagePlanDTO(_StagePlanDTO):
    stage: Literal["etsy_media"] = "etsy_media"
    snapshot: EtsyMediaSnapshot | None = None


class RetractStagePlanDTO(_StagePlanDTO):
    stage: Literal["retract"] = "retract"
    snapshot: None = None


StagePlanDTO = Annotated[
    RenderStagePlanDTO
    | ProductStagePlanDTO
    | PublishStagePlanDTO
    | EtsyListingStagePlanDTO
    | EtsyMediaStagePlanDTO
    | RetractStagePlanDTO,
    Field(discriminator="stage"),
]


def _stage_plan_fields(stage_plan: StagePlan) -> dict[str, Any]:
    if stage_plan.will_run:
        reason = stage_plan.reason
        if reason is None:
            raise TypeError("a runnable stage plan must have a reason")
        outcome: StageOutcomeDTO = WorkOutcomeDTO(
            reason=reason,
            changes=tuple(_change_dto(c) for c in stage_plan.changes),
            actions=tuple(_action_dto(a) for a in stage_plan.actions),
        )
    elif stage_plan.blocked is not None:
        outcome = BlockedOutcomeDTO(message=stage_plan.blocked)
    else:
        outcome = IdleOutcomeDTO()
    return {
        "outcome": outcome,
        "drift": tuple(_drift_dto(d) for d in stage_plan.drift),
        "group": stage_plan.group,
    }


def _snapshot[SnapshotT: BaseModel](
    stage_plan: StagePlan, expected: type[SnapshotT]
) -> SnapshotT | None:
    snapshot = stage_plan.snapshot
    if snapshot is not None and not isinstance(snapshot, expected):
        raise TypeError(
            f"{stage_plan.stage} snapshot must be {expected.__name__}, "
            f"not {type(snapshot).__name__}"
        )
    return snapshot


def stage_plan_dto(
    stage_plan: StagePlan,
) -> (
    RenderStagePlanDTO
    | ProductStagePlanDTO
    | PublishStagePlanDTO
    | EtsyListingStagePlanDTO
    | EtsyMediaStagePlanDTO
    | RetractStagePlanDTO
):
    fields = _stage_plan_fields(stage_plan)
    if stage_plan.stage == "render":
        return RenderStagePlanDTO(**fields, snapshot=_snapshot(stage_plan, RenderSnapshot))
    if stage_plan.stage == "printify_product":
        return ProductStagePlanDTO(**fields, snapshot=_snapshot(stage_plan, ProductSnapshot))
    if stage_plan.stage == "publish":
        return PublishStagePlanDTO(**fields, snapshot=_snapshot(stage_plan, PublishSnapshot))
    if stage_plan.stage == "etsy_listing":
        return EtsyListingStagePlanDTO(
            **fields, snapshot=_snapshot(stage_plan, EtsyListingSnapshot)
        )
    if stage_plan.stage == "etsy_media":
        return EtsyMediaStagePlanDTO(**fields, snapshot=_snapshot(stage_plan, EtsyMediaSnapshot))
    if stage_plan.stage == "retract":
        if stage_plan.snapshot is not None:
            raise TypeError("retract does not have a snapshot")
        return RetractStagePlanDTO(**fields)
    raise ValueError(f"unknown stage {stage_plan.stage!r}")


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
    """Stage progress after the engine has attached its run identity."""

    type: Literal["progress"] = "progress"
    id: int
    listing: str
    stage: str
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
    """The engine's ``EngineListingFailed`` wire twin. ``message`` is the
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
