from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from etsy_listings.core.application.job_gate import JobGate, Ticket
from etsy_listings.core.application.preparation.dependencies import (
    PreparationRuntime,
)
from etsy_listings.core.application.preparation.execution import Execution, StoppedError, WorkerSlot
from etsy_listings.core.application.preparation.models import TERMINAL, Action, Event, Job, Quad
from etsy_listings.core.application.preparation.store import Store
from etsy_listings.core.application.refusals import TemplateInUseError
from etsy_listings.core.errors import ConflictError, UserFacingError
from etsy_listings.core.preparation.artifacts import Artifacts, PreparationInputs
from etsy_listings.core.preparation.evidence_reader import CropEvidence, placement_key
from etsy_listings.core.preparation.position_fits import PositionFits, padded_quads
from etsy_listings.core.preparation.runtime import Capability, Runtime
from etsy_listings.core.render.config import MarigoldRenderer
from etsy_listings.core.render.positions import PositionLimits
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import (
    CalibrationChangedError,
    CalibrationStore,
    json_bytes,
)

logger = logging.getLogger(__name__)

MAX_JOB_PAGE = 1000
"""The most jobs one :meth:`Preparations.list_jobs` page returns."""
MAX_EVENT_WAIT_S = 30
"""The longest :meth:`Preparations.events` holds a request open for new events."""
MAX_REQUEST_ID_LENGTH = 256
_NO_COMPLETE_REPLACEMENT = 0


class PreparationRefusedError(ConflictError, ValueError):
    pass


@dataclass(frozen=True)
class PreparationRequest:
    """One explicit Prepare, Prepare again or Retry, against the calibration
    ``config_revision`` it was asked for. ``request_id`` makes a repeated
    submission idempotent; ``previous_job`` names the job a Retry repeats, and
    ``reset_masks_for_photo`` is Prepare again's choice to start the masks
    over."""

    config_revision: str
    request_id: str
    action: Action = "prepare"
    previous_job: str | None = None
    reset_masks_for_photo: bool = False


