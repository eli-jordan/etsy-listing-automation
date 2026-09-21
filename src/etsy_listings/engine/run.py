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

**One event sink, not a callback bundle that grows.** Planning, previewing and
applying emit values from the closed :data:`EngineRunEvent` union through one
ordered sink. Adapters may ignore events they do not render; adding an event
does not change the orchestration signatures.

Nothing here formats, and nothing here decides an exit code -- that is
``cli``'s to take from :attr:`RunReport.failed`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any

from etsy_listings import __about__
from etsy_listings.config.money import Money
from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.events import (
    EngineEventSink,
    EngineListingFailed,
    EngineListingPlanned,
    EnginePreviewRendered,
    ignore_engine_event,
)
from etsy_listings.engine.lifecycle import after_apply
from etsy_listings.engine.lock import Lockfile, canonical_hash
from etsy_listings.engine.plan import PlannedRun, build_plan
from etsy_listings.engine.preview import render_pending
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


def _never_stop() -> bool:
    return False


class StalePlanError(UserFacingError):
    """``apply`` was asked to run a plan whose fingerprint no longer matches
    what re-planning this listing produces right now (A31).

    Carries the fresh :class:`~etsy_listings.engine.plan.PlannedRun`, so a
    caller that reviewed a stale plan -- the editor, in a later PR -- can show
    what changed rather than only that it did. Raised **before** ``execute``
    runs a single stage: acting on a plan that may no longer describe the
    live state (Etsy drifted, or a hand edit changed ``listing.yaml``) would
    risk reverting something the reviewer never saw reverted. It is a
    :class:`~etsy_listings.errors.UserFacingError`, so PRD 16 already covers
    it -- one stale listing in a many-listing ``apply`` does not stop the rest.
    """

    def __init__(self, listing: str, planned: PlannedRun) -> None:
        self.listing = listing
        self.planned = planned
        super().__init__(
            f"{listing} changed since it was planned. Plan again to review the current version."
        )


def plan_fingerprint(plan: Plan) -> str:
    """A stable digest of everything a plan reviewed (A31).

    :func:`~etsy_listings.engine.lock.canonical_hash` over a canonical
    rendering of ``plan``, with every
    :attr:`~etsy_listings.engine.change.StagePlan.snapshot` left out and every
    :class:`~etsy_listings.config.money.Money` rendered as the string a
    listing would recognise (``"349 NOK"``) rather than a ``Decimal``
    ``json.dumps`` cannot serialise.

    Snapshots are excluded deliberately: they carry things that can change
    between two otherwise-identical plans -- an Etsy CDN URL, whether a
    preview has rendered yet -- and hashing one would make ``apply`` refuse a
    plan nobody actually disagreed with. Everything else is hashed on
    purpose, drift and ``actions`` included: if Etsy drifted between review
    and apply, applying without a fresh review would revert something the
    user never saw reverted.
    """
    canonical = _canonical(plan)
    assert isinstance(canonical, dict)  # noqa: S101 - `Plan` is a dataclass; see `_canonical`
    return canonical_hash(canonical)


def _canonical(value: Any) -> Any:  # noqa: ANN401 - a generic tree walk, by construction
    """``value``, rendered into the ``dict``/``list``/scalar tree
    :func:`~etsy_listings.engine.lock.canonical_hash` can hash.

    A stage's ``snapshot`` is dropped by name rather than by type, which is
    safe because no other field on :class:`~etsy_listings.engine.change.Plan`,
    :class:`~etsy_listings.engine.change.StagePlan` or a ``Change`` is ever
    called ``snapshot``. ``Money`` is checked before the generic dataclass
    branch below, since it is itself a (frozen) dataclass and would otherwise
    be unrolled into its raw ``Decimal`` amount rather than the string form a
    listing actually wrote -- ``Decimal`` and ``dict`` do not otherwise appear
    anywhere in a ``Plan``, so there is no separate branch for either: every
    other value is a dataclass, a ``list``/``tuple`` of one, or a plain scalar
    ``json.dumps`` already handles.
    """
    if isinstance(value, Money):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _canonical(getattr(value, f.name))
            for f in fields(value)
            if f.name != "snapshot"
        }
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    return value


def plan_listings(
    ctx: RunContext,
    listings: Sequence[str],
    stages: list[AnyStage],
    *,
    on_event: EngineEventSink = ignore_engine_event,
    should_stop: Callable[[], bool] | None = None,
) -> RunReport:
    """Plan every listing. Reads only -- nothing is created or written.

    ``should_stop`` (A33) is checked once per listing, before that listing's
    plan starts -- the UI's runs resource is what gives one, so a plan run's
    ``DELETE`` (or a server shutdown) stops the batch between listings rather
    than only after the last one. ``None``, every existing caller's default,
    behaves exactly as before.
    """

    def work(listing: str) -> PlannedRun:
        planned = build_plan(ctx, listing, _read_lock(ctx, listing), stages, on_event=on_event)
        on_event(EngineListingPlanned(listing, planned.plan))
        return planned

    return _over(listings, work, on_event, should_stop=should_stop or _never_stop)


