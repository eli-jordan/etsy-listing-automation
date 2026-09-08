"""Running the pipeline over a set of listings, and what came of each. PRD 16.

The shape of a *run* -- read the listing's lockfile, plan it, execute it,
write the lockfile back, and carry on when one of them fails -- used to live
in ``cli/app.py``, in a private helper taking a callback. None of it is
presentation: the lockfile's path and lifecycle are engine concerns, the tool
version and the clock stamped into it are engine concerns, and PRD 16's
"one bad listing must not halt fifty good ones" is a product rule that has to
hold whichever entry point drives it. The only thing the CLI added was the
words.

So this module is to ``build_plan``/``execute`` what
:class:`~etsy_listings.engine.change.Plan` is to ``cli.render.format_plan``:
the same seam, one level up. ``cli`` formats the :class:`RunReport`; the UI
(Phase 5) will serialise it; neither re-derives what a run does, and PRD 16 is
now testable without a terminal.

**Two sinks, because a batch has two moments worth watching.** ``on_planned``
fires the instant a listing's plan is ready -- before ``apply`` starts
executing it -- which is where the CLI prints the plan, or the header and the
blocked-stage warnings. ``on_failure`` fires when a listing is abandoned. Both
exist so output stays interleaved with the work: a ``--all`` run over a real
catalogue should print as it goes, not save everything for the end. The
returned report is the same information for a caller that wants it in one
piece rather than as it happens.

Nothing here formats, and nothing here decides an exit code -- that is
``cli``'s to take from :attr:`RunReport.failed`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from etsy_listings import __about__
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, build_plan
from etsy_listings.engine.stage import AnyStage
from etsy_listings.errors import UserFacingError


@dataclass(frozen=True)
class ListingOutcome:
    """What happened to one listing: its plan, or the reason it was abandoned.

    Exactly one of ``planned`` and ``error`` is set. A failure carries no plan
    even when it failed *after* planning -- an ``apply`` that got partway is
    not described by the plan it started from, and reporting one as though it
    had been carried out is worse than reporting none.

    ``error`` is a :class:`~etsy_listings.errors.UserFacingError` and nothing
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
    """Every listing a run touched, in the order it touched them."""

    outcomes: tuple[ListingOutcome, ...]

    @property
    def failed(self) -> bool:
        """Whether any listing was abandoned -- the CLI's exit code, and the
        one thing a batch's *caller* has to know that watching it go by does
        not tell you."""
        return any(not outcome.ok for outcome in self.outcomes)

    @property
    def failures(self) -> tuple[ListingOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.ok)


PlannedSink = Callable[[str, PlannedRun], None]
"""Called with a listing's name and its plan, the moment the plan is ready."""

FailureSink = Callable[[str, UserFacingError], None]
"""Called with a listing's name and the reason it was abandoned."""


def _ignore_planned(listing: str, planned: PlannedRun) -> None:
    return None


def _ignore_failure(listing: str, error: UserFacingError) -> None:
    return None


def plan_listings(
    ctx: RunContext,
    listings: Sequence[str],
    stages: list[AnyStage],
    *,
    on_planned: PlannedSink = _ignore_planned,
    on_failure: FailureSink = _ignore_failure,
) -> RunReport:
    """Plan every listing. Reads only -- nothing is created or written."""

    def work(listing: str) -> PlannedRun:
        planned = build_plan(ctx, listing, _read_lock(ctx, listing), stages)
        on_planned(listing, planned)
        return planned

    return _over(listings, work, on_failure)


def apply_listings(
    ctx: RunContext,
    listings: Sequence[str],
    stages: list[AnyStage],
    *,
    on_planned: PlannedSink = _ignore_planned,
    on_failure: FailureSink = _ignore_failure,
) -> RunReport:
    """Plan and then execute every listing, writing each lockfile as it goes.

    The lockfile is written per listing rather than at the end of the batch,
    which is what makes a half-finished ``--all`` run resumable: the listings
    that succeeded have recorded that they did, and re-running skips them.
    """

    def work(listing: str) -> PlannedRun:
        lock = _read_lock(ctx, listing)
        planned = build_plan(ctx, listing, lock, stages)
        on_planned(listing, planned)
        execute(ctx, planned, lock).write(ctx.workspace.lock_file(listing))
        return planned

    return _over(listings, work, on_failure)


def _over(
    listings: Sequence[str],
    work: Callable[[str], PlannedRun],
    on_failure: FailureSink,
) -> RunReport:
    """Run ``work`` per listing, continuing past any refusal the user can act on.

    PRD 16. The exception is caught here rather than inside ``work`` so that
    every step of a listing -- loading its lockfile, planning it, executing it
    -- is covered by the same rule, and adding a step later cannot quietly
    escape it.
    """
    outcomes: list[ListingOutcome] = []
    for listing in listings:
        try:
            planned = work(listing)
        except UserFacingError as exc:
            on_failure(listing, exc)
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
