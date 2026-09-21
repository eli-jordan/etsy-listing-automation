"""The closed event vocabulary emitted while the engine runs (A33).

These are domain values, not the UI server's wire models. A caller learns one
interface and receives one ordered stream; adapters decide which events to
render or serialise.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import Swatch
from etsy_listings.errors import UserFacingError


@dataclass(frozen=True)
class EngineStageChecking:
    listing: str
    stage: str


@dataclass(frozen=True)
class EngineStagePlanned:
    listing: str
    stage_plan: StagePlan


@dataclass(frozen=True)
class EngineListingPlanned:
    listing: str
    plan: Plan


@dataclass(frozen=True)
class EngineListingFailed:
    listing: str
    error: UserFacingError


@dataclass(frozen=True)
class EnginePreviewRendered:
    listing: str
    template: str
    colour: str | None


@dataclass(frozen=True)
class EngineStageApplying:
    listing: str
    stage: str


@dataclass(frozen=True)
class EngineProgress:
    listing: str
    stage: str
    message: str
    swatches: tuple[Swatch, ...] = ()


@dataclass(frozen=True)
class EngineStageApplied:
    listing: str
    stage: str


@dataclass(frozen=True)
class EngineStageFailed:
    listing: str
    stage: str
    message: str


EngineRunEvent = (
    EngineStageChecking
    | EngineStagePlanned
    | EngineListingPlanned
    | EngineListingFailed
    | EnginePreviewRendered
    | EngineStageApplying
    | EngineProgress
    | EngineStageApplied
    | EngineStageFailed
)
EngineEventSink = Callable[[EngineRunEvent], None]


def ignore_engine_event(event: EngineRunEvent) -> None:
    """The default sink for callers interested only in the final report."""
