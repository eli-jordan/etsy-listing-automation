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
from etsy_listings.core.application.deploy.events import TERMINAL_PHASES, RunScope
from etsy_listings.core.application.deploy.executor import RunExecutor
from etsy_listings.core.application.deploy.registry import (
    BatchApply,
    Conflict,
    Run,
    RunCommand,
    RunRegistry,
    WorkspaceApply,
)
from etsy_listings.core.application.deploy.review import check_reviewed_apply
from etsy_listings.core.application.job_gate import JobGate
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
        gate: JobGate | None = None,
    ) -> None:
        self._registry = RunRegistry()
        self._gate = gate if gate is not None else JobGate()
        self._executor = RunExecutor(
            workspace=workspace,
            context_factory=context_factory,
            registry=self._registry,
            stages=list(stages),
            ai=ai,
            gate=self._gate,
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

        A workspace or batch apply must name exactly the ready plan of its
        scope it was reviewed from, or
        :class:`~etsy_listings.core.application.refusals.ReviewedPlanRefusedError`
        is raised and nothing is queued (ADR-0042, ADR-0059)."""
        if isinstance(command, WorkspaceApply | BatchApply):
            check_reviewed_apply(self._registry.get(command.reviewed_run_id), command)
        return self._registry.create(command)

    def cancel(self, run_id: str) -> bool | None:
        """Cancel a queued or running plan: ``True`` if cancelled or asked
        to stop at its next safe point, ``False`` for an apply (never
        cancellable) or a finished run, ``None`` for no such run."""
        return self._registry.cancel(run_id)

    def get(self, run_id: str) -> Run | None:
        return self._registry.get(run_id)

    def busy(self) -> bool:
        """Whether any run is queued or in progress, on any listing."""
        return any(run.phase not in TERMINAL_PHASES for run in self._registry.all_runs())

    def waiting_for_backup(self, run: Run) -> bool:
        """Whether ``run`` is held by a backup's pause (plan decision P4):
        queued while the gate is paused. Never stored, only read."""
        return self._gate.holds(queued=run.phase == "queued")

    def runs(
        self,
        *,
        listing: str | None = None,
        scope: RunScope | None = None,
        batch: str | None = None,
    ) -> list[Run]:
        """Runs still remembered (ADR-0041's retention).

        ``scope="workspace"``: the current workspace run, which a finished
        plan stays until a later workspace run replaces it. ``scope="batch"``
        with ``batch``: that listing batch's current run, kept the same way;
        without, every retained batch run. ``scope=
        "listings"``: every retained listing-scoped run. Otherwise ``listing``
        narrows to that listing's current run, active or finished and not yet
        superseded; with neither, every run.
        """
        if scope == "workspace":
            return self._registry.for_workspace()
        if scope == "batch":
            return (
                self._registry.for_batch(batch)
                if batch is not None
                else self._registry.for_scope("batch")
            )
        if scope == "listings":
            return self._registry.for_scope("listings")
        if listing is not None:
            return self._registry.for_listing(listing)
        return self._registry.all_runs()
