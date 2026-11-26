from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from functools import singledispatch
from pathlib import Path
from typing import Annotated, Any, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field

from etsy_listings.core.config.money import Money
from etsy_listings.core.engine.change import (
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
from etsy_listings.core.engine.stages.etsy_listing import EtsyListingSnapshot
from etsy_listings.core.engine.stages.etsy_media import EtsyMediaSnapshot
from etsy_listings.core.engine.stages.etsy_videos import EtsyVideosSnapshot
from etsy_listings.core.engine.stages.printify_product import ProductSnapshot
from etsy_listings.core.engine.stages.publish import PublishSnapshot
from etsy_listings.core.engine.stages.render import RenderSnapshot

RunKind = Literal["plan", "apply"]
RunScope = Literal["listings", "workspace", "batch"]

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
this to know when to close the stream (``server/api/runs.py``); the registry polls it
to know a listing's lock may be released."""


@singledispatch
def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    return value


@_jsonable.register(Money)
def _money(value: Money) -> str:
    return str(value)


@_jsonable.register(BaseModel)
def _model(value: BaseModel) -> Any:
    return value.model_dump(mode="json")


@_jsonable.register(Path)
def _path(value: Path) -> str:
    return value.as_posix()


@_jsonable.register(Enum)
def _enum(value: Enum) -> Any:
    return value.value


@_jsonable.register(list)
@_jsonable.register(tuple)
def _sequence(value: list[Any] | tuple[Any, ...]) -> list[Any]:
    return [_jsonable(item) for item in value]


@_jsonable.register(dict)
def _mapping(value: dict[Any, Any]) -> dict[Any, Any]:
    return {key: _jsonable(item) for key, item in value.items()}


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
    match change:
        case FieldChange():
            return FieldChangeDTO(
                path=change.path, before=_jsonable(change.before), after=_jsonable(change.after)
            )
        case ListChange():
            return ListChangeDTO(
                path=change.path,
                added=tuple(_jsonable(item) for item in change.added),
                removed=tuple(_jsonable(item) for item in change.removed),
                reordered=change.reordered,
            )
        case PriceChange():
            return PriceChangeDTO(
                size=change.size,
                before=str(change.before),
                after=str(change.after),
                color=change.color,
            )
        case MediaChange():
            return MediaChangeDTO(rank=change.rank, before=change.before, after=change.after)
        case _:
            assert_never(change)


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
    inferring it from a name."""


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


class EtsyVideosStagePlanDTO(_StagePlanDTO):
    stage: Literal["etsy_videos"] = "etsy_videos"
    snapshot: EtsyVideosSnapshot | None = None


class RetractStagePlanDTO(_StagePlanDTO):
    stage: Literal["retract"] = "retract"
    snapshot: None = None


class EtsyActivateStagePlanDTO(_StagePlanDTO):
    """Only in a run that asked to publish drafts (``publishing_pipeline``)."""

    stage: Literal["etsy_activate"] = "etsy_activate"
    snapshot: None = None


StagePlanDTO = Annotated[
    RenderStagePlanDTO
    | ProductStagePlanDTO
    | PublishStagePlanDTO
    | EtsyListingStagePlanDTO
    | EtsyMediaStagePlanDTO
    | EtsyVideosStagePlanDTO
    | RetractStagePlanDTO
    | EtsyActivateStagePlanDTO,
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


_SnapshotStagePlanDTO = (
    RenderStagePlanDTO
    | ProductStagePlanDTO
    | PublishStagePlanDTO
    | EtsyListingStagePlanDTO
    | EtsyMediaStagePlanDTO
    | EtsyVideosStagePlanDTO
)
_SNAPSHOT_STAGES: dict[str, Callable[[StagePlan, dict[str, Any]], _SnapshotStagePlanDTO]] = {
    "render": lambda sp, values: RenderStagePlanDTO(
        **values, snapshot=_snapshot(sp, RenderSnapshot)
    ),
    "printify_product": lambda sp, values: ProductStagePlanDTO(
        **values, snapshot=_snapshot(sp, ProductSnapshot)
    ),
    "publish": lambda sp, values: PublishStagePlanDTO(
        **values, snapshot=_snapshot(sp, PublishSnapshot)
    ),
    "etsy_listing": lambda sp, values: EtsyListingStagePlanDTO(
        **values, snapshot=_snapshot(sp, EtsyListingSnapshot)
    ),
    "etsy_media": lambda sp, values: EtsyMediaStagePlanDTO(
        **values, snapshot=_snapshot(sp, EtsyMediaSnapshot)
    ),
    "etsy_videos": lambda sp, values: EtsyVideosStagePlanDTO(
        **values, snapshot=_snapshot(sp, EtsyVideosSnapshot)
    ),
}


def stage_plan_dto(
    stage_plan: StagePlan,
) -> (
    RenderStagePlanDTO
    | ProductStagePlanDTO
    | PublishStagePlanDTO
    | EtsyListingStagePlanDTO
    | EtsyMediaStagePlanDTO
    | EtsyVideosStagePlanDTO
    | RetractStagePlanDTO
    | EtsyActivateStagePlanDTO
):
    fields = _stage_plan_fields(stage_plan)
    if stage_plan.stage in {"retract", "etsy_activate"}:
        if stage_plan.snapshot is not None:
            raise TypeError(f"{stage_plan.stage} does not have a snapshot")
        if stage_plan.stage == "retract":
            return RetractStagePlanDTO(**fields)
        return EtsyActivateStagePlanDTO(**fields)
    if stage_plan.stage not in _SNAPSHOT_STAGES:
        raise ValueError(f"unknown stage {stage_plan.stage!r}")
    return _SNAPSHOT_STAGES[stage_plan.stage](stage_plan, fields)


class PlanDTO(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    listing: str
    is_live: bool
    etsy_listing_id: int | None
    stage_plans: tuple[StagePlanDTO, ...]
    publishable: bool = False
    """An apply that opts in to publishing would make this listing live on
    Etsy (``Plan.publishable``)."""


def plan_dto(plan: Plan) -> PlanDTO:
    return PlanDTO(
        listing=plan.listing,
        is_live=plan.is_live,
        etsy_listing_id=plan.etsy_listing_id,
        stage_plans=tuple(stage_plan_dto(sp) for sp in plan.stage_plans),
        publishable=plan.publishable,
    )


class PhaseEvent(BaseModel):
    """The run (or one of the two run kinds) moved to a new phase. Always the
    first event of a run and always its last, whichever phase that turns out
    to be."""

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
    :class:`~etsy_listings.core.errors.UserFacingError`'s own text, word for
    word, or the generic internal-error text for a defect, which also fails
    the run. ``stale_plan`` is set only when the error was a
    :class:`~etsy_listings.core.engine.run.StalePlanError`."""

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
"""The typed union :class:`~etsy_listings.server.api.schemas.RunDetail` exposes,
so ``openapi.json`` -- and ``gen:api`` after it -- carries every event shape a
frontend needs to switch on by ``type``."""
