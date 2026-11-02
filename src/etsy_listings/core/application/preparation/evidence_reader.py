"""Validated read-only evidence selection and reconstruction."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from etsy_listings.core.application.preparation.models import (
    CropEvidence,
    Job,
    PredictionPointer,
    placement_key,
)
from etsy_listings.core.preparation.artifacts import PreparationInputs
from etsy_listings.core.preparation.numerics import (
    Crop,
    Evidence,
    EvidenceIdentity,
    evidence_covers,
    plan_crop,
)
from etsy_listings.core.preparation.predictions import (
    PredictionError,
    cache_path,
    read_prediction,
    validate_prediction_file,
)
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import json_bytes
from etsy_listings.core.workspace.file_version import file_version

# Checkpoint and preprocessing semantics are immutable for this supported fitter.
# Installation IDs intentionally do not change compatible evidence identity.

CHECKPOINTS = (
    "09cfdd258cb281fa006cf1afcd2284376d16687d/"
    "08c3930bb641abf786ba44ce92547507ebefbc16/"
    "9571e7123e258cf052b4e54241f17971c290e9a8"
)


def required_identity(inputs: PreparationInputs) -> EvidenceIdentity:
    return EvidenceIdentity(
        hashlib.sha256(json_bytes(inputs.photo.model_dump(mode="json"))).hexdigest(),
        CHECKPOINTS,
        hashlib.sha256(json_bytes(inputs.inference.model_dump(mode="json"))).hexdigest(),
        "rgb-original-crop-resolution768-seed2026-v1",
    )


def crop_of(value: CropEvidence, inputs: PreparationInputs) -> Crop:
    left, top, right, bottom = value.rectangle
    crop = Crop(
        value.rectangle,
        (inputs.photo.width, inputs.photo.height),
        (right - left, bottom - top),
        (1, 1, -float(left), -float(top)),
    )
    return crop.resized(value.size)


# A real two-scene edit/rebuild working set is about 262 MiB. Retaining it
# avoids archive decoding during warm edits while keeping ownership bounded.
_EVIDENCE_BUDGET = 384 * 1024 * 1024
_EVIDENCE_LOCK = threading.Lock()
_EVIDENCE: OrderedDict[tuple[Any, ...], tuple[Evidence, int]] = OrderedDict()


class _EvidenceBudget:
    """Bytes retained by ``_EVIDENCE``. A holder, so the cache can update it without ``global``."""

    used = 0


def _retain_evidence(key: tuple[Any, ...], value: Evidence) -> None:
    size = sum(
        a.nbytes for a in (value.normals, value.shading, value.albedo, value.residual, value.depth)
    )
    with _EVIDENCE_LOCK:
        old = _EVIDENCE.pop(key, None)
        if old is not None:
            _EvidenceBudget.used -= old[1]
        if size > _EVIDENCE_BUDGET:
            return
        while _EVIDENCE and _EvidenceBudget.used + size > _EVIDENCE_BUDGET:
            _, (_, removed) = _EVIDENCE.popitem(last=False)
            _EvidenceBudget.used -= removed
        _EVIDENCE[key] = value, size
        _EvidenceBudget.used += size


class EvidenceReader:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.root = workspace.cache("preparation")

    def path(self, relative: str, suffix: str = ".npz") -> Path:
        return cache_path(self.root, relative, suffix=suffix)

    def valid(self, value: CropEvidence) -> bool:
        try:
            for prediction in value.predictions:
                validate_prediction_file(
                    self.path(prediction.path),
                    role=prediction.role,
                    checksum=prediction.checksum,
                    size=value.size,
                )
            return {p.role for p in value.predictions} == {"normals", "lighting", "depth"}
        except (OSError, ValueError):
            return False

    def select(
        self, inputs: PreparationInputs, candidates: tuple[CropEvidence, ...]
    ) -> dict[str, CropEvidence]:
        identity = required_identity(inputs)
        selected = {}
        for placement in inputs.placements:
            for value in candidates:
                if evidence_covers(
                    crop_of(value, inputs),
                    EvidenceIdentity(**value.identity),
                    np.array(placement.quad, np.float32),
                    (inputs.photo.width, inputs.photo.height),
                    identity,
                ) and self.valid(value):
                    selected[placement_key(placement.id)] = value
                    break
        return selected

    def pointer(self, template: str) -> PredictionPointer | None:
        """The template's current prediction set; None when it has none or
        its pointer is unreadable."""
        path = self.workspace.preparation_prediction_current(template)
        try:
            pointer = PredictionPointer.model_validate_json(path.read_bytes())
            # Refuses a set ID that is not one path segment, as ValueError.
            self.workspace.preparation_prediction_set(template, pointer.id)
        except (OSError, ValueError):
            return None
        return pointer

    def current(self, template: str) -> tuple[CropEvidence, ...]:
        pointer = self.pointer(template)
        return () if pointer is None else pointer.evidence

    def candidates(self, template: str, jobs: list[Job]) -> tuple[CropEvidence, ...]:
        return (
            *self.current(template),
            *(v for job in reversed(jobs) if job.template == template for v in job.evidence),
        )

    def new_crop(self, inputs: PreparationInputs, quad: Any) -> CropEvidence:
        crop = plan_crop(np.array(quad, np.float32), (inputs.photo.width, inputs.photo.height))
        return CropEvidence(
            id=uuid4().hex,
            rectangle=crop.rectangle,
            size=crop.prediction_size,
            identity=asdict(required_identity(inputs)),
        )

    def load(self, value: CropEvidence, inputs: PreparationInputs) -> Evidence:
        key = self._evidence_key(value, inputs)
        with _EVIDENCE_LOCK:
            cached = _EVIDENCE.get(key)
            if cached is not None:
                _EVIDENCE.move_to_end(key)
                return cached[0]
        arrays = {
            p.role: read_prediction(
                self.path(p.path), role=p.role, checksum=p.checksum, size=value.size
            )
            for p in value.predictions
        }
        for array in arrays.values():
            array.flags.writeable = False
        lighting = arrays["lighting"]
        result = Evidence(
            crop=crop_of(value, inputs),
            identity=EvidenceIdentity(**value.identity),
            normals=arrays["normals"][0],
            shading=lighting[1],
            albedo=lighting[0],
            residual=lighting[2],
            depth=arrays["depth"][0, :, :, 0],
        )

        if self._evidence_key(value, inputs) != key:
            raise PredictionError("Prediction files changed while loading evidence")
        _retain_evidence(key, result)
        return result

    def _evidence_key(self, value: CropEvidence, inputs: PreparationInputs) -> tuple[Any, ...]:
        files = []
        for prediction in value.predictions:
            path = self.path(prediction.path)
            files.append(
                (prediction.role, prediction.checksum, str(path).casefold(), *file_version(path))
            )
        return value.semantic_digest(), inputs.photo.model_dump_json(), tuple(files)
