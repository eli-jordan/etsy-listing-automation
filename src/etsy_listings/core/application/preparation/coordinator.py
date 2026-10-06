"""Workspace-owned durable preparation queue (ADR-0053).

Async hosts offload synchronous request operations. GPU and CPU work each own a
single executor lane; installation inspection never runs on their event loop.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from contextlib import suppress
from typing import Any
from uuid import uuid4

from etsy_listings.core.application.preparation.dependencies import (
    InferenceWorker,
    PreparationRuntime,
)
from etsy_listings.core.application.preparation.execution import Execution
from etsy_listings.core.application.preparation.models import (
    TERMINAL,
    Action,
    Event,
    Job,
    placement_key,
)
from etsy_listings.core.application.preparation.store import Store
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import Artifacts, PreparationInputs
from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.render.config import MarigoldRenderer
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import (
    CalibrationConflict,
    CalibrationStore,
    json_bytes,
)


class PreparationRefused(ValueError):
    """Actionable refusal without any inference or installation side effect."""


class Preparations:
    def __init__(
        self,
        workspace: Workspace,
        *,
        runtime: PreparationRuntime | None = None,
        artifacts: Artifacts | None = None,
        gpu_executor: Executor | None = None,
        cpu_executor: Executor | None = None,
        checkpoint: Callable[[str, str], None] = lambda _job, _step: None,
    ) -> None:
        self.workspace = workspace
        self.runtime: PreparationRuntime = runtime if runtime is not None else Runtime()
        self.calibration = CalibrationStore(workspace)
        self.artifacts = artifacts if artifacts is not None else Artifacts(workspace)
        self.store = Store(workspace)
        self.gpu = gpu_executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="preparation-gpu"
        )
        self.cpu = cpu_executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="preparation-cpu"
        )
        self.owns_gpu = gpu_executor is None
        self.owns_cpu = cpu_executor is None
        self.checkpoint = checkpoint
        self._started = False
        self._closing = False
        self._active: set[str] = set()
        self._worker: InferenceWorker | None = None
        self._worker_selection: tuple[str | None, str | None] | None = None
        self._call: tuple[str, str] | None = None
        self._futures: list[Future[Any]] = []
        self._gpu_busy = False
        self._cpu_busy = False
        self.execution = Execution(self)

    def status(self, identity: str) -> Job:
        with self.store.condition:
            return self.store.read(identity)

    def list_jobs(
        self, *, template: str | None = None, offset: int = 0, limit: int = 100
    ) -> list[Job]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("Invalid job pagination")
        return [j for j in self.store.jobs() if template is None or j.template == template][
            offset : offset + limit
        ]

    def events(self, identity: str, *, after: int = 0, wait: float = 0) -> tuple[Event, ...]:
        if after < 0 or not 0 <= wait <= 30:
            raise ValueError("Invalid event cursor or wait")
        with self.store.condition:
            job = self.store.read(identity)
            last_sequence = job.events[-1].sequence if job.events else 0
            if after > last_sequence or (
                after and job.events and after < job.events[0].sequence - 1
            ):
                raise ValueError("Event cursor is unavailable; resync from status")
            if wait and after == last_sequence and job.phase not in TERMINAL:
                self.store.condition.wait(wait)
                job = self.store.read(identity)
            return tuple(e for e in job.events if e.sequence > after)

    def submit(
        self,
        template: str,
        *,
        config_revision: str,
        request_id: str,
        action: Action = "prepare",
        previous_job: str | None = None,
    ) -> Job:
        if (
            action not in ("prepare", "prepare_again", "retry")
            or not request_id
            or len(request_id) > 256
        ):
            raise PreparationRefused("Invalid preparation action or request ID")
        if (action == "retry") != (previous_job is not None):
            raise PreparationRefused("Retry requires a previous job")
        digest = hashlib.sha256(
            json_bytes(
                {
                    "template": template,
                    "config_revision": config_revision,
                    "action": action,
                    "previous_job": previous_job,
                }
            )
        ).hexdigest()
        with self.calibration.lock(template), self.store.condition:
            for job in self.store.jobs():
                receipt = job.receipts.get(request_id)
                if receipt:
                    if receipt != digest:
                        raise PreparationRefused(
                            "Preparation request ID reused with different content"
                        )
                    return job
            calibration = self.calibration.read(template)
            if calibration.revision != config_revision:
                raise CalibrationConflict("Calibration changed before preparation submission")
            if not isinstance(calibration.config.renderer, MarigoldRenderer):
                raise PreparationRefused("Select Marigold before preparing this template")
            snapshot = self.artifacts.saved_inputs(template)
            if previous_job is not None:
                previous = self.store.read(previous_job)
                if previous.template != template or previous.phase not in {
                    "failed",
                    "cancelled",
                    "superseded",
                }:
                    raise PreparationRefused(
                        "Retry requires a failed or cancelled job for this template"
                    )
            for job in self.store.jobs():
                if (
                    job.template == template
                    and job.phase not in TERMINAL
                    and (
                        action != "prepare_again"
                        or (job.kind == "prepare" and job.action == "prepare_again")
                    )
                    and self.execution.geometry(job.snapshot) == self.execution.geometry(snapshot)
                ):
                    return self.store.write(job, receipts={**job.receipts, request_id: digest})
        # Deep inspection may take 25 seconds. Never hold a journal or template
        # lock while probing packages/models; unrelated status and Cancel stay live.
        selected = self.runtime.inspect()
        with self.calibration.lock(template), self.store.condition:
            for existing in self.store.jobs():
                if request_id in existing.receipts:
                    if existing.receipts[request_id] != digest:
                        raise PreparationRefused(
                            "Preparation request ID reused with different content"
                        )
                    return existing
            calibration = self.calibration.read(template)
            if calibration.revision != config_revision:
                raise CalibrationConflict("Calibration changed during runtime inspection")
            snapshot = self.artifacts.saved_inputs(template)
            for existing in self.store.jobs():
                if (
                    existing.template == template
                    and existing.phase not in TERMINAL
                    and (
                        action != "prepare_again"
                        or (existing.kind == "prepare" and existing.action == "prepare_again")
                    )
                    and self.execution.geometry(existing.snapshot)
                    == self.execution.geometry(snapshot)
                ):
                    return self.store.write(
                        existing, receipts={**existing.receipts, request_id: digest}
                    )
            if (
                not selected.available
                or not selected.engine_version
                or not selected.installation_id
            ):
                raise PreparationRefused(
                    selected.problem or "Run etsy-listings marigold setup first"
                )
            if (
                snapshot.inference.num_inference_steps > selected.max_num_inference_steps
                or snapshot.inference.ensemble_size > selected.max_ensemble_size
            ):
                raise PreparationRefused(
                    "Inference settings exceed the installed worker capability"
                )
            now = time.time()
            job = Job(
                id=uuid4().hex,
                order=max((j.order for j in self.store.jobs()), default=0) + 1,
                template=template,
                request_id=request_id,
                request_digest=digest,
                receipts={request_id: digest},
                action=action,
                kind="prepare",
                config_revision=config_revision,
                snapshot=snapshot,
                engine_version=selected.engine_version,
                installation_id=selected.installation_id,
                created=now,
                updated=now,
            )
            self.execution.capture(job)
            job = self.store.write(job)
        self._schedule()
        return job

    def cancel(self, identity: str) -> Job:
        with self.store.condition:
            job = self.store.read(identity)
            if job.phase in TERMINAL or job.cancel_intent:
                return job
            job = self.store.write(
                job,
                cancel_intent=True,
                phase="cancelling" if identity in self._active else "cancelled",
            )
            call = self._call if self._call and self._call[0] == identity else None
            worker = self._worker
        if call and worker:
            with suppress(RuntimeError, OSError):
                worker.cancel(call[1])
        return job

    def _requires_retry(self, template: str, inputs: PreparationInputs, jobs: list[Job]) -> bool:
        latest = next((job for job in reversed(jobs) if job.template == template), None)
        return (
            latest is not None
            and latest.phase in {"failed", "cancelled"}
            and self.execution.geometry(latest.snapshot) == self.execution.geometry(inputs)
        )

    def reconcile_saved(self, template: str) -> Job | None:
        """CPU work only. Missing complete evidence never authorizes inference."""
        with self.calibration.lock(template):
            calibration = self.calibration.read(template)
            if not isinstance(calibration.config.renderer, MarigoldRenderer):
                return None
            inputs = self.artifacts.saved_inputs(template)
            if self.artifacts.readiness(template, inputs).can_render:
                return None
            jobs = self.store.jobs()
            if self._requires_retry(template, inputs, jobs):
                return None
            selected = self.execution.evidence.select(
                inputs, self.execution.evidence.candidates(template, jobs)
            )
            if len(selected) != len(inputs.placements):
                return None
            inputs = inputs.model_copy(
                update={
                    "placements": tuple(
                        p.model_copy(
                            update={"evidence": selected[placement_key(p.id)].semantic_digest()}
                        )
                        for p in inputs.placements
                    )
                }
            )
            with self.store.condition:
                jobs = self.store.jobs()
                if self._requires_retry(template, inputs, jobs):
                    return None
                for job in jobs:
                    if job.template == template and job.phase not in TERMINAL:
                        if self.execution.geometry(job.snapshot) == self.execution.geometry(inputs):
                            return job
                        if job.kind == "rebuild" and job.id not in self._active:
                            self.store.write(job, phase="superseded")
                now = time.time()
                identity = uuid4().hex
                job = Job(
                    id=identity,
                    order=max((j.order for j in jobs), default=0) + 1,
                    template=template,
                    request_id="reconcile-" + identity,
                    request_digest=inputs.identity(),
                    action="prepare",
                    kind="rebuild",
                    config_revision=calibration.revision,
                    snapshot=inputs,
                    created=now,
                    updated=now,
                    evidence=tuple({v.id: v for v in selected.values()}.values()),
                    placement_evidence={key: value.id for key, value in selected.items()},
                )
                self.execution.capture(job)
                job = self.store.write(job)
        self._schedule()
        return job

    def recover(self) -> None:
        for job in self.store.jobs():
            if job.phase in TERMINAL:
                continue
            if job.cancel_intent:
                self.execution.write(job.id, phase="cancelled")
                continue
            try:
                self.execution.recover_masks(job.id)
                if self.execution.finalize_published(job.id):
                    continue
                self.execution.safe(job.id, "recovery")
                self.execution.write(job.id, phase="queued")
            except Exception as exc:
                from etsy_listings.core.application.preparation.execution import Stopped

                self.execution.write(
                    job.id,
                    phase="superseded" if isinstance(exc, Stopped) else "failed",
                    error=None if isinstance(exc, Stopped) else str(exc),
                )
        for name in self.workspace.template_names(include_uncalibrated=True):
            # A damaged or changed-photo template remains an actionable reader
            # refusal; it must not stop recovery of unrelated saved templates.
            with suppress(UserFacingError, ValueError, OSError):
                self.reconcile_saved(name)
            self.cleanup(name)

    def start(self) -> None:
        """Recover and reconcile before scheduling. Hosts run this off the event loop."""
        if self._started:
            return
        self.recover()
        self._started = True
        self._schedule()

    def close(self) -> None:
        """Finish active phases and retain resumable records; do not imply Cancel."""
        with self.store.condition:
            self._closing = True
            futures = list(self._futures)
        try:
            for future in futures:
                future.result()
        finally:
            if self._worker:
                self._worker.close()
            if self.owns_gpu:
                self.gpu.shutdown(wait=True)
            if self.owns_cpu:
                self.cpu.shutdown(wait=True)

    def _schedule(self) -> None:
        with self.store.condition:
            if not self._started or self._closing:
                return
            jobs = self.store.jobs()
            for lane in ("cpu", "gpu"):
                if getattr(self, "_" + lane + "_busy"):
                    continue
                for job in jobs:
                    if job.id in self._active or job.phase in TERMINAL:
                        continue
                    eligible = (
                        job.kind == "rebuild" and job.phase == "queued"
                    ) or job.step == "cpu_queued"
                    if (lane == "cpu") != eligible or (lane == "gpu" and job.phase != "queued"):
                        continue
                    self._active.add(job.id)
                    setattr(self, "_" + lane + "_busy", True)
                    self.store.write(
                        job, phase="running", step="loading_models" if lane == "gpu" else "fitting"
                    )
                    self._futures = [f for f in self._futures if not f.done()]
                    self._futures.append(getattr(self, lane).submit(self._run, job.id, lane))
                    break

    def _run(self, identity: str, lane: str) -> None:
        try:
            self.execution.run(identity, lane)
        finally:
            with self.store.condition:
                self._active.discard(identity)
                setattr(self, "_" + lane + "_busy", False)
            job = self.status(identity)
            if job.phase == "superseded" and not self._closing:
                self.reconcile_saved(job.template)
            if job.phase in TERMINAL:
                self.cleanup(job.template)
            self._schedule()

    def cleanup(self, template: str) -> dict[str, list[str]]:
        """Release terminal scratch, retaining cancelled/failed retry evidence."""
        import json

        removed_sets = []
        removed_work = []
        with self.calibration.lock(template):
            jobs = self.store.jobs()
            current = set()
            replacement_order = 0
            try:
                pointer = json.loads(
                    self.workspace.preparation_prediction_current(template).read_bytes()
                )
                self.workspace.preparation_prediction_set(template, pointer["id"])
                current.add(pointer["id"])
                replacement_inputs = PreparationInputs.model_validate(pointer["inputs"])
                values = self.execution.evidence.current(template)
                if len(self.execution.evidence.select(replacement_inputs, values)) == len(
                    replacement_inputs.placements
                ):
                    replacement_order = pointer["job_order"]
            except (OSError, ValueError, TypeError, KeyError):
                pass
            # Completed and superseded jobs cease holding obsolete complete sets.
            # Retire those references in their authoritative records before deletion.
            with self.store.condition:
                for job in jobs:
                    if job.template != template or job.id in self._active:
                        continue
                    retired = job.phase in {"completed", "superseded"} or (
                        job.phase in {"failed", "cancelled"} and job.order < replacement_order
                    )
                    if retired and (job.evidence or job.cpu_checkpoints):
                        self.store.write(job, evidence=(), cpu_checkpoints={})
                jobs = self.store.jobs()
            referenced_paths = [
                self.execution.evidence.path(p.path)
                for job in jobs
                for value in job.evidence
                for p in value.predictions
            ]
            for identity in self.workspace.preparation_prediction_sets(template):
                directory = self.workspace.preparation_prediction_set(template, identity)
                if (
                    identity not in current
                    and not self.execution.evidence.publishing(directory)
                    and not any(path.is_relative_to(directory) for path in referenced_paths)
                ):
                    self.workspace.remove_prediction_set(template, identity)
                    removed_sets.append(identity)
            for job in jobs:
                directory = self.workspace.preparation_work(job.id)
                if (
                    job.template == template
                    and job.id not in self._active
                    and (
                        job.phase in {"completed", "superseded"}
                        or (job.phase in {"failed", "cancelled"} and job.order < replacement_order)
                    )
                    and directory.exists()
                    and not any(path.is_relative_to(directory) for path in referenced_paths)
                ):
                    self.workspace.remove_preparation_work(job.id)
                    removed_work.append(job.id)
            known_jobs = {job.id for job in jobs}
            for identity in self.workspace.preparation_work_ids():
                if identity not in known_jobs and identity not in self._active:
                    self.workspace.remove_preparation_work(identity)
                    removed_work.append(identity)
            generations = {
                j.result["generation_id"]
                for j in jobs
                if j.template == template
                and j.phase not in TERMINAL
                and j.result
                and "generation_id" in j.result
            }
            removed_maps: list[str] = []
            # An unreadable pointer cannot identify the last valid generation.
            # Preserve every generation, but allow explicit preparation to repair it.
            with suppress(ValueError, OSError):
                removed_maps = self.artifacts.cleanup(template, retained_generations=generations)
        return {"prediction_sets": removed_sets, "work": removed_work, "generations": removed_maps}
