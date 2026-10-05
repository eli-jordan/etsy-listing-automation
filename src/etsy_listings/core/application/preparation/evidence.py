"""Prediction identity, complete-set retention and safe reconstruction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from etsy_listings.core.application.preparation.models import CropEvidence, Job, placement_key
from etsy_listings.core.preparation.artifacts import PreparationInputs
from etsy_listings.core.preparation.numerics import (
    Crop,
    Evidence,
    EvidenceIdentity,
    evidence_covers,
    plan_crop,
)
from etsy_listings.core.preparation.predictions import cache_path, read_prediction
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import json_bytes

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


class EvidenceStore:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.root = workspace.cache("preparation")

    def path(self, relative: str, suffix: str = ".npz") -> Path:
        return cache_path(self.root, relative, suffix=suffix)

    def valid(self, value: CropEvidence) -> bool:
        try:
            for prediction in value.predictions:
                read_prediction(
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
                if self.valid(value) and evidence_covers(
                    crop_of(value, inputs),
                    EvidenceIdentity(**value.identity),
                    np.array(placement.quad, np.float32),
                    (inputs.photo.width, inputs.photo.height),
                    identity,
                ):
                    selected[placement_key(placement.id)] = value
                    break
        return selected

    def current(self, template: str) -> tuple[CropEvidence, ...]:
        try:
            value = json.loads(self.workspace.preparation_prediction_current(template).read_bytes())
            if value["schema_version"] != 1:
                return ()
            self.workspace.preparation_prediction_set(template, value["id"])
            return tuple(CropEvidence.model_validate(v) for v in value["evidence"])
        except (OSError, ValueError, KeyError, TypeError):
            return ()

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
        arrays = {
            p.role: read_prediction(
                self.path(p.path), role=p.role, checksum=p.checksum, size=value.size
            )
            for p in value.predictions
        }
        lighting = arrays["lighting"]
        return Evidence(
            crop_of(value, inputs),
            EvidenceIdentity(**value.identity),
            arrays["normals"][0],
            lighting[0],
            lighting[1],
            lighting[2],
            arrays["depth"][0, :, :, 0],
        )

    def retain(
        self, template: str, inputs: PreparationInputs, values: tuple[CropEvidence, ...]
    ) -> tuple[CropEvidence, ...]:
        if len(self.select(inputs, values)) != len(inputs.placements):
            raise ValueError("Prediction replacement must cover the complete placement set")
        identity = uuid4().hex
        directory = self.workspace.preparation_prediction_set(template, identity)
        directory.mkdir(parents=True)
        retained = []
        for value in values:
            predictions = []
            for prediction in value.predictions:
                path = directory / (value.id + "-" + prediction.role + ".npz")
                write_bytes_atomic(path, self.path(prediction.path).read_bytes(), durable=True)
                predictions.append(
                    prediction.model_copy(update={"path": path.relative_to(self.root).as_posix()})
                )
            retained.append(value.model_copy(update={"predictions": tuple(predictions)}))
        document = {
            "schema_version": 1,
            "id": identity,
            "evidence": [v.model_dump(mode="json") for v in retained],
        }
        for value in retained:
            if not self.valid(value):
                raise ValueError("Invalid retained prediction replacement")
        write_bytes_atomic(directory / "manifest.json", json_bytes(document), durable=True)
        write_bytes_atomic(
            self.workspace.preparation_prediction_current(template),
            json_bytes(document),
            durable=True,
        )
        return tuple(retained)
