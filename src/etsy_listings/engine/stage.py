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

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from etsy_listings.engine.change import StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile

D = TypeVar("D")
A = TypeVar("A")
L = TypeVar("L")


@dataclass(frozen=True)
class StageApplyResult:
    """What a stage's ``apply`` hands back to fold into the next lockfile.

    Three dicts, each merged into a different part of it by the engine -- never
    by the stage, which returns a value and lets the engine decide what becomes
    of it. That is what keeps a stage testable without a lockfile.

    ``applied`` becomes ``lock.applied[stage.name]`` -- the verbatim
    last-applied document A2 hashes. ``outputs`` merges into the lockfile's
    separate ``outputs`` axis (workspace-relative path -> content hash), which
    is what later decides whether a file needs *re-uploading*, independently
    of whether the stage needed to *re-run* at all.

    ``remote`` merges into ``lock.remote``: ids an API handed back, which the
    stage did not choose and cannot derive (A20). Each stage owns a key prefix
    -- ``printify_*``, ``etsy_*`` -- so one arriving never displaces another's.

    **``remote`` is never hashed**, and that is the point of keeping it out of
    ``applied`` rather than letting a stage tuck ids in there. A product id is
    volatile by definition; hash one and every listing shows a diff for the
    rest of its life. ``canonical_hash`` only sees the ``applied`` subtree, so
    the separation is enforced by the lockfile rather than by convention.
    """

    applied: dict[str, Any]
    outputs: dict[str, str] = field(default_factory=dict)
    remote: dict[str, Any] = field(default_factory=dict)


class Stage(Protocol[D, A, L]):
    name: str
    local: bool  # True => no remote state; differences are work, not drift

    def desired(self, ctx: RunContext, listing: str) -> D: ...

    def last_applied(self, lock: Lockfile) -> A | None: ...

    def read_live(self, ctx: RunContext, listing: str, lock: Lockfile) -> L | None: ...

    def plan(self, desired: D, applied: A | None, live: L | None) -> StagePlan: ...

    def apply(
        self, ctx: RunContext, stage_plan: StagePlan, desired: D, lock: Lockfile
    ) -> StageApplyResult: ...

    """``lock`` is the *previous* one. A stage that writes remote state has to
    read the remote state it wrote last time -- the Printify product id it is
    about to update, the upload ids it can skip re-shipping. Passing it in
    keeps that visible in the signature rather than hidden on the context."""


AnyStage = Stage[Any, Any, Any]
"""A stage with its desired/applied/live types erased, for heterogeneous lists
(the ``STAGES`` pipeline mixes stages with unrelated types by design -- A1)."""
