"""Prediction publication and retention, owned by job execution."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from etsy_listings.core.preparation.artifacts import PreparationInputs
from etsy_listings.core.preparation.evidence_reader import (
    CropEvidence,
    EvidenceReader,
    PredictionPointer,
)
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import CalibrationStore, json_bytes
from etsy_listings.core.workspace.trees import remove_tree

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
        with self._publisher(directory):
            if len(self.select(inputs, values)) != len(inputs.placements):
                raise ValueError("Prediction replacement must cover the complete placement set")
            directory.mkdir(parents=True)
            checkpoint("predictions_staging")
            retained = []
            for value in values:
                predictions = []
                for prediction in value.predictions:
                    path = directory / (value.id + "-" + prediction.role + ".npz")
                    write_bytes_atomic(path, self.path(prediction.path).read_bytes(), durable=True)
                    predictions.append(
                        prediction.model_copy(
                            update={"path": path.relative_to(self.root).as_posix()}
                        )
                    )
                retained.append(value.model_copy(update={"predictions": tuple(predictions)}))
            pointer = PredictionPointer(
                schema_version=1,
                id=identity,
                job_order=job_order,
                inputs=inputs,
                evidence=tuple(retained),
            )
            for value in retained:
                if not self.valid(value):
                    raise ValueError("Invalid retained prediction replacement")
            document = json_bytes(pointer.model_dump(mode="json"))
            write_bytes_atomic(directory / "manifest.json", document, durable=True)
            checkpoint("predictions_validated")
            with CalibrationStore(self.workspace).lock(template):
                write_bytes_atomic(
                    self.workspace.preparation_prediction_current(template), document, durable=True
                )
            checkpoint("predictions_pointer")
            return tuple(retained)

    def rehome(self, old: str, new: str) -> Callable[[CropEvidence], CropEvidence]:
        """Move template ``old``'s retained predictions to ``new``, and answer
        how a job's evidence follows them. A prediction's path spells its
        template, in the pointer, in each set's manifest and in job records.
        The caller holds both templates' locks."""
        source = self.workspace.preparation_predictions_dir(old)
        target = self.workspace.preparation_predictions_dir(new)
        prefix = f"{source.relative_to(self.root).as_posix()}/"
        moved = f"{target.relative_to(self.root).as_posix()}/"

        def follow(value: CropEvidence) -> CropEvidence:
            predictions = tuple(
                p.model_copy(update={"path": moved + p.path.removeprefix(prefix)})
                if p.path.startswith(prefix)
                else p
                for p in value.predictions
            )
            return value.model_copy(update={"predictions": predictions})

        if source.is_dir():
            if target.exists():
                remove_tree(target)
            source.replace(target)
            self._rewrite_pointers(target, follow)
        return follow

    @staticmethod
    def _rewrite_pointers(directory: Path, follow: Callable[[CropEvidence], CropEvidence]) -> None:
        for path in (directory / "current.json", *directory.glob("sets/*/manifest.json")):
            if path.is_file():
                pointer = PredictionPointer.model_validate_json(path.read_bytes())
                evidence = tuple(map(follow, pointer.evidence))
                document = pointer.model_copy(update={"evidence": evidence}).model_dump(mode="json")
                write_bytes_atomic(path, json_bytes(document), durable=True)

    @staticmethod
    @contextmanager
    def _publisher(directory: Path) -> Iterator[None]:
        """Mark ``directory`` as being written, for :meth:`publishing`."""
        key = str(directory.resolve()).casefold()
        with _PUBLISHER_LOCK:
            _PUBLISHERS.add(key)
        try:
            yield
        finally:
            with _PUBLISHER_LOCK:
                _PUBLISHERS.discard(key)

    def publishing(self, directory: Path) -> bool:
        with _PUBLISHER_LOCK:
            return str(directory.resolve()).casefold() in _PUBLISHERS
