"""The deployment coordinator: one per application runtime (ADR-0041).

What an adapter needs to deploy -- submit a plan or apply, cancel one, read
runs back -- behind one object whose lifetime the host controls. Constructing
it starts nothing: runs queue until :meth:`Deployments.start` starts the one
worker thread, and :meth:`Deployments.stop` finishes the work in flight and
starts nothing else. The UI server's lifespan makes both calls; a test makes
them directly.

Which runs may be queued (``registry``), how one executes (``executor``) and
whether a workspace apply is the reviewed one (``review``) stay in their
modules. This one decides only the order they are asked in: a reviewed apply
is checked before it is queued, so a refusal leaves nothing behind.
"""

from __future__ import annotations

from collections.abc import Sequence

from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.dependencies import ContextFactory
from etsy_listings.core.application.deploy.events import RunScope
from etsy_listings.core.application.deploy.executor import RunExecutor
from etsy_listings.core.application.deploy.registry import (
    Conflict,
    Run,
    RunCommand,
    RunRegistry,
    WorkspaceApply,
)
from etsy_listings.core.application.deploy.review import check_reviewed_apply
from etsy_listings.core.engine.stage import AnyStage
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.workspace.workspace import Workspace


class Deployments:
    """Plan and apply runs for one workspace, executed one at a time.

    With ``ai``, each run first takes its listings from that coordinator's
    AI work and holds them until it ends (ADR-0050: deploying takes
    precedence over AI); the UI server passes its own. Without, nothing is
    yielded -- there is no AI work to take them from."""

    def __init__(
        self,
        workspace: Workspace,
        context_factory: ContextFactory,
        *,
        ai: AiCoordinator | None = None,
        stages: Sequence[AnyStage] = STAGES,
    ) -> None:
        self._registry = RunRegistry()
        self._executor = RunExecutor(
            workspace=workspace,
            context_factory=context_factory,
            registry=self._registry,
            stages=list(stages),
            ai=ai,
        )

    def start(self) -> None:
        """Start the worker thread; runs already queued execute in order."""
        self._executor.start()

    def stop(self) -> None:
        """Shutdown (ADR-0041): queued runs end without starting -- a plan
        cancelled, an apply failed -- and the call returns once the run in
        flight reaches its next safe point. An apply finishes the stage in
        progress and keeps its lockfile progress (ADR-0037)."""
        self._executor.stop()

    def submit(self, command: RunCommand) -> Run | Conflict:
        """Queue ``command`` as a new run, or answer the active run already
        holding one of its listings (or the workspace), to reattach to.

        A workspace apply must name exactly the ready workspace plan it was
        reviewed from, or :class:`~etsy_listings.core.application.refusals.ReviewedPlanRefused`
        is raised and nothing is queued (ADR-0042)."""
        if isinstance(command, WorkspaceApply):
            check_reviewed_apply(self._registry.get(command.reviewed_run_id), command)
        return self._registry.create(command)

    def cancel(self, run_id: str) -> bool | None:
        """Cancel a queued or running plan: ``True`` if cancelled or asked
        to stop at its next safe point, ``False`` for an apply (never
        cancellable) or a finished run, ``None`` for no such run."""
        return self._registry.cancel(run_id)

    def get(self, run_id: str) -> Run | None:
        return self._registry.get(run_id)

    def runs(self, *, listing: str | None = None, scope: RunScope | None = None) -> list[Run]:
        """Runs still remembered (ADR-0041's retention).

        ``scope="workspace"``: the current workspace run, which a finished
        plan stays until a later workspace run replaces it. ``scope=
        "listings"``: every retained listing-scoped run. Otherwise ``listing``
        narrows to that listing's current run, active or finished and not yet
        superseded; with neither, every run.
        """
        if scope == "workspace":
            return self._registry.for_workspace()
        if scope == "listings":
            return self._registry.for_scope("listings")
        if listing is not None:
            return self._registry.for_listing(listing)
        return self._registry.all_runs()