class Preparations:
    def __init__(
        self,
        workspace: Workspace,
        *,
        runtime: PreparationRuntime | None = None,
        artifacts: Artifacts | None = None,
        checkpoint: Callable[[str, str], None] = lambda _job, _step: None,
        gate: JobGate | None = None,
    ) -> None:
        self.workspace = workspace
        self.gate = gate if gate is not None else JobGate()
        self.gate.on_resume(self._schedule)
        self.runtime: PreparationRuntime = runtime if runtime is not None else Runtime()
        self.calibration = CalibrationStore(workspace)
        self.artifacts = artifacts if artifacts is not None else Artifacts(workspace)
        self.store = Store(workspace)
        self.gpu = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preparation-gpu")
        self.cpu = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preparation-cpu")
        self.checkpoint = checkpoint
        self._started = False
        self._closing = False
        self._active: set[str] = set()
        self.worker_slot = WorkerSlot()
        self._futures: list[Future[Any]] = []
        self._gpu_busy = False
        self._cpu_busy = False
        self.execution = Execution(self)

    @property
    def closing(self) -> bool:
        return self._closing

    def status(self, identity: str) -> Job:
        with self.store.condition:
            return self.store.read(identity)

    def list_jobs(
        self, *, template: str | None = None, offset: int = 0, limit: int = 100
    ) -> list[Job]:
        if offset < 0 or not 1 <= limit <= MAX_JOB_PAGE:
            raise ValueError("Invalid job pagination")
        return [j for j in self.store.jobs() if template is None or j.template == template][
            offset : offset + limit
        ]

    def events(self, identity: str, *, after: int = 0, wait: float = 0) -> tuple[Event, ...]:
        if after < 0 or not 0 <= wait <= MAX_EVENT_WAIT_S:
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

    def submit(self, template: str, request: PreparationRequest) -> Job:
        _refuse_malformed(request)
        submission = _Submission.of(
            template, request, reset_masks_for_photo=self._mask_reset(request)
        )
        with self.calibration.lock(template), self.store.condition:
            existing = self._admit_locked(submission)
        if existing is not None:
            return existing
        selected = self._inspect_unlocked()
        with self.calibration.lock(template), self.store.condition:
            job, created = self._enqueue_locked(submission, selected)
        if created:
            self._schedule()
        return job

    def _mask_reset(self, request: PreparationRequest) -> bool:
        if request.previous_job is not None:
            return self.status(request.previous_job).reset_masks_for_photo
        return request.reset_masks_for_photo

    def _inspect_unlocked(self) -> Capability:
        """Deep inspection may take 25 seconds. Call it holding no journal or
        template lock, so unrelated status and Cancel stay live."""
        return self.runtime.inspect()

    def _admit_locked(self, submission: _Submission) -> Job | None:
        template, request = submission.template, submission.request
        known = self._receipted(submission)
        if known is not None:
            return known
        calibration = self.calibration.read(template)
        if calibration.revision != request.config_revision:
            raise CalibrationChangedError("Calibration changed before preparation submission")
        if not isinstance(calibration.config.renderer, MarigoldRenderer):
            raise PreparationRefusedError("Select Marigold before preparing this template")
        snapshot = self._snapshot(submission)
        if request.previous_job is not None:
            previous = self.store.read(request.previous_job)
            if previous.template != template or previous.phase not in {
                "failed",
                "cancelled",
                "superseded",
            }:
                raise PreparationRefusedError(
                    "Retry requires a failed or cancelled job for this template"
                )
        return self._join(submission, snapshot)

    def _enqueue_locked(self, submission: _Submission, selected: Capability) -> tuple[Job, bool]:
        template, request = submission.template, submission.request
        known = self._receipted(submission)
        if known is not None:
            return known, False
        calibration = self.calibration.read(template)
        if calibration.revision != request.config_revision:
            raise CalibrationChangedError("Calibration changed during runtime inspection")
        snapshot = self._snapshot(submission)
        joined = self._join(submission, snapshot)
        if joined is not None:
            return joined, False
        _check_capability(selected, snapshot)
        now = time.time()
        job = Job(
            id=uuid4().hex,
            order=max((j.order for j in self.store.jobs()), default=0) + 1,
            template=template,
            request_id=request.request_id,
            request_digest=submission.digest,
            receipts={request.request_id: submission.digest},
            action=request.action,
            kind="prepare",
            reset_masks_for_photo=submission.reset_masks_for_photo,
            config_revision=request.config_revision,
            snapshot=snapshot,
            engine_version=selected.engine_version,
            installation_id=selected.installation_id,
            created=now,
            updated=now,
        )
        self.execution.capture(job)
        return self.store.write(job), True

    def _receipted(self, submission: _Submission) -> Job | None:
        request_id = submission.request.request_id
        for job in self.store.jobs():
            if request_id in job.receipts:
                if job.receipts[request_id] != submission.digest:
                    raise PreparationRefusedError(
                        "Preparation request ID reused with different content"
                    )
                return job
        return None

    def _snapshot(self, submission: _Submission) -> PreparationInputs:
        snapshot = self.artifacts.saved_inputs(
            submission.template, reset_masks_for_photo=submission.reset_masks_for_photo
        )
        self.artifacts.validate_inputs(snapshot)
        return snapshot

    def _join(self, submission: _Submission, snapshot: PreparationInputs) -> Job | None:
        for job in self.store.jobs():
            if (
                job.template == submission.template
                and job.kind != "coverage"
                and job.phase not in TERMINAL
                and job.reset_masks_for_photo == submission.reset_masks_for_photo
                and (
                    submission.request.action != "prepare_again"
                    or (job.kind == "prepare" and job.action == "prepare_again")
                )
                and self.execution.geometry(job.snapshot) == self.execution.geometry(snapshot)
            ):
                return self.store.write(
                    job, receipts={**job.receipts, submission.request.request_id: submission.digest}
                )
        return None

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
            slot = self.worker_slot
            call = slot.call if slot.call and slot.call[0] == identity else None
            worker = slot.worker
        if call and worker:
            with suppress(RuntimeError, OSError):
                worker.cancel(call[1])
        return job

    def _requires_retry(self, template: str, inputs: PreparationInputs, jobs: list[Job]) -> bool:
        latest = next(
            (j for j in reversed(jobs) if j.template == template and j.kind != "coverage"), None
        )
        return (
            latest is not None
            and latest.phase in {"failed", "cancelled"}
            and self.execution.geometry(latest.snapshot) == self.execution.geometry(inputs)
        )

    def reconcile_saved(self, template: str) -> Job | None:
        with self.calibration.lock(template):
            rebuild = self._planned_rebuild_locked(template)
            if rebuild is None:
                return None
            with self.store.condition:
                job, created = self._queue_rebuild_locked(template, rebuild)
        if created:
            self._schedule()
        return job

    def _planned_rebuild_locked(self, template: str) -> _Rebuild | None:
        calibration = self.calibration.read(template)
        if not isinstance(calibration.config.renderer, MarigoldRenderer):
            return None
        inputs = self.artifacts.saved_inputs(template)
        self.artifacts.validate_inputs(inputs)
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
        return _Rebuild(calibration.revision, inputs, selected)

    def _queue_rebuild_locked(self, template: str, rebuild: _Rebuild) -> tuple[Job | None, bool]:
        inputs = rebuild.inputs
        jobs = self.store.jobs()
        if self._requires_retry(template, inputs, jobs):
            return None, False
        active = self._supersede_rebuilds(template, inputs, jobs)
        if active is not None:
            return active, False
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
            config_revision=rebuild.config_revision,
            snapshot=inputs,
            created=now,
            updated=now,
            evidence=tuple({v.id: v for v in rebuild.evidence.values()}.values()),
            placement_evidence={key: value.id for key, value in rebuild.evidence.items()},
        )
        self.execution.capture(job)
        return self.store.write(job), True

    def cover(self, template: str, limits: PositionLimits) -> Job | None:
        with self.calibration.lock(template), self.store.condition:
            planned = self._planned_coverage_locked(template, limits)
            if planned is None or isinstance(planned, Job):
                return planned
        selected = self._inspect_unlocked()
        if not selected.available or not selected.engine_version or not selected.installation_id:
            return None
        with self.calibration.lock(template), self.store.condition:
            planned = self._planned_coverage_locked(template, limits)
            if planned is None or isinstance(planned, Job):
                return planned
            revision, inputs, quads = planned
            now = time.time()
            identity = uuid4().hex
            job = Job(
                id=identity,
                order=max((j.order for j in self.store.jobs()), default=0) + 1,
                template=template,
                request_id="coverage-" + identity,
                request_digest=inputs.identity(),
                action="prepare",
                kind="coverage",
                config_revision=revision,
                snapshot=inputs,
                engine_version=selected.engine_version,
                installation_id=selected.installation_id,
                created=now,
                updated=now,
                coverage=quads,
            )
            self.execution.capture(job)
            job = self.store.write(job)
        self._schedule()
        return job

    def _planned_coverage_locked(
        self, template: str, limits: PositionLimits
    ) -> tuple[str, PreparationInputs, dict[str, Quad]] | Job | None:
        calibration = self.calibration.read(template)
        if not isinstance(calibration.config.renderer, MarigoldRenderer):
            return None
        padded = padded_quads(calibration.config, limits)
        inputs = self.artifacts.saved_inputs(template)
        if padded is None or PositionFits(self.workspace).covers(template, inputs, padded):
            return None
        quads: dict[str, Quad] = {
            placement_key(key): (
                (box[0].x, box[0].y),
                (box[1].x, box[1].y),
                (box[2].x, box[2].y),
                (box[3].x, box[3].y),
            )
            for key, box in padded.items()
        }
        for job in self.store.jobs():
            if (
                job.template == template
                and job.kind == "coverage"
                and job.phase not in TERMINAL
                and job.coverage == quads
                and self.execution.geometry(job.snapshot) == self.execution.geometry(inputs)
            ):
                return job
        return calibration.revision, inputs, quads

    def _finish_interrupted_saves(self) -> None:
        """This server owns the workspace, so what a crash left is its to
        finish (``template_state``). After this a job's reads only observe."""
        for name in self.workspace.template_names(include_uncalibrated=True):
            self.calibration.state(name)

    def recover(self) -> None:
        self._finish_interrupted_saves()
        for job in self.store.jobs():
            if job.phase in TERMINAL:
                continue
            if job.cancel_intent:
                self.execution.write(job.id, phase="cancelled")
                continue
            try:
                self.artifacts.validate_inputs(job.snapshot)
                self.execution.recover_masks(job.id)
                if self.execution.finalize_published(job.id):
                    continue
                self.execution.safe(job.id, "recovery")
                self.execution.write(job.id, phase="queued")
            except Exception as exc:  # noqa: BLE001 -- one job's recovery failure must not stop the rest
                self.execution.write(
                    job.id,
                    phase="superseded" if isinstance(exc, StoppedError) else "failed",
                    error=None if isinstance(exc, StoppedError) else str(exc),
                )
        for name in self.workspace.template_names(include_uncalibrated=True):
            # One damaged template must not stop recovery of the others.
            with suppress(UserFacingError, ValueError, OSError):
                self.reconcile_saved(name)
            self.cleanup(name)

    def start(self) -> None:
        """Blocks on recovery: hosts run it off the event loop."""
        if self._started:
            return
        self.recover()
        self._started = True
        self._schedule()

    def close(self) -> None:
        with self.store.condition:
            self._closing = True
            futures = list(self._futures)
        try:
            for future in futures:
                future.result()
        finally:
            if self.worker_slot.worker:
                self.worker_slot.worker.close()
            self.gpu.shutdown(wait=True)
            self.cpu.shutdown(wait=True)

    def _supersede_rebuilds(
        self, template: str, inputs: PreparationInputs, jobs: list[Job]
    ) -> Job | None:
        for job in jobs:
            if job.template != template or job.phase in TERMINAL or job.kind == "coverage":
                continue
            if self.execution.geometry(job.snapshot) == self.execution.geometry(inputs):
                return job
            if job.kind == "rebuild" and job.id not in self._active:
                self.store.write(job, phase="superseded")
        return None

    def _schedule(self) -> None:
        with self.store.condition:
            if not self._started or self._closing:
                return
            jobs = self.store.jobs()
            for lane in ("cpu", "gpu"):
                if getattr(self, "_" + lane + "_busy"):
                    continue
                job = next((job for job in jobs if self._runnable(job, lane)), None)
                if job is not None:
                    self._dispatch_locked(job, lane)

    def _runnable(self, job: Job, lane: str) -> bool:
        if job.id in self._active or job.phase in TERMINAL:
            return False
        cpu_work = (job.kind == "rebuild" and job.phase == "queued") or job.step == "cpu_queued"
        if lane == "cpu":
            return cpu_work
        return not cpu_work and job.phase == "queued"

    def _dispatch_locked(self, job: Job, lane: str) -> None:
        ticket = self.gate.admit(f"Prepare job for {job.template}")
        if ticket is None:
            return
        try:
            self.store.write(
                job, phase="running", step="loading_models" if lane == "gpu" else "fitting"
            )
            future = getattr(self, lane).submit(self._run, job.id, lane, ticket)
        except BaseException:
            ticket.release()
            raise
        self._active.add(job.id)
        setattr(self, "_" + lane + "_busy", True)
        self._futures = [f for f in self._futures if not f.done()]
        self._futures.append(future)

    def _run(self, identity: str, lane: str, ticket: Ticket) -> None:
        with ticket:
            try:
                self.execution.run(identity, lane)
            finally:
                with self.store.condition:
                    self._active.discard(identity)
                    setattr(self, "_" + lane + "_busy", False)
                self._settle(identity)
        self._schedule()

    def _settle(self, identity: str) -> None:
        job = self.status(identity)
        if job.phase == "superseded" and not self._closing:
            self.reconcile_saved(job.template)
        if job.phase in TERMINAL:
            self.cleanup(job.template)
        if job.kind == "prepare" and job.phase == "completed":
            self._cover_prepared(job.template)

    def waiting_for_backup(self, job: Job) -> bool:
        return self.gate.holds(queued=job.phase == "queued" or job.step == "cpu_queued")

    def _cover_prepared(self, template: str) -> None:
        """Queued while closing too: the job is durable and runs on the next
        start."""
        settings = self.workspace.settings_if_readable(
            skipping=f"covering prepared template {template!r}"
        )
        if settings is None:
            return
        try:
            self.cover(template, settings.template_positions)
        except (UserFacingError, ValueError, OSError) as exc:
            logger.warning("not covering prepared template %r: %s", template, exc)

    def rename_template(self, old: str, new: str, move: Callable[[], None]) -> None:
        with self.calibration.lock(old, new), self.store.condition:
            jobs = [job for job in self.store.jobs() if job.template == old]
            if any(job.phase not in TERMINAL for job in jobs):
                raise TemplateInUseError(f"{old!r} is being prepared; rename it when that finishes")
            move()
            follow = self.execution.evidence.rehome_locked(old, new)
            for job in jobs:
                self.store.write(job, template=new, evidence=tuple(map(follow, job.evidence)))

    def cleanup(self, template: str) -> dict[str, list[str]]:

        with self.calibration.lock(template):
            jobs = self.store.jobs()
            current, replacement_order = self._replacement(template)
            with self.store.condition:
                self._retire_references_locked(template, jobs, replacement_order)
                jobs = self.store.jobs()
            referenced_paths = [
                self.execution.evidence.path(p.path)
                for job in jobs
                for value in job.evidence
                for p in value.predictions
            ]
            removed_sets = self._remove_prediction_sets(template, current, referenced_paths)
            removed_work = self._remove_work(template, jobs, replacement_order, referenced_paths)
            removed_maps: list[str] = []
            # An unreadable pointer names no valid generation: keep them all.
            with suppress(ValueError, OSError):
                removed_maps = self.artifacts.cleanup(template)
        return {"prediction_sets": removed_sets, "work": removed_work, "generations": removed_maps}

    def _retire_references_locked(
        self, template: str, jobs: list[Job], replacement_order: int
    ) -> None:
        for job in jobs:
            if job.template != template or job.id in self._active:
                continue
            if _retired(job, replacement_order) and (job.evidence or job.cpu_checkpoints):
                self.store.write(job, evidence=(), cpu_checkpoints={})

    def _replacement(self, template: str) -> tuple[set[str], int]:
        pointer = self.execution.evidence.pointer(template)
        if pointer is None:
            return set(), _NO_COMPLETE_REPLACEMENT
        try:
            selected = self.execution.evidence.select(pointer.inputs, pointer.evidence)
        except (OSError, ValueError):
            return {pointer.id}, _NO_COMPLETE_REPLACEMENT
        if len(selected) == len(pointer.inputs.placements):
            return {pointer.id}, pointer.job_order
        return {pointer.id}, _NO_COMPLETE_REPLACEMENT

    def _remove_prediction_sets(
        self, template: str, current: set[str], referenced_paths: list[Path]
    ) -> list[str]:
        removed = []
        for identity in self.workspace.preparation_prediction_sets(template):
            directory = self.workspace.preparation_prediction_set(template, identity)
            if (
                identity not in current
                and not self.execution.evidence.publishing(directory)
                and not any(path.is_relative_to(directory) for path in referenced_paths)
            ):
                self.workspace.remove_prediction_set(template, identity)
                removed.append(identity)
        return removed

    def _remove_work(
        self, template: str, jobs: list[Job], replacement_order: int, referenced_paths: list[Path]
    ) -> list[str]:
        removed = []
        for job in jobs:
            directory = self.workspace.preparation_work(job.id)
            if (
                job.template == template
                and job.id not in self._active
                and _retired(job, replacement_order)
                and directory.exists()
                and not any(path.is_relative_to(directory) for path in referenced_paths)
            ):
                self.workspace.remove_preparation_work(job.id)
                removed.append(job.id)
        known_jobs = {job.id for job in jobs}
        for identity in self.workspace.preparation_work_ids():
            if identity not in known_jobs and identity not in self._active:
                self.workspace.remove_preparation_work(identity)
                removed.append(identity)
        return removed