def preview_listing(
    ctx: RunContext,
    planned: PlannedRun,
    on_event: EngineEventSink = ignore_engine_event,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Render full-size previews for one already-planned listing (A32,
    decision 6), emitting :class:`EnginePreviewRendered` once per scene
    that ends this call with a ready preview file.

    Deliberately not part of :func:`plan_listings`: a plan stays read-only and
    fast, and a full-size render costs real seconds per scene. The UI's future
    plan run calls this once ``build_plan`` has already resolved -- there is
    nothing to plan here, only to render ahead of an ``apply`` that has not
    happened yet.

    Finds the render stage's own :class:`~etsy_listings.engine.plan.StageState`
    in ``planned.states`` and asks *it* for previews, rather than knowing
    anything about scenes itself -- that type-peek lives in
    :mod:`~etsy_listings.engine.preview`, so this module emits the ready event
    and nothing else. Previewing is render-specific by design (`stage.py`'s
    note on why), not an optional extension every stage might grow.

    Does nothing, quietly, for a listing with no render state at all (a
    ``deleted``/``retired`` listing's plan is retract-only) or whose render
    stage is itself blocked (no garment profile chosen yet) -- there is no
    :class:`~etsy_listings.engine.stages.render.RenderDesired` to preview in
    either case.
    """
    listing = planned.plan.listing
    render_pending(
        ctx,
        planned,
        should_stop=should_stop or _never_stop,
        on_ready=lambda work: on_event(EnginePreviewRendered(listing, work.template, work.colour)),
    )


def apply_listings(
    ctx: RunContext,
    listings: Sequence[str],
    stages: list[AnyStage],
    *,
    on_event: EngineEventSink = ignore_engine_event,
    expect: Mapping[str, str] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunReport:
    """Plan and then execute every listing, writing the lockfile after every
    stage that succeeds, not just once at the end.

    A29: this is what makes a partial apply resumable rather than only a
    complete one. ``execute``'s ``record`` callback is what actually reaches
    disk on the way through -- passing it a stage's own ``write`` is the
    whole of what this function adds; a stage failing after a create (PRD 48)
    is ``execute``'s to record, not this loop's to notice and redo.

    ``expect`` (A31) is the fingerprint a caller saw when it last planned this
    listing, keyed by name. A listing named in ``expect`` is re-planned as it
    always is, and if the fresh plan's fingerprint disagrees, ``execute`` is
    never called for it -- :class:`StalePlanError` is raised instead, caught
    by the same PRD 16 loop every other refusal already goes through. A
    listing this run applies with no entry in ``expect`` (every CLI call
    today) skips the check entirely, which is what keeps `apply` usable
    without ever having planned through this same mapping first.

    ``should_stop`` (A33) is threaded two places: between listings, like
    :func:`plan_listings`, and into ``execute`` itself, so a stage boundary
    inside the *current* listing's apply is also a place this can stop --
    which is the shutdown guarantee decision 7 makes (finish the stage in
    progress, start no other). ``None`` behaves exactly as before.
    """
    stop = should_stop or _never_stop

    def work(listing: str) -> PlannedRun:
        lock = _read_lock(ctx, listing)
        planned = build_plan(ctx, listing, lock, stages, on_event=on_event)
        if expect is not None and listing in expect:
            fingerprint = plan_fingerprint(planned.plan)
            if fingerprint != expect[listing]:
                raise StalePlanError(listing, planned)
        on_event(EngineListingPlanned(listing, planned.plan))
        lock_file = ctx.workspace.lock_file(listing)
        execute(
            ctx,
            planned,
            lock,
            on_event=on_event,
            record=lambda updated: updated.write(lock_file),
            should_stop=stop,
        )
        after_apply(ctx, listing, planned)
        return planned

    return _over(listings, work, on_event, should_stop=stop)


def _over(
    listings: Sequence[str],
    work: Callable[[str], PlannedRun],
    on_event: EngineEventSink,
    *,
    should_stop: Callable[[], bool] = _never_stop,
) -> RunReport:
    """Run ``work`` per listing, continuing past any refusal the user can act on.

    PRD 16. The exception is caught here rather than inside ``work`` so that
    every step of a listing -- loading its lockfile, planning it, executing it
    -- is covered by the same rule, and adding a step later cannot quietly
    escape it.

    ``should_stop`` (A33) is checked before each listing starts -- a listing
    already in progress is `work`'s own business (``execute`` has its own,
    finer-grained check), and this loop only ever decides whether to *start*
    the next one.
    """
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
