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
class Action:
    """One concrete unit of work a stage will perform if applied, with the
    files it reads and the files it writes.

    ``plan`` is meant to answer "what would happen, exactly?", not just "does
    something need to happen?" -- a stage that reports ``will_run`` without
    saying what it will read and write leaves the user guessing. Paths are
    workspace-relative and forward-slashed, the same form that enters a hash
    (see ``to_workspace_relative_posix``), so plan output is identical on
    Windows and Linux.

    ``missing_outputs`` is the subset of ``outputs`` that does not exist on
    disk right now. It is the stage that observes this, never the renderer:
    presentation may not stat a file (A2).
    """

    description: str
    inputs: tuple[str, ...] = field(default_factory=tuple)
    outputs: tuple[str, ...] = field(default_factory=tuple)
    missing_outputs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Verdict:
    """What a stage's ``plan()`` decided, before the engine says whose it is.

    A :class:`StagePlan` minus two things a stage has no business supplying.

    ``stage`` is gone because every stage wrote ``stage=self.name`` into every
    plan it returned -- the engine already knows which stage it asked, and a
    name a stage stamps for itself is a name it can stamp wrongly.

    ``blocked`` is gone because a stage does not decide how a refusal is
    *presented* -- it says one is warranted, and the engine turns it into
    :attr:`StagePlan.blocked` beside the ones ``desired()`` raised. Which
    leaves three answers a stage can give, and no fourth: nothing to do, work
    to do and why, or a refusal.
    """

    will_run: bool
    changes: tuple[Change, ...] = field(default_factory=tuple)
    drift: tuple[Drift, ...] = field(default_factory=tuple)
    reason: str | None = None
    actions: tuple[Action, ...] = field(default_factory=tuple)
    refusal: str | None = None
    """Why this stage cannot run, when only the live state could prove it.

    A ``str`` and not a :class:`~etsy_listings.engine.stage.Blocked` because
    ``stage`` imports *this* module, not the other way about -- but it carries
    the same contract, and reaches the user through the same
    :attr:`StagePlan.blocked` field: first line the consequence, any further
    lines the remedy.
    """

    @classmethod
    def no_work(cls) -> Verdict:
        """Nothing to do. The common answer, and the one worth not spelling."""
        return cls(will_run=False)

    @classmethod
    def refused(cls, message: str, *, drift: tuple[Drift, ...] = ()) -> Verdict:
        """This stage cannot run, and the live state is what says so.

        The pre-flight half of the same idea is ``desired()`` returning
        ``Blocked``, and it covers every refusal that can be decided from
        config alone. This covers the rest: a retail price below Printify's
        cost needs ``variants[].cost``, which exists only on a product that
        already exists (PRD 40's amendment), so the check *cannot* happen
        before ``read_live``.

        The alternative it replaces was a verdict that would not run carrying
        a ``reason`` -- and ``cli.render`` prints a reason only for stages
        that do run, so the refusal reached nobody: the listing was skipped
        under a plan reading "No changes." A refusal that renders as silence
        is worse than no check at all, because it looks like agreement.

        ``drift`` still travels: what Etsy has drifted to is worth reporting
        whether or not this run is allowed to fix it.
        """
        return cls(will_run=False, refusal=message, drift=drift)

    @classmethod
    def work(cls, reason: str, *, actions: tuple[Action, ...] = (), **rest: Any) -> Verdict:  # noqa: ANN401
        """Work to do, and why -- the two being inseparable is the point.

        ``will_run`` used to be an expression standing beside a ``reason``
        string that restated it, so a stage could run while reporting no
        reason, or report one while not running. Here a reason is required and
        ``will_run`` follows from it.
        """
        return cls(will_run=True, reason=reason, actions=actions, **rest)


@dataclass(frozen=True)
class StagePlan:
    stage: str
    will_run: bool
    changes: tuple[Change, ...] = field(default_factory=tuple)
    drift: tuple[Drift, ...] = field(default_factory=tuple)
    reason: str | None = None
    actions: tuple[Action, ...] = field(default_factory=tuple)
    blocked: str | None = None
    """Why this stage cannot run at all, if it cannot.

    Distinct from ``reason``, which says why a stage *will* run. A blocked
    stage does nothing and is not counted as work -- but it must still be
    shown, because the alternative is what shipped first: a workspace with an
    entire unrun stage reporting "No changes." and the user reasonably
    concluding the tool had nothing to do."""


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
