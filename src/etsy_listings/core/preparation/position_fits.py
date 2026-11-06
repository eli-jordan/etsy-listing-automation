"""Marigold maps fitted directly to a listing's posed quad (option B).

The spike rejected warping a template's maps to a listing position (spec,
*Spike result*), so a positioned Marigold layer gets its own maps: the fit a
calibrator geometry change runs, from evidence that covers the posed quad
(spec *Rendering → Marigold (option B: a fit per position)*).

A fit is a durable, content-addressed artifact under ``.cache/position-fits/``,
named by the digest of :class:`FitInputs` -- template, placement, posed quad,
mask, evidence identity, photo and inference settings -- so listings holding
the same position share one, and any fit is rebuilt from evidence on demand.
Each load is validated like a published generation (ADR-0054): archive
checksum, array descriptors, shapes and bounds. :meth:`PositionFits.ensure`
holds a per-fit lock while it fits, so a plan or preview arriving while the
scene warmer fits the same position waits for that fit instead of starting a
second, and never falls back to the template's own maps.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from PIL import Image

from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.preparation.artifacts import (
    ArtifactError,
    PhotoIdentity,
    PlacementArtifact,
    PlacementInput,
    PreparationInputs,
    Record,
    StalePreparationError,
    arrays_of,
    descriptors,
    file_checksum,
    numerical_digest,
    read_maps,
)
from etsy_listings.core.preparation.evidence_reader import (
    CropEvidence,
    EvidenceReader,
    placement_key,
)
from etsy_listings.core.preparation.numerics import Placement, prepare
from etsy_listings.core.render.config import (
    AnyTemplate,
    BoundingBox,
    LayerBoxes,
    MarigoldInference,
    MultipleTemplate,
)
from etsy_listings.core.render.material import MaterialMaps
from etsy_listings.core.render.positions import PositionLimits, padded_box
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import CalibrationStore, json_bytes
from etsy_listings.core.workspace.file_version import file_version
from etsy_listings.core.workspace.template_state import template_state

_RECORD = "fit.json"
_ARCHIVE = "maps.npz"
_MAX_RECORD_BYTES = 1024 * 1024


class PositionCoverageError(ArtifactError):
    """The template's evidence does not reach a listing position, so no fit
    can be made until preparation infers evidence covering its padded quad."""

    reason = "missing_maps"


class FitInputs(Record):
    """Everything a position fit's pixels depend on; its digest is the key."""

    template: str
    photo: PhotoIdentity
    placement: PlacementInput
    """The placement at the listing's posed quad, with the template's mask
    and the semantic digest of the evidence it is fitted from."""
    inference: MarigoldInference
    compatibility: Literal["material-v1"] = "material-v1"

    def key(self) -> str:
        return hashlib.sha256(json_bytes(self.model_dump(mode="json"))).hexdigest()


class FitRecord(Record):
    """A fit's ``fit.json``: its inputs and the arrays its archive must hold."""

    schema_version: Literal[1]
    inputs: FitInputs
    artifact: PlacementArtifact


@dataclass(frozen=True)
class FitRequest:
    """One positioned layer's fit, and the retained evidence it is fitted from."""

    inputs: FitInputs
    evidence: CropEvidence

    @property
    def key(self) -> str:
        return self.inputs.key()


@dataclass(frozen=True)
class PositionFit:
    maps: MaterialMaps
    digest: str
    """The fit's numerical content digest (:func:`numerical_digest`)."""


def scene_map_content(content_digest: str, fits: Mapping[str | None, PositionFit]) -> str:
    """A prepared scene's map identity: the template generation's content
    digest alone when no layer is positioned -- so unpositioned scenes and
    their lockfiles are unchanged -- else that and each fit's digest."""
    if not fits:
        return content_digest
    document = {
        "generation": content_digest,
        "fits": {placement_key(key): fit.digest for key, fit in fits.items()},
    }
    return hashlib.sha256(json_bytes(document)).hexdigest()


def template_boxes(config: AnyTemplate) -> dict[str | None, BoundingBox]:
    """Each layer's own box, keyed as :data:`LayerBoxes` keys it."""
    if isinstance(config, MultipleTemplate):
        return {p.id: p.bounding_box for p in config.placements}
    return {None: config.bounding_box}


def positioned_quads(config: AnyTemplate, boxes: LayerBoxes) -> dict[str | None, BoundingBox]:
    """The layers ``boxes`` moves off the template's own box."""
    own = template_boxes(config)
    return {key: box for key, box in boxes.items() if key in own and box != own[key]}


