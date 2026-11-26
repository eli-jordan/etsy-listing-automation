from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from etsy_listings import __about__
from etsy_listings.core.ai import ProposalStore
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.config.money import Money
from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.change import Plan
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.events import (
    EngineEventSink,
    EngineListingFailed,
    EngineListingPlanned,
    EnginePreviewRendered,
    RunHooks,
    ignore_engine_event,
)
from etsy_listings.core.engine.lifecycle import after_apply
from etsy_listings.core.engine.lock import Lockfile, canonical_hash
from etsy_listings.core.engine.plan import PlannedRun, build_plan
from etsy_listings.core.engine.preview import render_pending
from etsy_listings.core.engine.stage import AnyStage
from etsy_listings.core.errors import UserFacingError

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


@dataclass(frozen=True)
class ListingOutcome:
    """What happened to one listing: its plan, or the reason it was abandoned.

    Exactly one of ``planned`` and ``error`` is set. A failure carries no plan
    even when it failed *after* planning -- an ``apply`` that got partway is
    not described by the plan it started from, and reporting one as though it
    had been carried out is worse than reporting none.

    ``error`` is a :class:`~etsy_listings.core.errors.UserFacingError` and nothing
    else. That is the whole point of the type: a config mistake, a design too
    small, a colour that does not exist are all things the *user* can act on,
    and a run must survive them to reach the next listing. A defect still
    propagates and still prints a traceback, because that is what a traceback
    is for.
    """

    listing: str
    planned: PlannedRun | None = None
    error: UserFacingError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class RunReport:
    outcomes: tuple[ListingOutcome, ...]

    @property
    def failed(self) -> bool:
        return any(not outcome.ok for outcome in self.outcomes)

    @property
    def failures(self) -> tuple[ListingOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.ok)


def fully_applied(outcome: ListingOutcome, lock: Lockfile) -> bool:
    """ADR-0050's *full success*; ``lock`` is the lockfile the apply left."""
    if not outcome.ok or outcome.planned is None:
        return False
    if any(stage_plan.blocked for stage_plan in outcome.planned.plan.stage_plans):
        return False
    return lock.incomplete is None


def _never_stop() -> bool:
    return False


class StalePlanError(UserFacingError):
    def __init__(self, listing: str, planned: PlannedRun) -> None:
        self.listing = listing
        self.planned = planned
        super().__init__(
            f"{listing} changed since it was planned. Plan again to review the current version."
        )


def plan_fingerprint(plan: Plan) -> str:
    reviewed = replace(
        plan, stage_plans=tuple(sp for sp in plan.stage_plans if not sp.chosen_at_apply)
    )
    return canonical_hash(_canonical_dataclass(reviewed))


def _canonical_dataclass(value: DataclassInstance) -> dict[str, object]:
    return {
        f.name: _canonical(getattr(value, f.name))
        for f in fields(value)
        if not f.metadata.get("unhashed")
    }


def _canonical(value: object) -> object:
    """``value`` as the ``dict``/``list``/scalar tree ``canonical_hash`` hashes.
    ``Money`` is checked first: it is a dataclass too, and a plan shows the
    string a listing wrote, not its ``Decimal`` amount."""
    if isinstance(value, Money):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_dataclass(value)
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    return value


def plan_listings(
    ctx: RunContext,
    listings: Sequence[str],
    stages: list[AnyStage],
    *,
    hooks: RunHooks = RunHooks(),
) -> RunReport:
    def work(listing: str) -> PlannedRun:
        planned = build_plan(
            ctx, listing, _read_lock(ctx, listing), stages, on_event=hooks.on_event
        )
        hooks.on_event(EngineListingPlanned(listing, planned.plan))
        return planned

    return _over(listings, work, hooks.on_event, should_stop=hooks.should_stop)


def preview_listing(
    ctx: RunContext,
    planned: PlannedRun,
    on_event: EngineEventSink = ignore_engine_event,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    listing = planned.plan.listing
    render_pending(
        ctx,
        planned,
        should_stop=should_stop or _never_stop,
        on_ready=lambda work: on_event(EnginePreviewRendered(listing, work.template, work.colour)),
    )


class _StopLatch:
    """``should_stop`` for one listing's ``execute``, remembering whether it
    ever answered True. `execute` breaks out of its loop the first time it
    does, so remembering that answer is knowing it stopped."""

    def __init__(self, stop: Callable[[], bool]) -> None:
        self._stop = stop
        self.halted = False

    def __call__(self) -> bool:
        self.halted = self.halted or self._stop()
        return self.halted


@dataclass(frozen=True)
class _ApplyListing:
    ctx: RunContext
    stages: list[AnyStage]
    hooks: RunHooks
    expect: Mapping[str, str] | None

    def __call__(self, listing: str) -> PlannedRun:
        ctx, on_event = self.ctx, self.hooks.on_event
        lock = _read_lock(ctx, listing)
        planned = build_plan(ctx, listing, lock, self.stages, on_event=on_event)
        self._check_expected(listing, planned)
        on_event(EngineListingPlanned(listing, planned.plan))
        lock_file = ctx.workspace.lock_file(listing)
        stop_here = _StopLatch(self.hooks.should_stop)
        applied = execute(
            ctx,
            planned,
            lock,
            hooks=RunHooks(on_event, stop_here),
            record=lambda updated: updated.write(lock_file),
        )
        if stop_here.halted:
            return planned
        after_apply(ctx, listing, planned)
        if fully_applied(ListingOutcome(listing=listing, planned=planned), applied):
            ProposalStore(ctx.workspace).remove(listing)
            if ctx.workspace.listing_file(listing).is_file():
                BatchStore(ctx.workspace).mark_deployed(listing)
        return planned

    def _check_expected(self, listing: str, planned: PlannedRun) -> None:
        if self.expect is not None and listing in self.expect:
            fingerprint = plan_fingerprint(planned.plan)
            if fingerprint != self.expect[listing]:
                raise StalePlanError(listing, planned)


def apply_listings(
    ctx: RunContext,
    listings: Sequence[str],
    stages: list[AnyStage],
    *,
    hooks: RunHooks = RunHooks(),
    expect: Mapping[str, str] | None = None,
) -> RunReport:
    work = _ApplyListing(ctx, stages, hooks, expect)
    return _over(listings, work, hooks.on_event, should_stop=hooks.should_stop)


def _over(
    listings: Sequence[str],
    work: Callable[[str], PlannedRun],
    on_event: EngineEventSink,
    *,
    should_stop: Callable[[], bool] = _never_stop,
) -> RunReport:
    outcomes: list[ListingOutcome] = []
    for listing in listings:
        if should_stop():
            break
        try:
            planned = work(listing)
        except UserFacingError as exc:
            on_event(EngineListingFailed(listing, exc))
            outcomes.append(ListingOutcome(listing=listing, error=exc))
        else:
            outcomes.append(ListingOutcome(listing=listing, planned=planned))
    return RunReport(outcomes=tuple(outcomes))


def _read_lock(ctx: RunContext, listing: str) -> Lockfile:
    """This listing's lockfile, or an empty one if it has never been applied.

    The empty one is stamped with the current version and time so that the
    document is well-formed from the moment it exists; ``execute`` re-stamps
    it with the version and time that actually applied it.
    """
    existing = Lockfile.read(ctx.workspace.lock_file(listing))
    if existing is not None:
        return existing
    return Lockfile.empty(
        tool_version=__about__.VERSION,
        applied_at=datetime.now(UTC).isoformat(),
    )
