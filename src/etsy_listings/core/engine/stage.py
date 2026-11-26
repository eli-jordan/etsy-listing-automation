from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from etsy_listings.core.engine.change import Verdict
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile, StageApplyResult
from etsy_listings.core.errors import UserFacingError

D = TypeVar("D")
A = TypeVar("A", bound=BaseModel)
L = TypeVar("L")

__all__ = ["AnyStage", "Blocked", "Stage", "StageApplyResult", "StageBlockedError"]
"""``StageApplyResult`` is re-exported, not defined here: it lives in ``lock``,
beside :meth:`~etsy_listings.core.engine.lock.Lockfile.fold`, which is the only
thing that reads it. A stage still imports it from here, because returning one
is part of *this* protocol."""


@dataclass(frozen=True)
class Blocked:
    """``message``'s first line is the consequence in the user's terms; any
    further lines are the remedy. ``cli.render`` relies on that shape."""

    message: str


class StageBlockedError(UserFacingError):
    pass


class Stage(Protocol[D, A, L]):
    name: str
    local: bool
    """No remote state: a difference ``read_live`` finds is work to redo, never drift."""

    group: str | None
    """The stage a reader shows this one under: ``etsy_videos`` is
    ``"etsy_media"``'s, one gallery in two stages. The CLI and the UI group by
    it rather than inferring from a name."""

    applied_model: type[A]

    needs_every_earlier_stage: bool = False
    """Blocks the stage, without asking it, while any earlier stage in the walk
    is blocked."""

    chosen_at_apply: bool = False
    """The apply adds this stage by the seller's choice, so the ADR-0039
    fingerprint leaves its plan out and adding or dropping it never stales a
    review."""

    def desired(self, ctx: RunContext, listing: str, applied: A | None) -> D | Blocked:
        """Every refusal decidable from config and the last-applied document;
        one only the live state can prove is ``plan()``'s
        :meth:`~etsy_listings.core.engine.change.Verdict.refused`."""
        ...

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: A | None
    ) -> L | None:
        """``lock`` is passed for ``lock.remote``'s ids, which are not live state."""
        ...

    def plan(self, desired: D, applied: A | None, live: L | None) -> Verdict:
        """Pure: no context, clock or client."""
        ...

    def apply(
        self,
        ctx: RunContext,
        desired: D,
        applied: A | None,
        live: L | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        """The states are the ones ``build_plan`` resolved, so the document
        that was hashed is the document that is sent."""
        ...

    def snapshot(self, desired: D, live: L | None) -> BaseModel | None:
        """Domain facts for the before/after review, never layout and never a
        second copy of what a ``Change`` already decided."""
        del desired, live
        return None

    def rewrites(self, ctx: RunContext, desired: D, live: L | None) -> Mapping[Path, Path | None]:
        """Asked only when the stage will run; see :attr:`RunContext.rewrites`."""
        del ctx, desired, live
        return {}

    def review_hash(self, desired: D) -> str | None:
        """Stable execution inputs not visible in changes or actions (ADR-0039)."""
        del desired
        return None


AnyStage = Stage[Any, Any, Any]
"""A stage with its desired/applied/live types erased, for heterogeneous lists
(the ``STAGES`` pipeline mixes stages with unrelated types by design -- ADR-0007)."""