def padded_quads(
    config: AnyTemplate, limits: PositionLimits
) -> dict[str | None, BoundingBox] | None:
    """Each layer's padded quad under ``limits`` (:func:`padded_box`): what
    its evidence must cover for any allowed position to be fitted. ``None``
    when one crosses the homography's horizon and no evidence ever can."""
    try:
        return {key: padded_box(box, limits) for key, box in template_boxes(config).items()}
    except ValueError:
        return None


def _quad(box: BoundingBox) -> tuple[tuple[float, float], ...]:
    return tuple((point.x, point.y) for point in box)


def _with_quads(
    inputs: PreparationInputs, quads: Mapping[str | None, BoundingBox]
) -> PreparationInputs:
    placements = tuple(
        p.model_copy(update={"quad": _quad(quads[p.id])})
        for p in inputs.placements
        if p.id in quads
    )
    return inputs.model_copy(update={"placements": placements})


_GUARD = threading.Lock()
_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_WRITING: set[str] = set()
# Fits a scene is fitting or composing with; prune leaves them alone.
_LEASED: Counter[str] = Counter()
# Validated fits, as the generation reader keeps its maps (ADR-0054).
_FITS: BoundedCache[tuple[Any, ...], PositionFit] = BoundedCache(
    256 * 1024 * 1024,
    size=lambda fit: sum(a.nbytes for a in arrays_of(fit.maps).values()),
)


