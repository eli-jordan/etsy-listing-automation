"""The shared ``Change`` vocabulary. A2: each stage writes its own comparison, so
the shared surface here is the vocabulary and a handful of helpers -- not a
generic differ. Keeping the *mechanics* shared is what stops six near-identical
routines diverging."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

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
    last_applied_label: str | None = None
    live_label: str | None = None
    """A30: a human name in place of ``last_applied``/``live``'s raw id, when
    the stage that found the drift can name one. ``None`` by default -- most
    drift is already scalar text (a title, a boolean) with nothing to name,
    and a stage with no catalog to ask (``product_diff``, ``publish``) simply
    never sets these. Filled by `etsy_listing._drift` from the
    :class:`~etsy_listings.clients.etsy.shopcatalog.EtsyShopCatalog` A25
    already resolved this run, so naming an id costs no request `plan()`'s own
    comparison was not already going to make -- `plan()` stays pure (no
    client) by never asking one itself."""


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


def drift(
    path: str,
    applied: Any,  # noqa: ANN401
    live: Any,  # noqa: ANN401
    *,
    last_applied_label: str | None = None,
    live_label: str | None = None,
) -> Drift | None:
    """Compare last-applied to live state; ``None`` if no drift."""
    if applied is None or live is None or applied == live:
        return None
    return Drift(
        path=path,
        last_applied=applied,
        live=live,
        last_applied_label=last_applied_label,
        live_label=live_label,
    )


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
class StageIdle:
    """The stage has nothing to do."""


@dataclass(frozen=True)
class StageWork:
    """The stage will run, with the reason and work inseparable."""

    reason: str
    changes: tuple[Change, ...] = field(default_factory=tuple)
    actions: tuple[Action, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StageBlocked:
    """The stage cannot run, with the user-facing refusal inseparable."""

    message: str


StageOutcome = StageIdle | StageWork | StageBlocked
"""The only three answers a stage can give (A33).

The former product of ``will_run``, ``reason``, ``blocked``, changes and
actions admitted contradictions that the repository's invariants explicitly
forbid. The union is the stored truth; compatibility properties on
:class:`Verdict` and :class:`StagePlan` are derived views for renderers.
"""


@dataclass(frozen=True)
class Verdict:
    """What a stage's ``plan()`` decided, before the engine says whose it is."""

    outcome: StageOutcome
    drift: tuple[Drift, ...] = field(default_factory=tuple)

    @classmethod
    def no_work(cls, *, drift: tuple[Drift, ...] = ()) -> Verdict:
        """Nothing to do. The common answer, and the one worth not spelling."""
        return cls(outcome=StageIdle(), drift=drift)

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
        return cls(outcome=StageBlocked(message=message), drift=drift)

    @classmethod
    def work(
        cls,
        reason: str,
        *,
        changes: tuple[Change, ...] = (),
        drift: tuple[Drift, ...] = (),
        actions: tuple[Action, ...] = (),
    ) -> Verdict:
        """Work to do, and why -- the two being inseparable is the point.

        ``will_run`` used to be an expression standing beside a ``reason``
        string that restated it, so a stage could run while reporting no
        reason, or report one while not running. Here a reason is required and
        ``will_run`` follows from it.
        """
        return cls(
            outcome=StageWork(reason=reason, changes=changes, actions=actions),
            drift=drift,
        )

    @property
    def will_run(self) -> bool:
        return isinstance(self.outcome, StageWork)

    @property
    def changes(self) -> tuple[Change, ...]:
        return self.outcome.changes if isinstance(self.outcome, StageWork) else ()

    @property
    def reason(self) -> str | None:
        return self.outcome.reason if isinstance(self.outcome, StageWork) else None

    @property
    def actions(self) -> tuple[Action, ...]:
        return self.outcome.actions if isinstance(self.outcome, StageWork) else ()

    @property
    def refusal(self) -> str | None:
        return self.outcome.message if isinstance(self.outcome, StageBlocked) else None


@dataclass(frozen=True)
class StagePlan:
    """One stage's named outcome, drift evidence and optional review facts.

    The outcome owns the mutually exclusive idle/work/blocked decision.
    ``snapshot`` carries unchanged facts for review and remains excluded from
    the A31 fingerprint.
    """

    stage: str
    outcome: StageOutcome
    drift: tuple[Drift, ...] = field(default_factory=tuple)
    snapshot: BaseModel | None = None

    @classmethod
    def no_work(
        cls,
        stage: str,
        *,
        drift: tuple[Drift, ...] = (),
        snapshot: BaseModel | None = None,
    ) -> StagePlan:
        return cls(stage=stage, outcome=StageIdle(), drift=drift, snapshot=snapshot)

    @classmethod
    def work(
        cls,
        stage: str,
        reason: str,
        *,
        changes: tuple[Change, ...] = (),
        drift: tuple[Drift, ...] = (),
        actions: tuple[Action, ...] = (),
        snapshot: BaseModel | None = None,
    ) -> StagePlan:
        return cls(
            stage=stage,
            outcome=StageWork(reason=reason, changes=changes, actions=actions),
            drift=drift,
            snapshot=snapshot,
        )

    @classmethod
    def block(cls, stage: str, message: str) -> StagePlan:
        return cls(stage=stage, outcome=StageBlocked(message=message))

    @property
    def will_run(self) -> bool:
        return isinstance(self.outcome, StageWork)

    @property
    def changes(self) -> tuple[Change, ...]:
        return self.outcome.changes if isinstance(self.outcome, StageWork) else ()

    @property
    def reason(self) -> str | None:
        return self.outcome.reason if isinstance(self.outcome, StageWork) else None

    @property
    def actions(self) -> tuple[Action, ...]:
        return self.outcome.actions if isinstance(self.outcome, StageWork) else ()

    @property
    def blocked(self) -> str | None:
        return self.outcome.message if isinstance(self.outcome, StageBlocked) else None


@dataclass(frozen=True)
class Plan:
    listing: str
    is_live: bool
    etsy_listing_id: int | None
    stage_plans: tuple[StagePlan, ...]

    @property
    def has_changes(self) -> bool:
        return any(sp.will_run for sp in self.stage_plans)

    @property
    def has_drift(self) -> bool:
        return any(sp.drift for sp in self.stage_plans)
