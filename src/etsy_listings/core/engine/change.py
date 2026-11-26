from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from etsy_listings.core.config.money import Money


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
    """``before == after``: same image, new bytes (a re-rendered mockup)."""

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
    """ADR-0038: a human name for ``last_applied``/``live``'s raw id, from the
    shop catalog already resolved this run, so ``plan()`` stays pure."""


Change = FieldChange | ListChange | PriceChange | MediaChange


def scalar(path: str, desired: Any, applied: Any) -> FieldChange | None:
    if desired == applied:
        return None
    return FieldChange(path=path, before=applied, after=desired)


def sequence(path: str, desired: list[Any], applied: list[Any]) -> ListChange | None:
    if desired == applied:
        return None
    added = tuple(item for item in desired if item not in applied)
    removed = tuple(item for item in applied if item not in desired)
    reordered = not added and not removed and desired != applied
    return ListChange(path=path, added=added, removed=removed, reordered=reordered)


def drift(
    path: str,
    applied: Any,
    live: Any,
    *,
    last_applied_label: str | None = None,
    live_label: str | None = None,
) -> Drift | None:
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
    """``missing_outputs`` is the subset of ``outputs`` that does not exist on
    disk right now. It is the stage that observes this, never the renderer:
    presentation may not stat a file.
    """

    description: str
    inputs: tuple[str, ...] = field(default_factory=tuple)
    outputs: tuple[str, ...] = field(default_factory=tuple)
    missing_outputs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StageIdle:
    pass


@dataclass(frozen=True)
class StageWork:
    reason: str
    changes: tuple[Change, ...] = field(default_factory=tuple)
    actions: tuple[Action, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StageBlocked:
    message: str


StageOutcome = StageIdle | StageWork | StageBlocked
"""The only three answers a stage can give. The union is the stored truth; the
properties on :class:`Verdict` and :class:`StagePlan` are views of it."""


class _OutcomeView:
    outcome: StageOutcome

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


@dataclass(frozen=True)
class Verdict(_OutcomeView):
    """What a stage's ``plan()`` decided, before the engine says whose it is."""

    outcome: StageOutcome
    drift: tuple[Drift, ...] = field(default_factory=tuple)

    @classmethod
    def no_work(cls, *, drift: tuple[Drift, ...] = ()) -> Verdict:
        return cls(outcome=StageIdle(), drift=drift)

    @classmethod
    def refused(cls, message: str, *, drift: tuple[Drift, ...] = ()) -> Verdict:
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
        return cls(
            outcome=StageWork(reason=reason, changes=changes, actions=actions),
            drift=drift,
        )

    @property
    def refusal(self) -> str | None:
        return self.outcome.message if isinstance(self.outcome, StageBlocked) else None


UNHASHED: dict[str, bool] = {"unhashed": True}
"""``field`` metadata for a :class:`StagePlan` field the ADR-0039 plan
fingerprint leaves out."""


@dataclass(frozen=True)
class StagePlan(_OutcomeView):
    stage: str
    outcome: StageOutcome
    drift: tuple[Drift, ...] = field(default_factory=tuple)
    snapshot: BaseModel | None = field(default=None, metadata=UNHASHED)
    group: str | None = None
    """``Stage.group``, stamped by the engine like ``stage``."""

    review_hash: str | None = None
    """Stable execution inputs not expressed by changes/actions (ADR-0039).
    Separate from display snapshots, so preview availability cannot stale a review."""

    chosen_at_apply: bool = field(default=False, metadata=UNHASHED)
    """``Stage.chosen_at_apply``, stamped by the engine like ``group``."""

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
        work: StageWork,
        *,
        drift: tuple[Drift, ...] = (),
        snapshot: BaseModel | None = None,
    ) -> StagePlan:
        return cls(stage=stage, outcome=work, drift=drift, snapshot=snapshot)

    @classmethod
    def block(
        cls,
        stage: str,
        message: str,
        *,
        group: str | None = None,
        chosen_at_apply: bool = False,
    ) -> StagePlan:
        return cls(
            stage=stage,
            outcome=StageBlocked(message=message),
            group=group,
            chosen_at_apply=chosen_at_apply,
        )

    @property
    def blocked(self) -> str | None:
        return self.outcome.message if isinstance(self.outcome, StageBlocked) else None


@dataclass(frozen=True)
class Plan:
    listing: str
    is_live: bool
    etsy_listing_id: int | None
    stage_plans: tuple[StagePlan, ...]
    publishable: bool = False
    """An opt-in apply would make this listing live on Etsy: the review shows
    the publish choice, which the apply makes without planning again."""

    @property
    def has_changes(self) -> bool:
        return any(sp.will_run for sp in self.stage_plans)

    @property
    def has_drift(self) -> bool:
        return any(sp.drift for sp in self.stage_plans)
