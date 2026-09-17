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

**One ``RunObserver``, not a signature that grows.** ``on_planned`` and
``on_failure`` used to be separate keywords, and every event worth watching
after A30/A33 would have been a third. They are now two fields of one
dataclass of no-op-by-default callbacks, alongside the plan-time ones
``build_plan``'s walk fires (A33, decision 2) -- see :class:`RunObserver`'s
own docstring for exactly which events belong to this PR and which are a
later one's.

Nothing here formats, and nothing here decides an exit code -- that is
``cli``'s to take from :attr:`RunReport.failed`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

from etsy_listings import __about__
from etsy_listings.config.money import Money
from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, canonical_hash
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

StageCheckingSink = Callable[[str, str], None]
"""Called with a listing's name and a stage's name, the moment ``build_plan``
starts asking that stage anything -- before its ``desired()``, before its
``read_live()``. What lets a plan-time progress strip show which stage is
being checked right now, in the pipeline's own order: A21 left A3's live-fetch
thread pool unbuilt, so that order is genuinely the order stages resolve in,
not a fiction the strip would otherwise have to perform (A33, decision 2)."""

StagePlannedSink = Callable[[str, StagePlan], None]
"""Called with a listing's name and one stage's resolved ``StagePlan`` --
:attr:`~etsy_listings.engine.change.StagePlan.snapshot` included -- the
moment that stage's own walk finishes, whether it ran, changed nothing, drifted
or blocked."""


def _ignore_planned(listing: str, planned: PlannedRun) -> None:
    return None


def _ignore_failure(listing: str, error: UserFacingError) -> None:
    return None


def _ignore_stage_checking(listing: str, stage: str) -> None:
    return None


def _ignore_stage_planned(listing: str, stage_plan: StagePlan) -> None:
    return None


@dataclass(frozen=True)
class RunObserver:
    """No-op-by-default callbacks a caller can watch a run through.

    One parameter that grows beats a signature that gains a keyword per event
    (A33, decision 2): ``plan_listings``/``apply_listings`` used to carry
    ``on_planned`` and ``on_failure`` as separate keywords, and every event
    worth watching since would have been a third.

    **This PR's scope is the plan-time half.** ``build_plan``'s walk calls
    :attr:`on_stage_checking` before each stage and :attr:`on_stage_planned`
    right after, snapshot included; ``plan_listings``/``apply_listings`` call
    :attr:`on_listing_planned` once a listing's plan is whole (the old
    ``on_planned``, renamed to match decision 7's event table) and
    :attr:`on_failure` when a listing is abandoned -- unchanged from the sink
    it already was.

    **The apply-time half is not here yet, on purpose.** Decision 7's event
    table also names ``stage_applying``, ``progress``, ``stage_applied``,
    ``stage_failed`` and ``listing_failed``, and files them under the same
    dataclass -- but that decision (`Runs live in the UI server`) is A33's
    own PR, not this one: those events exist to feed the UI's run resource,
    which does not exist yet, and ``execute``'s A29 ``record`` callback
    already gives ``apply_listings`` everything *it* needs to write a
    lockfile per stage. Adding fields nobody calls yet is exactly the
    growing signature this dataclass exists to avoid, so they join this same
    dataclass -- not a second one -- when that PR needs them.
    """

    on_stage_checking: StageCheckingSink = _ignore_stage_checking
    on_stage_planned: StagePlannedSink = _ignore_stage_planned
    on_listing_planned: PlannedSink = _ignore_planned
    on_failure: FailureSink = _ignore_failure


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
    observer: RunObserver | None = None,
) -> RunReport:
    """Plan every listing. Reads only -- nothing is created or written."""
    watch = observer or RunObserver()

    def work(listing: str) -> PlannedRun:
        planned = build_plan(ctx, listing, _read_lock(ctx, listing), stages, observer=watch)
        watch.on_listing_planned(listing, planned)
        return planned

    return _over(listings, work, watch.on_failure)


def apply_listings(
    ctx: RunContext,
    listings: Sequence[str],
    stages: list[AnyStage],
    *,
    observer: RunObserver | None = None,
    expect: Mapping[str, str] | None = None,
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
    """
    watch = observer or RunObserver()

    def work(listing: str) -> PlannedRun:
        lock = _read_lock(ctx, listing)
        planned = build_plan(ctx, listing, lock, stages, observer=watch)
        if expect is not None and listing in expect:
            fingerprint = plan_fingerprint(planned.plan)
            if fingerprint != expect[listing]:
                raise StalePlanError(listing, planned)
        watch.on_listing_planned(listing, planned)
        lock_file = ctx.workspace.lock_file(listing)
        execute(ctx, planned, lock, record=lambda updated: updated.write(lock_file))
        if _retract_succeeded(planned):
            ctx.workspace.remove_listing(listing)
            return planned
        _omit_consumed_renew(ctx, listing, planned)
        return planned

    return _over(listings, work, watch.on_failure)


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


def _retract_succeeded(planned: PlannedRun) -> bool:
    return any(
        state.stage.name == "retract" and state.stage_plan.will_run for state in planned.states
    )


def _omit_consumed_renew(ctx: RunContext, listing: str, planned: PlannedRun) -> None:
    """``lifecycle: renew`` is a one-shot mark (PRD 62). Apply sends
    ``state=active``, then deletes the key. ``plan`` never writes the yaml."""
    etsy_plan = next(
        (sp for sp in planned.plan.stage_plans if sp.stage == "etsy_listing"),
        None,
    )
    if etsy_plan is None or etsy_plan.blocked is not None:
        return
    path = ctx.workspace.listing_file(listing)
    if not path.is_file():
        return
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("lifecycle") != "renew":
        return
    del raw["lifecycle"]
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


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
