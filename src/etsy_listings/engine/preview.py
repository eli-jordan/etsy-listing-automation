"""Render-stage previews as one surface (A30, A32).

A30: only the stage that produced a type looks inside it. Preview is
render-specific -- not on ``Stage`` -- and then three callers peeked anyway:
``preview_listing`` found the ``RenderStage``, the executor re-opened the
snapshot, and the listings GET rebuilt ``desired`` and rehashed. One module
answers the three questions those callers actually have: does this plan still
need a preview; render them; the current-hash file for a scene.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun
from etsy_listings.engine.stage import Blocked
from etsy_listings.engine.stages.render import (
    RenderApplied,
    RenderSnapshot,
    RenderStage,
    SceneWork,
    _hash_token,
    scene_hash,
)


def _never_stop() -> bool:
    return False


def needs_preview(planned: PlannedRun) -> bool:
    """Whether this listing's plan has a scene worth spending a preview
    render on -- ``RenderStage.snapshot``'s own ``stale``/``missing`` states,
    minus whatever already has one (A32's ``preview`` field)."""
    render_state = next((s for s in planned.states if s.stage.name == RenderStage.name), None)
    if render_state is None or isinstance(render_state.desired, Blocked):
        return False
    snapshot = render_state.stage_plan.snapshot
    if not isinstance(snapshot, RenderSnapshot):
        return False
    return any(
        scene.state in ("stale", "missing") and not scene.preview for scene in snapshot.scenes
    )


def render_pending(
    ctx: RunContext,
    planned: PlannedRun,
    *,
    should_stop: Callable[[], bool] = _never_stop,
) -> tuple[SceneWork, ...]:
    """Render full-size previews for one already-planned listing.

    Finds the render stage's own state and asks *it*, rather than knowing
    anything about scenes -- A30, concentrated here so ``run`` and the
    executor do not each name ``RenderStage``. Empty when there is no render
    state (retract-only) or it is blocked.
    """
    render_state = next((s for s in planned.states if s.stage.name == RenderStage.name), None)
    if render_state is None or isinstance(render_state.desired, Blocked):
        return ()
    if not isinstance(render_state.stage, RenderStage):
        return ()
    return render_state.stage.preview(
        ctx, render_state.desired, render_state.live, should_stop=should_stop
    )


@dataclass(frozen=True)
class PreviewLookup:
    """The current-hash preview file for one scene, or why there isn't one."""

    path: Path | None = None
    miss: Literal["blocked", "no_scene", "missing_file"] | None = None


def lookup_preview(
    ctx: RunContext, listing: str, template: str, colour: str | None
) -> PreviewLookup:
    """The preview a plan run already rendered for this scene, at its
    *current* hash -- never a path built from ``template``/``colour``
    directly. Both arrive from a URL; ``Workspace.preview_file`` is what
    turns them into a real path, and only once this recomputes the same
    :func:`~etsy_listings.engine.stages.render.scene_hash` a plan run would
    right now -- a stale preview from before the last edit must not be
    served as if it still matched.
    """
    lock = Lockfile.read(ctx.workspace.lock_file(listing))
    applied = lock.parse_applied_for("render", RenderApplied) if lock is not None else None
    desired = RenderStage().desired(ctx, listing, applied)
    if isinstance(desired, Blocked):
        return PreviewLookup(miss="blocked")
    work = next((w for w in desired.works if w.template == template and w.colour == colour), None)
    if work is None:
        return PreviewLookup(miss="no_scene")
    path = ctx.workspace.preview_file(
        listing, template, colour, _hash_token(scene_hash(desired, work))
    )
    if not path.is_file():
        return PreviewLookup(path=path, miss="missing_file")
    return PreviewLookup(path=path)
