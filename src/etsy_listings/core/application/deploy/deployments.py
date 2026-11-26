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
        self._executor.start()

    def stop(self) -> None:
        self._executor.stop()

    def submit(self, command: RunCommand) -> Run | Conflict:
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
        return any(run.phase not in TERMINAL_PHASES for run in self._registry.all_runs())

    def waiting_for_backup(self, run: Run) -> bool:
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
