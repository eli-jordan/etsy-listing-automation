"""Safe phases of explicit preparation, reached only through Preparations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from etsy_listings.core.application.preparation.dependencies import InferenceWorker
from etsy_listings.core.application.preparation.evidence import EvidenceStore
from etsy_listings.core.application.preparation.models import Job, Prediction, placement_key
from etsy_listings.core.preparation.artifacts import (
    PreparationInputs,
    StalePreparation,
    file_checksum,
)
from etsy_listings.core.preparation.numerics import prepare, propose_mask
from etsy_listings.core.preparation.predictions import read_prediction
from etsy_listings.core.render import MaterialMaps
from etsy_listings.core.workspace.atomic import write_bytes_atomic

if TYPE_CHECKING:
    from etsy_listings.core.application.preparation.coordinator import Preparations


class Stopped(Exception):
    def __init__(self, phase: str) -> None:
        self.phase = phase


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
            if path.exists():
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
            current = self.owner.artifacts.saved_inputs(job.template)
            if self.geometry(current) != self.geometry(job.snapshot):
                raise Stopped("superseded")
            job = self.owner.status(identity)
            if job.cancel_intent:
                raise Stopped("cancelled")
            if self.owner._closing:
                raise Stopped("queued")
        job = self.write(identity, step=step)
        self.owner.checkpoint(identity, step)
        return job

    def run(self, identity: str, lane: str) -> None:
        try:
            self.recover_masks(identity)
            if self.finalize_published(identity):
                return
            self.safe(identity, "loading_models" if lane == "gpu" else "fitting")
            job = self.owner.status(identity)
            with Image.open(self.owner.workspace.preparation_work(identity, "photo.png")) as image:
                import hashlib

                pixels = image.convert("RGB")
                if (
                    pixels.size != (job.snapshot.photo.width, job.snapshot.photo.height)
                    or hashlib.sha256(pixels.tobytes()).hexdigest() != job.snapshot.photo.pixels
                ):
                    raise ValueError("Saved photo snapshot is invalid; retry preparation")
            if lane == "gpu":
                self.infer(identity)
                self.write(identity, step="cpu_queued")
            else:
                self.build(identity)
        except Stopped as exc:
            self.write(identity, phase=exc.phase)
        except StalePreparation:
            self.write(identity, phase="superseded")
        except Exception as exc:
            latest = self.owner.status(identity)
            self.write(
                identity,
                phase="cancelled" if latest.cancel_intent else "failed",
                error=str(exc) or type(exc).__name__,
            )

    def finalize_published(self, identity: str) -> bool:
        job = self.owner.status(identity)
        try:
            current = self.owner.artifacts.saved_inputs(job.template)
            if self.geometry(current) != self.geometry(job.snapshot):
                return False
            with self.owner.artifacts.acquire(job.template, job.snapshot) as acquired:
                if acquired.manifest.provenance.get("job_id") != job.id:
                    return False
                self.write(
                    identity,
                    phase="completed",
                    step="publication",
                    placements_completed=len(job.snapshot.placements),
                    result={
                        "generation_id": acquired.manifest.generation_id,
                        "content_digest": acquired.manifest.content_digest,
                    },
                )
                return True
        except (ValueError, OSError):
            return False

    def infer(self, identity: str) -> None:
        job = self.owner.status(identity)
        candidates = self.evidence.candidates(job.template, self.owner.store.jobs())
        if job.action == "prepare_again":
            candidates = job.evidence
        values = list(job.evidence)
        assignments = {}
        for placement in job.snapshot.placements:
            self.safe(identity, "loading_models")
            selected = self.evidence.select(job.snapshot, (*values, *candidates)).get(
                placement_key(placement.id)
            )
            if selected is None:
                planned = self.evidence.new_crop(job.snapshot, placement.quad)
                selected = next(
                    (
                        v
                        for v in (*values, *candidates)
                        if v.rectangle == planned.rectangle
                        and v.identity == planned.identity
                        and v.size == planned.size
                    ),
                    planned,
                )
                if selected not in values:
                    values.append(selected)
                self.write(identity, evidence=tuple(values))
                left, top, right, bottom = selected.rectangle
                with Image.open(
                    self.owner.workspace.preparation_work(identity, "photo.png")
                ) as photo:
                    crop_path = self.owner.workspace.preparation_work(
                        identity, selected.id + ".png"
                    )
                    photo.convert("RGB").crop((left, top, right, bottom)).save(crop_path)
                for role in ("normals", "lighting", "depth"):
                    prediction = next((p for p in selected.predictions if p.role == role), None)
                    if prediction:
                        try:
                            read_prediction(
                                self.evidence.path(prediction.path),
                                role=role,
                                checksum=prediction.checksum,
                                size=selected.size,
                            )
                            continue
                        except (OSError, ValueError):
                            pass
                    self.safe(identity, role)
                    output = self.owner.workspace.preparation_work(
                        identity, selected.id + "-" + role + ".npz"
                    )
                    worker = self.worker(job)
                    request = identity + "-" + selected.id + "-" + role
                    with self.owner.store.condition:
                        latest = self.owner.store.read(identity)
                        if latest.cancel_intent:
                            raise Stopped("cancelled")
                        self.owner._call = (identity, request)
                    try:
                        result = worker.infer(
                            request_id=request,
                            role=role,
                            input=crop_path.relative_to(self.evidence.root).as_posix(),
                            output=output.relative_to(self.evidence.root).as_posix(),
                            size=selected.size,
                            num_inference_steps=job.snapshot.inference.num_inference_steps,
                            ensemble_size=job.snapshot.inference.ensemble_size,
                            dispatch_guard=lambda: self.dispatch(identity),
                        )
                    finally:
                        with self.owner.store.condition:
                            self.owner._call = None
                    checksum = result.get("checksum", "")
                    read_prediction(output, role=role, checksum=checksum, size=selected.size)
                    prediction = Prediction(
                        role=role,
                        path=output.relative_to(self.evidence.root).as_posix(),
                        checksum=checksum,
                    )
                    selected = selected.model_copy(
                        update={
                            "predictions": tuple(p for p in selected.predictions if p.role != role)
                            + (prediction,)
                        }
                    )
                    values = [v for v in values if v.id != selected.id] + [selected]
                    self.write(identity, evidence=tuple(values))
                    self.safe(identity, role + "_saved")
            if selected not in values:
                values.append(selected)
            assignments[placement_key(placement.id)] = selected.id
        retained = self.evidence.retain(
            job.template,
            job.snapshot,
            tuple({v.id: v for v in values if v.id in set(assignments.values())}.values()),
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

    @contextmanager
    def dispatch(self, identity: str) -> Iterator[None]:
        """Serialize Cancel versus the actual protocol send, after warm startup."""
        job = self.owner.status(identity)
        with self.owner.calibration.lock(job.template):
            current = self.owner.artifacts.saved_inputs(job.template)
            with self.owner.store.condition:
                latest = self.owner.store.read(identity)
                if latest.cancel_intent:
                    raise Stopped("cancelled")
                if self.owner._closing:
                    raise Stopped("queued")
                if self.geometry(current) != self.geometry(latest.snapshot):
                    raise Stopped("superseded")
                yield

    def worker(self, job: Job) -> InferenceWorker:
        if not job.engine_version or not job.installation_id:
            raise ValueError("Saved worker selection is missing; retry explicit preparation")
        selection = (job.engine_version, job.installation_id)
        if self.owner._worker_selection != selection:
            if self.owner._worker:
                self.owner._worker.close()
            report = self.owner.runtime.selection(
                job.engine_version, installation_id=job.installation_id
            )
            if not report.available:
                raise ValueError(report.problem or "Run etsy-listings marigold setup first")
            self.owner._worker = self.owner.runtime.worker(report, cache_root=self.evidence.root)
            self.owner._worker_selection = selection
        assert self.owner._worker is not None
        return self.owner._worker

    def recover_masks(self, identity: str) -> None:
        job = self.owner.status(identity)
        if not job.planned_masks:
            return
        with self.owner.calibration.lock(job.template):
            current = self.owner.artifacts.saved_inputs(job.template)
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
                    raise Stopped("superseded")
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
                raise Stopped("superseded")
            self.write(
                identity,
                snapshot=candidate,
                config_revision=self.owner.calibration.read(job.template).revision,
            )

    def build(self, identity: str) -> None:
        from etsy_listings.core.preparation.artifacts import (
            PlacementArtifact,
            descriptors,
            read_maps,
        )

        job = self.owner.status(identity)
        with Image.open(self.owner.workspace.preparation_work(identity, "photo.png")) as photo:
            base = np.array(photo.convert("RGB"), np.uint8)
        maps: dict[str | None, MaterialMaps] = {}
        for placement in job.snapshot.placements:
            self.safe(identity, "mask")
            job = self.owner.status(identity)
            mask_path = self.owner.workspace.preparation_work(
                identity, "mask-" + placement_key(placement.id) + ".png"
            )
            if placement.mask == "0" * 64:
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
                        data,
                        algorithm_version=proposal.algorithm,
                        expected_revision=revision,
                        placement_id=placement.id,
                    )
                    self.owner.checkpoint(identity, "mask_committed")
                    self.recover_masks(identity)
                job = self.owner.status(identity)
            else:
                if not mask_path.exists():
                    raise ValueError("Saved mask snapshot is missing; retry preparation")
                if (
                    file_checksum(mask_path)
                    != next(p for p in job.snapshot.placements if p.id == placement.id).mask
                ):
                    raise ValueError("Saved mask snapshot checksum mismatch")
            with Image.open(mask_path) as image:
                from etsy_listings.core.render import FloatMap

                mask: FloatMap = np.array(image.convert("L"), dtype=np.float32)
                mask /= np.float32(255)
            record = job.cpu_checkpoints.get(placement_key(placement.id))
            archive = self.owner.workspace.preparation_work(
                identity, "maps-" + placement_key(placement.id) + ".npz"
            )
            prepared = None
            if record:
                with suppress(ValueError, OSError):
                    prepared = read_maps(
                        archive,
                        PlacementArtifact.model_validate(record),
                        (job.snapshot.photo.width, job.snapshot.photo.height),
                    )
            if prepared is None:
                value = next(
                    v
                    for v in job.evidence
                    if v.id == job.placement_evidence[placement_key(placement.id)]
                )

                def checkpoint(step: str) -> None:
                    self.safe(identity, step)

                prepared = prepare(
                    base,
                    np.array(placement.quad, np.float32),
                    self.evidence.load(value, job.snapshot),
                    mask=mask,
                    checkpoint=checkpoint,
                ).maps
                from etsy_listings.core.preparation.artifacts import arrays_of

                with archive.open("wb") as stream:
                    np.savez_compressed(stream, **arrays_of(prepared))
                    stream.flush()
                    import os

                    os.fsync(stream.fileno())
                descriptor = PlacementArtifact(
                    id=placement.id,
                    checksum=file_checksum(archive),
                    extent=(0, 0, job.snapshot.photo.width, job.snapshot.photo.height),
                    arrays=descriptors(prepared),
                )
                latest = self.owner.status(identity)
                self.write(
                    identity,
                    cpu_checkpoints={
                        **latest.cpu_checkpoints,
                        placement_key(placement.id): descriptor.model_dump(mode="json"),
                    },
                    placements_completed=len(maps) + 1,
                )
            maps[placement.id] = prepared
        job = self.safe(identity, "publication")
        semantic = {p.id: p.evidence for p in job.snapshot.placements}

        def current_inputs() -> PreparationInputs:
            latest = self.owner.status(identity)
            if latest.cancel_intent:
                raise Stopped("cancelled")
            return self.owner.artifacts.saved_inputs(job.template, evidence=semantic)

        manifest = self.owner.artifacts.publish(
            job.template,
            job.snapshot,
            maps,
            current_inputs=current_inputs,
            provenance={
                "job_id": job.id,
                "engine_version": job.engine_version,
                "installation_id": job.installation_id,
            },
            checkpoint=lambda step: self.owner.checkpoint(identity, step),
        )
        self.write(
            identity,
            phase="completed",
            result={
                "generation_id": manifest.generation_id,
                "content_digest": manifest.content_digest,
            },
            placements_completed=len(maps),
        )
