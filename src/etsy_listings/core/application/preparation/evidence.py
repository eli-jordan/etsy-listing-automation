"""Prediction publication and retention, owned by job execution."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from etsy_listings.core.application.preparation.evidence_reader import EvidenceReader
from etsy_listings.core.application.preparation.models import CropEvidence
from etsy_listings.core.preparation.artifacts import PreparationInputs
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import CalibrationStore, json_bytes

_PUBLISHERS: set[str] = set()
_PUBLISHER_LOCK = threading.Lock()


class EvidenceStore(EvidenceReader):
    def retain(
        self,
        template: str,
        inputs: PreparationInputs,
        values: tuple[CropEvidence, ...],
        *,
        job_order: int,
        checkpoint: Callable[[str], None] = lambda _: None,
    ) -> tuple[CropEvidence, ...]:
        identity = uuid4().hex
        directory = self.workspace.preparation_prediction_set(template, identity)
        key = str(directory.resolve()).casefold()
        with _PUBLISHER_LOCK:
            _PUBLISHERS.add(key)
        try:
            return self._retain(
                template,
                inputs,
                values,
                job_order=job_order,
                identity=identity,
                checkpoint=checkpoint,
            )
        finally:
            with _PUBLISHER_LOCK:
                _PUBLISHERS.discard(key)

    def publishing(self, directory: Path) -> bool:
        with _PUBLISHER_LOCK:
            return str(directory.resolve()).casefold() in _PUBLISHERS

    def _retain(
        self,
        template: str,
        inputs: PreparationInputs,
        values: tuple[CropEvidence, ...],
        *,
        job_order: int,
        identity: str,
        checkpoint: Callable[[str], None],
    ) -> tuple[CropEvidence, ...]:
        if len(self.select(inputs, values)) != len(inputs.placements):
            raise ValueError("Prediction replacement must cover the complete placement set")
        directory = self.workspace.preparation_prediction_set(template, identity)
        directory.mkdir(parents=True)
        checkpoint("predictions_staging")
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
            "job_order": job_order,
            "inputs": inputs.model_dump(mode="json"),
            "evidence": [v.model_dump(mode="json") for v in retained],
        }
        for value in retained:
            if not self.valid(value):
                raise ValueError("Invalid retained prediction replacement")
        write_bytes_atomic(directory / "manifest.json", json_bytes(document), durable=True)
        checkpoint("predictions_validated")
        with CalibrationStore(self.workspace).lock(template):
            write_bytes_atomic(
                self.workspace.preparation_prediction_current(template),
                json_bytes(document),
                durable=True,
            )
        checkpoint("predictions_pointer")
        return tuple(retained)
