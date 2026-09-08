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

from etsy_listings.engine.change import StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, StageApplyResult
from etsy_listings.errors import UserFacingError

D = TypeVar("D")
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


class Stage(Protocol[D, L]):
    name: str
    local: bool  # True => no remote state; differences are work, not drift

    def desired(self, ctx: RunContext, listing: str) -> D: ...

    def read_live(self, ctx: RunContext, listing: str, lock: Lockfile) -> L | None: ...

    def plan(self, desired: D, applied: dict[str, Any] | None, live: L | None) -> StagePlan: ...

    """``applied`` is this stage's own subtree of the lockfile, already looked
    up by ``build_plan`` through ``Lockfile.applied_for(name)`` -- not the
    whole lockfile with an instruction to take one key out of it.

    It arrives as the raw document, because that is what was written: a
    stage that wants a typed view parses one at the top of its ``plan()``,
    where the parse sits next to the comparison it feeds. There used to be a
    ``last_applied(lock)`` method for this, and every stage implemented it as
    ``lock.applied.get(self.name)`` -- the same lookup, written out once per
    stage, on a protocol wide enough to reach every other stage's state."""

    def apply(
        self,
        ctx: RunContext,
        stage_plan: StagePlan,
        desired: D,
        live: L | None,
        lock: Lockfile,
    ) -> StageApplyResult: ...

    """``desired`` and ``live`` are the ones ``build_plan`` already resolved,
    handed back rather than re-derived. That is what makes "the document that
    was hashed is the document that was sent" true by construction, and it is
    why the product stage no longer issues a second ``GET`` for a product it
    read moments ago.

    ``lock`` is the *previous* one, and stays because not all remote state is
    *live* state: the upload ids a stage may skip re-shipping were written by
    the last apply and exist nowhere on the API's side of the seam."""


AnyStage = Stage[Any, Any]
"""A stage with its desired/live types erased, for heterogeneous lists
(the ``STAGES`` pipeline mixes stages with unrelated types by design -- A1)."""