@dataclass(frozen=True)
class _Rebuild:
    config_revision: str
    inputs: PreparationInputs
    evidence: dict[str, CropEvidence]


@dataclass(frozen=True)
class _Submission:
    template: str
    request: PreparationRequest
    reset_masks_for_photo: bool
    digest: str

    @classmethod
    def of(
        cls, template: str, request: PreparationRequest, *, reset_masks_for_photo: bool
    ) -> _Submission:
        digest = hashlib.sha256(
            json_bytes(
                {
                    "template": template,
                    "config_revision": request.config_revision,
                    "action": request.action,
                    "previous_job": request.previous_job,
                    "reset_masks_for_photo": reset_masks_for_photo,
                }
            )
        ).hexdigest()
        return cls(template, request, reset_masks_for_photo, digest)


def _refuse_malformed(request: PreparationRequest) -> None:
    action, request_id = request.action, request.request_id
    if (
        action not in ("prepare", "prepare_again", "retry")
        or not request_id
        or len(request_id) > MAX_REQUEST_ID_LENGTH
    ):
        raise PreparationRefusedError("Invalid preparation action or request ID")
    if (action == "retry") != (request.previous_job is not None):
        raise PreparationRefusedError("Retry requires a previous job")
    if request.reset_masks_for_photo and action != "prepare_again":
        raise PreparationRefusedError("Photo mask reset requires explicit Prepare again")


def _check_capability(selected: Capability, snapshot: PreparationInputs) -> None:
    if not selected.available or not selected.engine_version or not selected.installation_id:
        raise PreparationRefusedError(selected.problem or "Run etsy-listings marigold setup first")
    if (
        snapshot.inference.num_inference_steps > selected.max_num_inference_steps
        or snapshot.inference.ensemble_size > selected.max_ensemble_size
    ):
        raise PreparationRefusedError("Inference settings exceed the installed worker capability")


def _retired(job: Job, replacement_order: int) -> bool:
    return job.phase in {"completed", "superseded"} or (
        job.phase in {"failed", "cancelled"} and job.order < replacement_order
    )
