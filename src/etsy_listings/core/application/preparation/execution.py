"""Safe phases of explicit preparation, reached only through Preparations."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from etsy_listings.core.application.preparation.activity import yield_to_interactive
from etsy_listings.core.application.preparation.dependencies import (
    InferenceWorker,
    PreparationRuntime,
)
from etsy_listings.core.application.preparation.evidence import EvidenceStore
from etsy_listings.core.application.preparation.models import (
    CropEvidence,
    Job,
    Prediction,
    Publication,
    placement_key,
)
from etsy_listings.core.preparation.artifacts import (
    PlacementArtifact,
    PlacementInput,
    PreparationInputs,
    Provenance,
    PublishOptions,
    StalePreparationError,
    arrays_of,
    descriptors,
    file_checksum,
    read_maps,
)
from etsy_listings.core.preparation.numerics import (
    Cooperation,
    Placement,
    prepare,
    propose_mask,
)
from etsy_listings.core.preparation.predictions import read_prediction
from etsy_listings.core.preparation.worker_client import InferenceCall
from etsy_listings.core.render import FloatMap, MaterialMaps
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import AutomaticMask

if TYPE_CHECKING:
    from etsy_listings.core.application.preparation.coordinator import Preparations


_Role = Literal["normals", "lighting", "depth"]
_ROLES: tuple[_Role, ...] = ("normals", "lighting", "depth")


class StoppedError(Exception):
    def __init__(self, phase: str) -> None:
        self.phase = phase


@dataclass
class WorkerSlot:
    """The one warm inference worker, shared by the coordinator and its execution.

    Execution selects the worker and records the request in flight; the
    coordinator cancels that request and closes the worker. ``call`` is read
    and written under the store's condition.
    """

    worker: InferenceWorker | None = None
    selection: tuple[str, str] | None = None
    call: tuple[str, str] | None = None

    def select(
        self,
        runtime: PreparationRuntime,
        engine_version: str,
        installation_id: str,
        *,
        cache_root: Path,
    ) -> InferenceWorker:
        """The worker for this engine and installation, replacing any other."""
        selection = (engine_version, installation_id)
        if self.selection != selection:
            if self.worker:
                self.worker.close()
            report = runtime.selection(engine_version, installation_id=installation_id)
            if not report.available:
                raise ValueError(report.problem or "Run etsy-listings marigold setup first")
            self.worker = runtime.worker(report, cache_root=cache_root)
            self.selection = selection
        assert self.worker is not None
        return self.worker


class Execution:
    def __init__(self, owner: Preparations) -> None:
        self.owner = owner
        self.evidence = EvidenceStore(owner.workspace)

    def write(self, identity: str, **changes: Any) -> Job:
        with self.owner.store.condition:
            return self.owner.store.write(self.owner.store.read(identity), **changes)

    def capture(self, job: Job) -> None:
        workspace = self.owner.workspace
        directory = workspace.preparation_work(job.id)
        directory.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(
            workspace.preparation_work(job.id, "photo.png"),
            workspace.template_main_photo(job.template).read_bytes(),
            durable=True,
        )
        for placement in job.snapshot.placements:
            path = workspace.template_mask_file(job.template, placement.id)
            if placement.mask != "0" * 64 and path.exists():
                write_bytes_atomic(
                    workspace.preparation_work(
                        job.id, "mask-" + placement_key(placement.id) + ".png"
                    ),
                    self.owner.calibration.mask(job.template, placement.id).edited,
                    durable=True,
                )

    @staticmethod
    def geometry(inputs: PreparationInputs) -> str:
        return inputs.model_copy(
            update={
                "placements": tuple(
                    p.model_copy(update={"evidence": "0" * 64}) for p in inputs.placements
                )
            }
        ).identity()

    def safe(self, identity: str, step: str) -> Job:
        job = self.owner.status(identity)
        with self.owner.calibration.lock(job.template):
            current = self.owner.artifacts.saved_inputs(
                job.template, reset_masks_for_photo=job.reset_masks_for_photo
            )
            if self.geometry(current) != self.geometry(job.snapshot):
                raise StoppedError("superseded")
            job = self.owner.status(identity)
            if job.cancel_intent:
                raise StoppedError("cancelled")
            if self.owner.closing:
                raise StoppedError("queued")
        job = self.write(identity, step=step)
        self.owner.checkpoint(identity, step)
        return job

    def run(self, identity: str, lane: str) -> None:
        def invalid_photo() -> None:
            # S01 TRY301: the job runner records this; the raise stays out of its try.
            raise ValueError("Saved photo snapshot is invalid; retry preparation")

        try:
            self.owner.artifacts.validate_inputs(self.owner.status(identity).snapshot)
            self.recover_masks(identity)
            if self.finalize_published(identity):
                return
            self.safe(identity, "loading_models" if lane == "gpu" else "fitting")
            job = self.owner.status(identity)
            with Image.open(self.owner.workspace.preparation_work(identity, "photo.png")) as image:
                pixels = image.convert("RGB")
                if (
                    pixels.size != (job.snapshot.photo.width, job.snapshot.photo.height)
                    or hashlib.sha256(pixels.tobytes()).hexdigest() != job.snapshot.photo.pixels
                ):
                    invalid_photo()
            if lane == "gpu":
                self.infer(identity)
                self.write(identity, step="cpu_queued")
            else:
                self.build(identity)
        except StoppedError as exc:
            self.write(identity, phase=exc.phase)
        except StalePreparationError:
            self.write(identity, phase="superseded")
        except Exception as exc:  # noqa: BLE001 -- a job failure is recorded; it must not kill the worker
            latest = self.owner.status(identity)
            self.write(
                identity,
                phase="cancelled" if latest.cancel_intent else "failed",
                error=str(exc) or type(exc).__name__,
            )

    def finalize_published(self, identity: str) -> bool:
        job = self.owner.status(identity)
        try:
            current = self.owner.artifacts.saved_inputs(
                job.template, reset_masks_for_photo=job.reset_masks_for_photo
            )
            if self.geometry(current) != self.geometry(job.snapshot):
                return False
            with self.owner.artifacts.acquire(job.template, job.snapshot) as acquired:
                if acquired.manifest.provenance.job_id != job.id:
                    return False
                self.write(
                    identity,
                    phase="completed",
                    step="publication",
                    placements_completed=len(job.snapshot.placements),
                    result=Publication(
                        generation_id=acquired.manifest.generation_id,
                        content_digest=acquired.manifest.content_digest,
                    ),
                )
                return True
        except (ValueError, OSError):
            return False

    def infer(self, identity: str) -> None:
        job = self.owner.status(identity)
        candidates = self.evidence.candidates(job.template, self.owner.store.jobs())
        if job.action == "prepare_again":
            candidates = job.evidence
        run = _InferenceRun(job, list(job.evidence), candidates)
        assignments = {}
        for placement in job.snapshot.placements:
            self.safe(identity, "loading_models")
            selected = self.evidence.select(job.snapshot, run.known).get(
                placement_key(placement.id)
            )
            if selected is None:
                selected = self._infer_crop(run, placement)
            run.keep(selected)
            assignments[placement_key(placement.id)] = selected.id
        retained = self.evidence.retain(
            job.template,
            job.snapshot,
            tuple({v.id: v for v in run.values if v.id in set(assignments.values())}.values()),
            job_order=job.order,
            checkpoint=lambda step: self.owner.checkpoint(identity, step),
        )
        inputs = job.snapshot.model_copy(
            update={
                "placements": tuple(
                    p.model_copy(
                        update={
                            "evidence": next(
                                v for v in retained if v.id == assignments[placement_key(p.id)]
                            ).semantic_digest()
                        }
                    )
                    for p in job.snapshot.placements
                )
            }
        )
        self.write(identity, evidence=retained, placement_evidence=assignments, snapshot=inputs)

    def _infer_crop(self, run: _InferenceRun, placement: PlacementInput) -> CropEvidence:
        """Evidence for a placement no existing crop covers: plan its crop (or
        reuse a known one with the same rectangle), then predict each role it
        lacks a valid prediction for."""
        identity = run.job.id
        planned = self.evidence.new_crop(run.job.snapshot, placement.quad)
        selected = next(
            (
                v
                for v in run.known
                if v.rectangle == planned.rectangle
                and v.identity == planned.identity
                and v.size == planned.size
            ),
            planned,
        )
        run.keep(selected)
        self.write(identity, evidence=tuple(run.values))
        crop_path = self.owner.workspace.preparation_work(identity, selected.id + ".png")
        left, top, right, bottom = selected.rectangle
        with Image.open(self.owner.workspace.preparation_work(identity, "photo.png")) as photo:
            photo.convert("RGB").crop((left, top, right, bottom)).save(crop_path)
        for role in _ROLES:
            if not self._has_valid_prediction(selected, role):
                selected = self._predict(run, selected, role, crop_path)
        return selected

    def _has_valid_prediction(self, selected: CropEvidence, role: str) -> bool:
        prediction = next((p for p in selected.predictions if p.role == role), None)
        if not prediction:
            return False
        try:
            read_prediction(
                self.evidence.path(prediction.path),
                role=role,
                checksum=prediction.checksum,
                size=selected.size,
            )
        except (OSError, ValueError):
            return False
        return True

    def _predict(
        self, run: _InferenceRun, selected: CropEvidence, role: _Role, crop_path: Path
    ) -> CropEvidence:
        """Run one model call for ``role`` on the crop; the evidence with its
        validated prediction, recorded on the job."""
        job = run.job
        identity = job.id
        self.safe(identity, role)
        output = self.owner.workspace.preparation_work(identity, selected.id + "-" + role + ".npz")
        worker = self.worker(job)
        request = identity + "-" + selected.id + "-" + role
        self._claim_call(identity, request)
        try:
            result = worker.infer(
                InferenceCall(
                    request_id=request,
                    role=role,
                    input=crop_path.relative_to(self.evidence.root).as_posix(),
                    output=output.relative_to(self.evidence.root).as_posix(),
                    size=selected.size,
                    num_inference_steps=job.snapshot.inference.num_inference_steps,
                    ensemble_size=job.snapshot.inference.ensemble_size,
                ),
                dispatch_guard=lambda: self.dispatch(identity),
            )
        finally:
            with self.owner.store.condition:
                self.owner.worker_slot.call = None
        checksum = result.checksum
        read_prediction(output, role=role, checksum=checksum, size=selected.size)
        prediction = Prediction(
            role=role,
            path=output.relative_to(self.evidence.root).as_posix(),
            checksum=checksum,
        )
        selected = selected.model_copy(
            update={
                "predictions": (
                    *tuple(p for p in selected.predictions if p.role != role),
                    prediction,
                )
            }
        )
        run.replace(selected)
        self.write(identity, evidence=tuple(run.values))
        self.safe(identity, role + "_saved")
        return selected

    def _claim_call(self, identity: str, request: str) -> None:
        """Record ``request`` as the call in flight, so Cancel can reach it;
        refuse once the job is cancelled."""
        with self.owner.store.condition:
            latest = self.owner.store.read(identity)
            if latest.cancel_intent:
                raise StoppedError("cancelled")
            self.owner.worker_slot.call = (identity, request)

    @contextmanager
    def dispatch(self, identity: str) -> Iterator[None]:
        """Serialize Cancel versus the actual protocol send, after warm startup."""
        job = self.owner.status(identity)
        with self.owner.calibration.lock(job.template):
            current = self.owner.artifacts.saved_inputs(
                job.template, reset_masks_for_photo=job.reset_masks_for_photo
            )
            with self.owner.store.condition:
                latest = self.owner.store.read(identity)
                if latest.cancel_intent:
                    raise StoppedError("cancelled")
                if self.owner.closing:
                    raise StoppedError("queued")
                if self.geometry(current) != self.geometry(latest.snapshot):
                    raise StoppedError("superseded")
                yield

    def worker(self, job: Job) -> InferenceWorker:
        if not job.engine_version or not job.installation_id:
            raise ValueError("Saved worker selection is missing; retry explicit preparation")
        return self.owner.worker_slot.select(
            self.owner.runtime,
            job.engine_version,
            job.installation_id,
            cache_root=self.evidence.root,
        )

    def recover_masks(self, identity: str) -> None:
        job = self.owner.status(identity)
        if not job.planned_masks:
            return
        with self.owner.calibration.lock(job.template):
            current = self.owner.artifacts.saved_inputs(
                job.template, reset_masks_for_photo=job.reset_masks_for_photo
            )
            proposed = tuple(
                p.model_copy(update={"mask": job.planned_masks.get(placement_key(p.id), p.mask)})
                for p in job.snapshot.placements
            )
            allowed = job.snapshot.model_copy(update={"placements": proposed})
            # A save may have committed some planned masks before the job record.
            # Accept only those exact bytes, and only with unchanged photo/geometry.
            reconciled = []
            for placement in current.placements:
                original = next((p for p in job.snapshot.placements if p.id == placement.id), None)
                if original is None or placement.mask not in {
                    original.mask,
                    job.planned_masks.get(placement_key(placement.id)),
                }:
                    raise StoppedError("superseded")
                reconciled.append(placement.model_copy(update={"evidence": original.evidence}))
            candidate = current.model_copy(update={"placements": tuple(reconciled)})
            stripped_current = candidate.model_copy(
                update={
                    "placements": tuple(
                        p.model_copy(update={"mask": "0" * 64}) for p in candidate.placements
                    )
                }
            )
            stripped_allowed = allowed.model_copy(
                update={
                    "placements": tuple(
                        p.model_copy(update={"mask": "0" * 64}) for p in allowed.placements
                    )
                }
            )
            if stripped_current.identity() != stripped_allowed.identity():
                raise StoppedError("superseded")
            self.write(
                identity,
                snapshot=candidate,
                config_revision=self.owner.calibration.read(job.template).revision,
            )

    def build(self, identity: str) -> None:

        job = self.owner.status(identity)
        with Image.open(self.owner.workspace.preparation_work(identity, "photo.png")) as photo:
            base = np.array(photo.convert("RGB"), np.uint8)
        reuse: AbstractContextManager[Mapping[str | None, MaterialMaps]] = (
            self.owner.artifacts.reusable(job.template, job.snapshot)
            if job.kind == "rebuild"
            else nullcontext({})
        )
        with reuse as reusable:
            maps: dict[str | None, MaterialMaps] = {}
            for placement in job.snapshot.placements:
                self.safe(identity, "mask")
                job = self.owner.status(identity)
                reused = reusable.get(placement.id)
                if reused is not None:
                    maps[placement.id] = reused
                    continue
                job, mask = self._placement_mask(job, placement, base)
                prepared = self._checkpointed_maps(job, placement)
                if prepared is None:
                    prepared = self._fit_maps(job, placement, base, mask)
                    self._record_checkpoint(identity, placement, prepared, completed=len(maps) + 1)
                maps[placement.id] = prepared
            self._publish(identity, maps)

    def _placement_mask(
        self, job: Job, placement: PlacementInput, base: NDArray[np.uint8]
    ) -> tuple[Job, FloatMap]:
        """The placement's visibility mask, proposing and committing an
        automatic one when it has none; with the job as it now stands."""
        mask_path = self.owner.workspace.preparation_work(
            job.id, "mask-" + placement_key(placement.id) + ".png"
        )
        if placement.mask == "0" * 64:
            job = self._propose_mask(job, placement, base, mask_path)
        else:
            if not mask_path.exists():
                raise ValueError("Saved mask snapshot is missing; retry preparation")
            if (
                file_checksum(mask_path)
                != next(p for p in job.snapshot.placements if p.id == placement.id).mask
            ):
                raise ValueError("Saved mask snapshot checksum mismatch")
        with Image.open(mask_path) as image:
            mask: FloatMap = np.array(image.convert("L"), dtype=np.float32)
            mask /= np.float32(255)
        return job, mask

    def _propose_mask(
        self, job: Job, placement: PlacementInput, base: NDArray[np.uint8], mask_path: Path
    ) -> Job:
        """Propose an automatic mask, plan it on the job, then install it
        under the template lock."""
        identity = job.id
        proposal = propose_mask(base, np.array(placement.quad, np.float32))
        data = self.owner.calibration.encode_mask(
            Image.fromarray(np.rint(proposal.mask * 255).astype(np.uint8))
        )
        write_bytes_atomic(mask_path, data, durable=True)
        planned = {
            **job.planned_masks,
            placement_key(placement.id): file_checksum(mask_path),
        }
        self.write(identity, planned_masks=planned)
        with self.owner.calibration.lock(job.template):
            self.safe(identity, "mask_publication")
            revision = self.owner.calibration.read(job.template).revision
            self.owner.calibration.install_automatic(
                job.template,
                AutomaticMask(
                    data,
                    algorithm_version=proposal.algorithm,
                    placement_id=placement.id,
                ),
                expected_revision=revision,
                reset_for_photo=job.reset_masks_for_photo,
            )
            self.owner.checkpoint(identity, "mask_committed")
            self.recover_masks(identity)
        return self.owner.status(identity)

    def _maps_archive(self, identity: str, placement: PlacementInput) -> Path:
        return self.owner.workspace.preparation_work(
            identity, "maps-" + placement_key(placement.id) + ".npz"
        )

    def _checkpointed_maps(self, job: Job, placement: PlacementInput) -> MaterialMaps | None:
        """Maps an earlier attempt already fitted and checkpointed, if valid."""
        record = job.cpu_checkpoints.get(placement_key(placement.id))
        if record is None:
            return None
        with suppress(ValueError, OSError):
            return read_maps(
                self._maps_archive(job.id, placement),
                record,
                (job.snapshot.photo.width, job.snapshot.photo.height),
            )
        return None

    def _fit_maps(
        self, job: Job, placement: PlacementInput, base: NDArray[np.uint8], mask: FloatMap
    ) -> MaterialMaps:
        """Fit the placement from its accepted evidence and write the
        read-only maps to the job's checkpoint archive."""
        identity = job.id
        value = next(
            v for v in job.evidence if v.id == job.placement_evidence[placement_key(placement.id)]
        )
        cooperate = partial(self._cooperate, identity)
        prepared = prepare(
            base,
            Placement(np.array(placement.quad, np.float32), mask),
            self.evidence.load(value, job.snapshot),
            cooperation=Cooperation(partial(self._checkpoint, identity), cooperate),
        ).maps

        for array in arrays_of(prepared).values():
            array.flags.writeable = False
        with self._maps_archive(identity, placement).open("wb") as stream:
            np.savez(stream, **arrays_of(prepared))
            stream.flush()

            os.fsync(stream.fileno())
        return prepared

    def _check_cancelled(self, identity: str) -> None:
        if self.owner.status(identity).cancel_intent:
            raise StoppedError("cancelled")
        if self.owner.closing:
            raise StoppedError("queued")

    def _cooperate(self, identity: str) -> None:
        yield_to_interactive(self.owner.workspace, partial(self._check_cancelled, identity))

    def _checkpoint(self, identity: str, step: str) -> None:
        self._cooperate(identity)
        self.safe(identity, step)

    def _record_checkpoint(
        self, identity: str, placement: PlacementInput, prepared: MaterialMaps, *, completed: int
    ) -> None:
        descriptor = PlacementArtifact(
            id=placement.id,
            checksum=file_checksum(self._maps_archive(identity, placement)),
            extent=prepared.extent,
            arrays=descriptors(prepared),
        )
        latest = self.owner.status(identity)
        self.write(
            identity,
            cpu_checkpoints={
                **latest.cpu_checkpoints,
                placement_key(placement.id): descriptor,
            },
            placements_completed=completed,
        )

    def _publish(self, identity: str, maps: dict[str | None, MaterialMaps]) -> None:
        job = self.safe(identity, "publication")
        semantic = {p.id: p.evidence for p in job.snapshot.placements}

        def current_inputs() -> PreparationInputs:
            latest = self.owner.status(identity)
            if latest.cancel_intent:
                raise StoppedError("cancelled")
            return self.owner.artifacts.saved_inputs(
                job.template, evidence=semantic, reset_masks_for_photo=job.reset_masks_for_photo
            )

        manifest = self.owner.artifacts.publish(
            job.template,
            job.snapshot,
            maps,
            current_inputs=current_inputs,
            options=PublishOptions(
                provenance=Provenance(
                    job_id=job.id,
                    engine_version=job.engine_version,
                    installation_id=job.installation_id,
                ),
                checkpoint=lambda step: self.owner.checkpoint(identity, step),
                copy_maps=False,
            ),
        )
        self.write(
            identity,
            phase="completed",
            result=Publication(
                generation_id=manifest.generation_id, content_digest=manifest.content_digest
            ),
            placements_completed=len(maps),
        )


@dataclass
class _InferenceRun:
    """One job's inference pass: the evidence it has gathered so far, in
    order, and the earlier evidence it may reuse."""

    job: Job
    values: list[CropEvidence]
    candidates: tuple[CropEvidence, ...]

    @property
    def known(self) -> tuple[CropEvidence, ...]:
        return (*self.values, *self.candidates)

    def keep(self, value: CropEvidence) -> None:
        if value not in self.values:
            self.values.append(value)

    def replace(self, value: CropEvidence) -> None:
        """Put ``value`` last, in place of any earlier version of it."""
        self.values = [v for v in self.values if v.id != value.id] + [value]