class PositionFits:
    """The workspace's position fits: request, read or fit, and prune."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.evidence = EvidenceReader(workspace)
        self.calibration = CalibrationStore(workspace)

    def requests(
        self, template: str, inputs: PreparationInputs, quads: Mapping[str | None, BoundingBox]
    ) -> dict[str | None, FitRequest]:
        """A fit request per positioned layer, against the template's current
        evidence. Refuses with :class:`PositionCoverageError` when that
        evidence does not cover a posed quad."""
        if not quads:
            return {}
        posed = _with_quads(inputs, quads)
        selected = self.evidence.select(posed, self.evidence.current(template))
        requests = {}
        for placement in posed.placements:
            evidence = selected.get(placement_key(placement.id))
            if evidence is None:
                raise PositionCoverageError(
                    f"Mockup template '{template}' needs Marigold inference to cover listing "
                    "positions.\nSaving the position queues it in the background; plan "
                    "again once that preparation finishes."
                )
            requests[placement.id] = FitRequest(
                FitInputs(
                    template=template,
                    photo=inputs.photo,
                    placement=placement.model_copy(update={"evidence": evidence.semantic_digest()}),
                    inference=inputs.inference,
                ),
                evidence,
            )
        return requests

    def covers(
        self,
        template: str,
        inputs: PreparationInputs,
        quads: Mapping[str | None, BoundingBox],
        *,
        verify: bool = True,
    ) -> bool:
        """Whether the template's current evidence covers every one of
        ``quads`` (its :func:`padded_quads`; spec, *Evidence coverage*).
        ``verify=False`` takes its files as sound, for a quick answer."""
        posed = _with_quads(inputs, quads)
        selected = self.evidence.select(posed, self.evidence.current(template), verify=verify)
        return len(selected) == len(posed.placements)

    @contextmanager
    def lease(self, keys: Iterable[str]) -> Iterator[None]:
        """Hold the fits named by ``keys`` against :meth:`prune` until exit,
        whether or not they exist yet."""
        held = list(keys)
        with _GUARD:
            _LEASED.update(held)
        try:
            yield
        finally:
            with _GUARD:
                _LEASED.subtract(held)
                for key in held:
                    if _LEASED[key] <= 0:
                        del _LEASED[key]

    def read(self, request: FitRequest) -> PositionFit | None:
        """The stored fit, validated, or ``None`` when it is missing or invalid."""
        key = request.key
        directory = self.workspace.position_fit(key)
        try:
            signature = (
                str(directory).casefold(),
                *file_version(directory / _RECORD),
                *file_version(directory / _ARCHIVE),
            )
        except OSError:
            return None
        cached = _FITS.get(signature)
        if cached is not None:
            return cached
        try:
            fit = self._load(directory, request.inputs)
        except (OSError, ValueError):
            return None
        _FITS.put(signature, fit)
        return fit

    def ensure(self, request: FitRequest) -> PositionFit:
        """The fit, fitting and storing it first when it is missing, or
        waiting for the caller already fitting it."""
        key = request.key
        with _GUARD:
            lock = _LOCKS.setdefault((str(self.workspace.root).casefold(), key), threading.Lock())
        with lock:
            found = self.read(request)
            if found is not None:
                return found
            self._store(request, self._fit(request))
            found = self.read(request)
            if found is None:
                raise ArtifactError("Position fit failed validation; prepare the template again")
            return found

    def _fit(self, request: FitRequest) -> MaterialMaps:
        inputs = request.inputs
        placement = inputs.placement
        with self.calibration.lock(inputs.template):
            config = template_state(self.workspace, inputs.template).require()
            path = self.workspace.template_main_photo(inputs.template, config)
            with Image.open(path) as photo:
                base = np.array(photo.convert("RGB"), np.uint8)
            mask = self.calibration.mask(inputs.template, placement.id)
        if (
            hashlib.sha256(base.tobytes()).hexdigest() != inputs.photo.pixels
            or mask.checksum != placement.mask
        ):
            raise StalePreparationError("Template photo or mask changed; plan the listing again")
        with Image.open(BytesIO(mask.edited)) as image:
            visibility = np.array(image.convert("L"), np.float32) / np.float32(255)
        evidence = self.evidence.load(
            request.evidence,
            PreparationInputs(
                photo=inputs.photo, placements=(placement,), inference=inputs.inference
            ),
        )
        quad = np.array(placement.quad, np.float32)
        return prepare(base, Placement(quad, visibility), evidence).maps

    def _store(self, request: FitRequest, maps: MaterialMaps) -> None:
        """Write the fit to a staging directory and rename it into place."""
        key = request.key
        final = self.workspace.position_fit(key)
        staging = final.with_name(f".{key}-{uuid4().hex}")
        with _GUARD:
            _WRITING.add(staging.name)
        try:
            staging.mkdir(parents=True)
            archive = staging / _ARCHIVE
            with archive.open("wb") as stream:
                canonical: dict[str, Any] = {
                    name: np.ascontiguousarray(array) for name, array in arrays_of(maps).items()
                }
                np.savez(stream, **canonical)
            record = FitRecord(
                schema_version=1,
                inputs=request.inputs,
                artifact=PlacementArtifact(
                    id=request.inputs.placement.id,
                    checksum=file_checksum(archive),
                    extent=maps.extent,
                    arrays=descriptors(maps),
                ),
            )
            write_bytes_atomic(
                staging / _RECORD, json_bytes(record.model_dump(mode="json")), durable=True
            )
            # Only reached when the stored fit did not validate: replace it.
            if final.exists():
                self.workspace.remove_position_fit(key)
            with suppress(FileExistsError, PermissionError):
                staging.rename(final)  # another process stored the same fit first
        finally:
            if staging.exists():
                self.workspace.remove_position_fit(staging.name)
            with _GUARD:
                _WRITING.discard(staging.name)

    @staticmethod
    def _load(directory: Path, expected: FitInputs) -> PositionFit:
        path = directory / _RECORD
        if path.stat().st_size > _MAX_RECORD_BYTES:
            raise ArtifactError("Position fit record exceeds size limit")
        record = FitRecord.model_validate_json(path.read_bytes())
        if record.inputs != expected or record.inputs.key() != directory.name:
            raise ArtifactError("Position fit belongs to other inputs")
        photo = expected.photo
        maps = read_maps(directory / _ARCHIVE, record.artifact, (photo.width, photo.height))
        return PositionFit(maps, numerical_digest({record.artifact.id: maps}))

    def prune(self, keep: Collection[str], *, since: float | None = None) -> list[str]:
        """Remove every stored fit whose key is not in ``keep``, and any
        abandoned staging directory. Fits being written or leased are left
        alone, and so is any entry modified at or after ``since`` -- when
        ``keep`` was computed -- since a position saved meanwhile may need it."""
        removed = []
        for name in self.workspace.position_fits():
            with _GUARD:
                busy = name in _WRITING or name in _LEASED
            if name in keep or busy or self._modified_since(name, since):
                continue
            self.workspace.remove_position_fit(name)
            removed.append(name)
        return removed

    def _modified_since(self, name: str, since: float | None) -> bool:
        if since is None:
            return False
        try:
            return self.workspace.position_fit(name).stat().st_mtime >= since
        except OSError:
            return True


def scan_started() -> float:
    """A ``since`` for :meth:`PositionFits.prune`, taken before its ``keep``."""
    return time.time()
