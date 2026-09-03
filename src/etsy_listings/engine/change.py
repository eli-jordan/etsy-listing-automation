"""The shared ``Change`` vocabulary. A2: each stage writes its own comparison, so
the shared surface here is the vocabulary and a handful of helpers -- not a
generic differ. Keeping the *mechanics* shared is what stops six near-identical
routines diverging."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from etsy_listings.config.money import Money


@dataclass(frozen=True)
class FieldChange:
    path: str
    before: Any
    after: Any


@dataclass(frozen=True)
class ListChange:
    path: str
    added: tuple[Any, ...]
    removed: tuple[Any, ...]
    reordered: bool = False


@dataclass(frozen=True)
class PriceChange:
    size: str
    before: Money
    after: Money
    color: str | None = None


@dataclass(frozen=True)
class MediaChange:
    rank: int
    before: str | None
    after: str | None


@dataclass(frozen=True)
class StageRun:
    stage: str
    reason: str


@dataclass(frozen=True)
class Drift:
    path: str
    last_applied: Any
    live: Any


Change = FieldChange | ListChange | PriceChange | MediaChange


def scalar(path: str, desired: Any, applied: Any) -> FieldChange | None:  # noqa: ANN401
    """Compare two scalar values (or equal-shaped pydantic models); ``None`` if unchanged."""
    if desired == applied:
        return None
    return FieldChange(path=path, before=applied, after=desired)


def sequence(path: str, desired: list[Any], applied: list[Any]) -> ListChange | None:
    """Compare two lists as sets-with-order; ``None`` if unchanged."""
    if desired == applied:
        return None
    added = tuple(item for item in desired if item not in applied)
    removed = tuple(item for item in applied if item not in desired)
    reordered = not added and not removed and desired != applied
    return ListChange(path=path, added=added, removed=removed, reordered=reordered)


def drift(path: str, applied: Any, live: Any) -> Drift | None:  # noqa: ANN401
    """Compare last-applied to live state; ``None`` if no drift."""
    if applied is None or live is None or applied == live:
        return None
    return Drift(path=path, last_applied=applied, live=live)


@dataclass(frozen=True)
class StagePlan:
    stage: str
    will_run: bool
    changes: tuple[Change, ...] = field(default_factory=tuple)
    drift: tuple[Drift, ...] = field(default_factory=tuple)
    reason: str | None = None


@dataclass(frozen=True)
class Plan:
    listing: str
    is_live: bool
    etsy_listing_id: int | None
    stage_plans: tuple[StagePlan, ...]

    @property
    def has_changes(self) -> bool:
        return any(sp.will_run or sp.changes for sp in self.stage_plans)

    @property
    def has_drift(self) -> bool:
        return any(sp.drift for sp in self.stage_plans)
