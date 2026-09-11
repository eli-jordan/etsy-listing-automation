"""The ``Stage`` protocol. A1: a fixed ordered list of stages sharing one
protocol; ``local`` marks a stage as having no *remote* state, so the engine
skips drift reporting for it rather than each stage having to remember.
Dependencies between stages are list order, not a dependency graph.

``local`` does not mean "reads nothing". A local stage still has state that
exists outside its lockfile entry -- the render stage's PNGs are on disk, and
they can be deleted or edited between runs. ``read_live()`` is where a stage
observes that, local or not; what ``local`` decides is that any difference is
work to redo, not *drift* to warn about (there is no second writer to have
drifted from), and that the read is cheap and local, so it never joins A3's
live-fetch thread pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from etsy_listings.engine.change import Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, StageApplyResult
from etsy_listings.errors import UserFacingError

D = TypeVar("D")
A = TypeVar("A", bound=BaseModel)
L = TypeVar("L")

__all__ = ["AnyStage", "Blocked", "Stage", "StageApplyResult", "StageBlockedError"]
"""``StageApplyResult`` is re-exported, not defined here: it lives in ``lock``,
beside :meth:`~etsy_listings.engine.lock.Lockfile.fold`, which is the only
thing that reads it. A stage still imports it from here, because returning one
is part of *this* protocol."""


@dataclass(frozen=True)
class Blocked:
    """A stage cannot run, and why -- as a *value*, never an exception.

    A stage that refuses is something ``plan`` has to **report**, not something
    that should end the walk. Raising ends it: the exception unwinds
    ``build_plan`` from wherever it was in :data:`STAGES`, so a design a
    hundred pixels too short cost the user the render stage's plan as well,
    and printed one line where a whole listing's worth of intent belonged.

    Returned instead, it becomes :attr:`StagePlan.blocked` like any other
    reason a stage will not run -- one vocabulary rather than two, and the UI's
    serialiser gets it for free because it is already part of the plan.

    ``message``'s first line is the consequence in the user's terms; any
    further lines are the remedy. ``cli.render`` relies on that shape.
    """

    message: str


class StageBlockedError(UserFacingError):
    """A blocked stage reached ``apply``.

    ``execute`` only runs stages the plan flagged, and a blocked stage is
    never flagged -- so this is a wiring defect, not a configuration problem.
    It exists so ``apply`` fails loudly rather than shipping a half-built
    payload if that invariant is ever broken.
    """


class Stage(Protocol[D, A, L]):
    """Three states and three questions, and nothing about bookkeeping.

    What a stage author must supply is deliberately smaller than it was. The
    engine now owns: looking up this stage's lockfile subtree, decoding it
    (:meth:`~etsy_listings.engine.lock.Lockfile.parse_applied_for`), naming
    the stage in the plan it produced, and turning a refusal into a blocked
    plan. Each of those was written out once per stage, and each had already
    been written two different ways with only two stages in the pipeline.
    """

    name: str
    local: bool  # True => no remote state; differences are work, not drift

    applied_model: type[A]
    """The type this stage's lockfile subtree decodes into.

    Declared rather than parsed: ``build_plan`` hands ``plan()`` a typed
    document, so no stage writes a ``parse()`` of its own and no stage can
    write one that raises where the others return ``None``. A model, always --
    a document read back as a dict is a document whose key names get spelled
    again in every function that touches it.
    """

    def desired(self, ctx: RunContext, listing: str, applied: A | None) -> D | Blocked: ...

    """What this listing wants from this stage, or why it cannot have it.

    **Where a pre-flight refusal is spoken** -- everything decidable from
    config and the last-applied document, which is nearly all of them. It is
    the earliest point one can be raised, and raising it here is what stops a
    fully resolved document being built for a run that was never going to
    happen. The exception is a refusal only the live state can prove, which
    belongs to ``plan()`` as :meth:`~etsy_listings.engine.change.Verdict.refused`
    because the fact it turns on does not exist yet.

    ``applied`` is passed because some refusals are about what was applied
    last time -- changing the garment under an existing product is the one
    that exists today (PRD 37)."""

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: A | None
    ) -> L | None: ...

    """The state outside the lockfile: a remote object, or files on disk.

    Called for ``local`` stages too -- ``local`` means "no *remote* state", so
    no drift reporting and no fan-out, never "reads nothing" (A1). ``applied``
    arrives already decoded, so a stage no longer re-looks-up and re-parses
    its own subtree here having just been handed it. ``lock`` stays for the
    rest of the file: the ids under ``lock.remote`` are not live state and
    exist nowhere on the API's side of the seam."""

    def plan(self, desired: D, applied: A | None, live: L | None) -> Verdict: ...

    """Compare the three states. A2: every stage writes its own.

    It returns a :class:`~etsy_listings.engine.change.Verdict` rather than a
    ``StagePlan`` because the one thing a ``StagePlan`` has and a verdict does
    not -- the stage's own name -- is the engine's to supply, and a name a
    stage stamps for itself is a name it can stamp wrongly.

    A verdict may also *refuse*
    (:meth:`~etsy_listings.engine.change.Verdict.refused`), for the refusals
    that only ``live`` could have proved. It is the same refusal ``desired()``
    speaks and lands in the same place; what a verdict must never do is
    decline to run while reporting a mere ``reason``, which renders as
    nothing at all.

    This signature is pure by construction: no context, no clock, no client,
    so a stage's comparison is unit-testable without any of them."""

    def apply(
        self,
        ctx: RunContext,
        desired: D,
        applied: A | None,
        live: L | None,
        lock: Lockfile,
    ) -> StageApplyResult: ...

    """``desired``, ``applied`` and ``live`` are the ones ``build_plan``
    already resolved, handed back rather than re-derived. That is what makes
    "the document that was hashed is the document that was sent" true by
    construction, and it is why the product stage no longer issues a second
    ``GET`` for a product it read moments ago.

    ``applied`` is here for the same reason it is passed to the other three
    questions: decoding a stage's own subtree is the engine's job, and a
    stage that cannot get the document handed to it goes and decodes one --
    ``etsy_media`` did, which put a second implementation of that rule in a
    file that had just been given the first. This parameter replaces the
    ``stage_plan`` that used to sit here, which no stage read: three deleted
    it outright and the protocol had already drifted, one stage typing it
    ``object`` while the rest said ``StagePlan``. A plan is the engine's
    account of what a stage said; handing it back to that stage tells it
    nothing it did not say.

    ``desired`` is a ``D``, never a ``Blocked``: a blocked stage is never
    flagged to run, so the branch every stage used to open here is gone.

    ``lock`` is the *previous* one, and stays because not all remote state is
    *live* state: the upload ids a stage may skip re-shipping were written by
    the last apply and exist nowhere on the API's side of the seam."""


AnyStage = Stage[Any, Any, Any]
"""A stage with its desired/applied/live types erased, for heterogeneous lists
(the ``STAGES`` pipeline mixes stages with unrelated types by design -- A1)."""
