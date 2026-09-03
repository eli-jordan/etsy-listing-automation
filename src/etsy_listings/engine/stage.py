"""The ``Stage`` protocol. A1: a fixed ordered list of stages sharing one
protocol; ``read_live()`` returning ``None`` marks a stage local-only, and the
engine skips drift reporting for it rather than each stage having to remember.
Dependencies between stages are list order, not a dependency graph."""

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

    ``applied`` becomes ``lock.applied[stage.name]`` -- the verbatim
    last-applied document A2 hashes. ``outputs`` merges into the lockfile's
    separate ``outputs`` axis (workspace-relative path -> content hash), which
    is what later decides whether a file needs *re-uploading*, independently
    of whether the stage needed to *re-run* at all.
    """

    applied: dict[str, Any]
    outputs: dict[str, str] = field(default_factory=dict)


class Stage(Protocol[D, A, L]):
    name: str
    local: bool  # True => read_live() always returns None; drift is undefined

    def desired(self, ctx: RunContext, listing: str) -> D: ...

    def last_applied(self, lock: Lockfile) -> A | None: ...

    def read_live(self, ctx: RunContext, lock: Lockfile) -> L | None: ...

    def plan(self, desired: D, applied: A | None, live: L | None) -> StagePlan: ...

    def apply(self, ctx: RunContext, stage_plan: StagePlan, desired: D) -> StageApplyResult: ...


AnyStage = Stage[Any, Any, Any]
"""A stage with its desired/applied/live types erased, for heterogeneous lists
(the ``STAGES`` pipeline mixes stages with unrelated types by design -- A1)."""
