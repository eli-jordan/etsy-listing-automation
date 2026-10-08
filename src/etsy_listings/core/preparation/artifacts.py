"""Validated immutable map generations, independent of inference installation.

ADR-0053: manifests describe numerical semantics. ZIP timestamps, generation
names, paths and diagnostic provenance do not enter the content digest.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from etsy_listings.core.render.config import (
    MarigoldInference,
    MarigoldRenderer,
    MultipleTemplate,
    PlacementId,
)
from etsy_listings.core.render.material import MaterialMaps
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import CalibrationStore, MaskPhotoMismatch, json_bytes

SCHEMA = 1
MAX_PIXELS = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
SEMANTICS = {
    "array_axes": "row,column,channel",
    "material_axes": "u-right,v-down",
    "photo_centres": "integer",
    "artwork_centres": "u*(width-1),v*(height-1)",
    "outside_material": "constant-zero-border",
    "outside_quad": "zero-visibility",
    "sampling": "linear-premultiplied-mip-v1",
}
BOUNDS = {
    "material": (-4.0, 4.0, 2),
    "visibility": (0.0, 1.0, 0),
    "estimated": (0.04, 1.7, 3),
    "photographic": (0.04, 1.7, 3),
    "texture": (0.9, 1.1, 0),
    "residual": (0.0, 0.035, 3),
    "patch_ids": (0.0, 100.0, 0),
}


class ArtifactError(ValueError):
    """Prepare the template again instead of interpreting an invalid map."""


class StalePreparation(ArtifactError):
    """Current geometry, masks or evidence changed before publication."""


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PhotoIdentity(Record):
    file: str = Field(min_length=1, max_length=255)
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    conversion: Literal["pillow-rgb-v1"]
    pixels: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def bounded(self) -> PhotoIdentity:
        if self.file in (".", "..") or any(v in self.file for v in ("/", chr(92), ":")):
            raise ValueError("Main photo must be a template-relative filename")
        if self.width * self.height > MAX_PIXELS:
            raise ValueError("Photo exceeds prepared-map pixel limit")
        return self


class PlacementInput(Record):
    id: PlacementId | None
    quad: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]
    mask: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def finite(self) -> PlacementInput:
        if not all(math.isfinite(v) for point in self.quad for v in point):
            raise ValueError("Placement coordinates must be finite")
        return self


class PreparationInputs(Record):
    photo: PhotoIdentity
    placements: tuple[PlacementInput, ...] = Field(min_length=1, max_length=32)
    inference: MarigoldInference
    compatibility: Literal["material-v1"] = "material-v1"

    @model_validator(mode="after")
    def exact_ids(self) -> PreparationInputs:
        ids = self.ids
        if len(set(ids)) != len(ids) or (None in ids and len(ids) != 1):
            raise ValueError("Use one null implicit placement or unique explicit IDs")
        return self

    @property
    def ids(self) -> tuple[str | None, ...]:
        return tuple(p.id for p in self.placements)

    def identity(self) -> str:
        document = self.model_dump(mode="json")
        document["placements"] = sorted(document["placements"], key=lambda p: p["id"] or "")
        return hashlib.sha256(json_bytes(document)).hexdigest()


class ArrayDescriptor(Record):
    shape: tuple[int, ...]
    dtype: Literal["float32", "int32"]
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlacementArtifact(Record):
    id: PlacementId | None
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    extent: tuple[int, int, int, int]
    arrays: dict[str, ArrayDescriptor]


class Manifest(Record):
    schema_version: Literal[1] = 1
    generation_id: PlacementId
    preparation_inputs: PreparationInputs
    semantics: dict[str, str]
    placements: tuple[PlacementArtifact, ...]
    provenance: dict[str, Any] = Field(default_factory=dict)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Acquired:
    manifest: Manifest
    maps: Mapping[str | None, MaterialMaps]


@dataclass(frozen=True)
class Readiness:
    state: Literal["needs_preparation", "out_of_date", "ready", "not_required"]
    reason: str | None = None
    message: str | None = None
    content_digest: str | None = None

    @property
    def can_render(self) -> bool:
        return self.state in ("ready", "not_required")


def arrays_of(maps: MaterialMaps) -> dict[str, Any]:
    return {
        field.name: getattr(maps, field.name)
        for field in fields(maps)
        if getattr(maps, field.name) is not None
    }


def validate_maps(maps: MaterialMaps, size: tuple[int, int]) -> None:
    width, height = size
    if min(size) < 1 or max(size) > 8192 or width * height > MAX_PIXELS:
        raise ArtifactError("Unsupported prepared-map dimensions")
    arrays = arrays_of(maps)
    for name, (low, high, channels) in BOUNDS.items():
        if name == "patch_ids" and name not in arrays:
            continue
        value = arrays[name]
        shape = (height, width, channels) if channels else (height, width)
        dtype = np.dtype("int32" if name == "patch_ids" else "float32")
        if value.shape != shape or value.dtype != dtype or not np.isfinite(value).all():
            raise ArtifactError(f"Invalid {name} shape, dtype or finite values")
        if np.any(value < low - 1e-6) or np.any(value > high + 1e-6):
            raise ArtifactError(f"Prepared {name} values outside declared bounds")


def descriptors(maps: MaterialMaps) -> dict[str, ArrayDescriptor]:
    return {
        name: ArrayDescriptor(
            shape=array.shape,
            dtype="int32" if name == "patch_ids" else "float32",
            checksum=hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest(),
        )
        for name, array in arrays_of(maps).items()
    }


def numerical_digest(placements: Mapping[str | None, MaterialMaps]) -> str:
    content = [
        {
            "id": key,
            "arrays": {
                name: descriptor.model_dump(mode="json")
                for name, descriptor in descriptors(placements[key]).items()
            },
        }
        for key in sorted(placements, key=lambda v: v or "")
    ]
    return hashlib.sha256(json_bytes({"semantics": SEMANTICS, "placements": content})).hexdigest()


def file_checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_maps(path: Path, descriptor: PlacementArtifact, size: tuple[int, int]) -> MaterialMaps:
    """Check all NPY headers and uncompressed byte budgets before allocation."""
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES or file_checksum(path) != descriptor.checksum:
            raise ArtifactError("Prepared archive size/checksum mismatch")
        required = set(BOUNDS) - {"patch_ids"}
        names = set(descriptor.arrays)
        if names not in (required, set(BOUNDS)):
            raise ArtifactError("Prepared array descriptor set is incomplete")
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) != len(names) or {m.filename for m in members} != {
                name + ".npy" for name in names
            }:
                raise ArtifactError("Prepared archive has unexpected or duplicate members")
            if sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
                raise ArtifactError("Prepared arrays exceed allocation budget")
            for member in members:
                name = member.filename[:-4]
                expected = descriptor.arrays[name]
                channels = BOUNDS[name][2]
                width, height = size
                shape = (height, width, channels) if channels else (height, width)
                dtype = np.dtype("int32" if name == "patch_ids" else "float32")
                if expected.shape != shape or expected.dtype != str(dtype):
                    raise ArtifactError("Unsafe prepared array descriptor")
                with archive.open(member) as stream:
                    version = np.lib.format.read_magic(stream)
                    if version == (1, 0):
                        actual_shape, fortran, actual_dtype = np.lib.format.read_array_header_1_0(
                            stream
                        )
                    elif version == (2, 0):
                        actual_shape, fortran, actual_dtype = np.lib.format.read_array_header_2_0(
                            stream
                        )
                    else:
                        raise ArtifactError("Unsupported prepared NPY format")
                    header_size = stream.tell()
                if (
                    actual_shape != shape
                    or actual_dtype != dtype
                    or fortran
                    or member.file_size != header_size + math.prod(shape) * dtype.itemsize
                ):
                    raise ArtifactError(
                        "Prepared array header has unsafe shape, dtype or byte length"
                    )
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in names}
        maps = MaterialMaps(**arrays)
        validate_maps(maps, size)
        if descriptors(maps) != descriptor.arrays:
            raise ArtifactError("Prepared numerical checksum mismatch")
        for array in arrays.values():
            array.flags.writeable = False
        return maps
    except (OSError, ValueError, zipfile.BadZipFile, EOFError, KeyError, TypeError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError("Invalid prepared artifact; prepare the template again") from exc


_READERS: dict[tuple[str, str], int] = {}


class Artifacts:
    """One complete set in, one leased immutable set out.

    Template locks serialize pointer changes and reader ownership in the
    single-server workspace model. Cleanup callers supply durable job references.
    """

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.calibration = CalibrationStore(workspace)

    def validate_inputs(self, inputs: PreparationInputs) -> None:
        """Refuse known map limits before runtime inspection or numerical work.

        Production baking includes optional patch labels. Every BOUNDS channel
        is four bytes (float32 or int32); count the full retained generation,
        not just one placement or compressed archive size.
        """
        try:
            checked = PreparationInputs.model_validate(inputs.model_dump())
        except ValueError as exc:
            raise ArtifactError("Invalid prepared-map inputs: " + str(exc)) from exc
        bytes_per_pixel = sum(max(channels, 1) * 4 for _, _, channels in BOUNDS.values())
        expected = (
            checked.photo.width * checked.photo.height * len(checked.placements) * bytes_per_pixel
        )
        if expected > MAX_ARCHIVE_BYTES:
            raise ArtifactError("Prepared generation exceeds allocation budget")

    def _key(self, name: str, generation: str) -> tuple[str, str]:
        return str(self.workspace.template_maps_dir(name)).casefold(), generation

    @contextmanager
    def _lease(self, name: str, generation: str) -> Iterator[None]:
        # Register ownership before exposing staging. The same canonical path
        # and template lock cover publishers, readers and alias-aware cleanup.
        key = self._key(name, generation)
        with self.calibration.lock(name):
            _READERS[key] = _READERS.get(key, 0) + 1
        try:
            yield
        finally:
            with self.calibration.lock(name):
                _READERS[key] -= 1
                if not _READERS[key]:
                    del _READERS[key]

    def _pointer(self, name: str) -> dict[str, Any]:
        path = self.workspace.template_map_current(name)
        if path.stat().st_size > 65536:
            raise ArtifactError("Invalid current map pointer")
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "generation_id",
            "manifest_checksum",
        }:
            raise ArtifactError("Invalid current map pointer")
        if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA:
            raise ArtifactError("Unsupported map schema; migrate or prepare the template again")
        if not isinstance(value["generation_id"], str) or not isinstance(
            value["manifest_checksum"], str
        ):
            raise ArtifactError("Invalid current map pointer; prepare the template again")
        self.workspace.template_map_generation_dir(name, value["generation_id"])
        return value

    def _read_manifest(
        self, name: str, generation: str, checksum: str, *, staging: bool = False
    ) -> Manifest:
        path = self.workspace.template_map_manifest(name, generation, staging=staging)
        if path.stat().st_size > 1024 * 1024 or file_checksum(path) != checksum:
            raise ArtifactError("Prepared manifest checksum mismatch")
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict):
            raise ArtifactError("Invalid prepared manifest; prepare the template again")
        if (
            type(document.get("schema_version")) is not int
            or document.get("schema_version") != SCHEMA
        ):
            raise ArtifactError("Unsupported map schema; migrate or prepare the template again")
        manifest = Manifest.model_validate(document)
        if manifest.generation_id != generation or manifest.semantics != SEMANTICS:
            raise ArtifactError("Unsupported map coordinate semantics")
        ids = [p.id for p in manifest.placements]
        if len(ids) != len(set(ids)) or set(ids) != set(manifest.preparation_inputs.ids):
            raise ArtifactError("Prepared generation does not contain the exact placement set")
        return manifest

    def _load(
        self, name: str, generation: str, checksum: str, *, staging: bool = False
    ) -> Acquired:
        manifest = self._read_manifest(name, generation, checksum, staging=staging)
        size = (manifest.preparation_inputs.photo.width, manifest.preparation_inputs.photo.height)
        if (
            sum(
                math.prod(descriptor.shape) * 4
                for placement in manifest.placements
                for descriptor in placement.arrays.values()
            )
            > MAX_ARCHIVE_BYTES
        ):
            raise ArtifactError("Prepared generation exceeds allocation budget")
        maps = {}
        for placement in manifest.placements:
            if placement.extent != (0, 0, *size):
                raise ArtifactError("Prepared map extent does not match main photo")
            maps[placement.id] = read_maps(
                self.workspace.template_map_file(name, generation, placement.id, staging=staging),
                placement,
                size,
            )
        if numerical_digest(maps) != manifest.content_digest:
            raise ArtifactError("Prepared generation numerical identity mismatch")
        return Acquired(manifest, MappingProxyType(maps))

    def saved_inputs(
        self,
        name: str,
        *,
        evidence: Mapping[str | None, str] | None = None,
        reset_masks_for_photo: bool = False,
    ) -> PreparationInputs:
        """Read current pixel-affecting inputs without cache or installed models.

        Evidence is the accepted checkpoint/preprocessing/photo/crop identity,
        not a cache path or runtime selection. Omission retains identity from
        the durable manifest. Explicit preparation supplies a new complete set.
        Appearance and placement order do not enter preparation identity.
        Explicit photo reset captures a zero mask identity only for a saved
        mask belonging to another photo. It never writes masks or bypasses
        damaged/missing mask components; valid same-photo edits are retained.
        """
        with self.calibration.lock(name):
            config = self.calibration.config(name)
            if not isinstance(config.renderer, MarigoldRenderer):
                raise ValueError("Prepared inputs require a Marigold template")
            accepted: dict[str | None, str] = {}
            if evidence is None:
                try:
                    pointer = self._pointer(name)
                    manifest = self._read_manifest(
                        name, pointer["generation_id"], pointer["manifest_checksum"]
                    )
                    accepted = {p.id: p.evidence for p in manifest.preparation_inputs.placements}
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            ids = self.calibration.placement_ids(config)
            if evidence is not None and set(evidence) != set(ids):
                raise ArtifactError("Evidence identity must cover the exact placement set")
            placements = []
            for placement_id in ids:
                box = (
                    next(p.bounding_box for p in config.placements if p.id == placement_id)
                    if isinstance(config, MultipleTemplate)
                    else config.bounding_box
                )
                checksum = "0" * 64
                has_mask = self.workspace.template_mask_file(name, placement_id).exists()
                if reset_masks_for_photo:
                    has_mask = has_mask or any(
                        self.workspace.template_mask_file(
                            name, placement_id, source=source
                        ).exists()
                        for source in ("automatic", "metadata")
                    )
                if has_mask:
                    try:
                        checksum = self.calibration.mask(name, placement_id).checksum
                    except MaskPhotoMismatch:
                        if not reset_masks_for_photo:
                            raise
                placements.append(
                    PlacementInput(
                        id=placement_id,
                        quad=(
                            (box[0].x, box[0].y),
                            (box[1].x, box[1].y),
                            (box[2].x, box[2].y),
                            (box[3].x, box[3].y),
                        ),
                        mask=checksum,
                        evidence=(evidence if evidence is not None else accepted).get(
                            placement_id, "0" * 64
                        ),
                    )
                )
            return PreparationInputs(
                photo=PhotoIdentity.model_validate(self.calibration.photo_identity(name, config)),
                placements=tuple(placements),
                inference=config.renderer.config.inference,
            )

    def publish(
        self,
        name: str,
        inputs: PreparationInputs,
        maps: Mapping[str | None, MaterialMaps],
        *,
        current_inputs: Callable[[], PreparationInputs],
        provenance: dict[str, Any] | None = None,
        checkpoint: Callable[[str], None] = lambda _: None,
    ) -> Manifest:
        generation = uuid4().hex
        with self._lease(name, generation):
            return self._publish(
                name,
                inputs,
                maps,
                current_inputs=current_inputs,
                provenance=provenance,
                checkpoint=checkpoint,
                generation=generation,
            )

    def _publish(
        self,
        name: str,
        inputs: PreparationInputs,
        maps: Mapping[str | None, MaterialMaps],
        *,
        current_inputs: Callable[[], PreparationInputs],
        provenance: dict[str, Any] | None = None,
        checkpoint: Callable[[str], None] = lambda _: None,
        generation: str,
    ) -> Manifest:
        if set(maps) != set(inputs.ids):
            raise ArtifactError("Publish requires the exact configured placement set")
        size = (inputs.photo.width, inputs.photo.height)
        if (
            sum(array.nbytes for value in maps.values() for array in arrays_of(value).values())
            > MAX_ARCHIVE_BYTES
        ):
            raise ArtifactError("Prepared generation exceeds allocation budget")
        for value in maps.values():
            validate_maps(value, size)
        staging = self.workspace.template_map_generation_dir(name, generation, staging=True)
        staging.mkdir(parents=True)
        entries = []
        for placement_id in sorted(maps, key=lambda v: v or ""):
            path = self.workspace.template_map_file(name, generation, placement_id, staging=True)
            canonical: dict[str, Any] = {
                key: np.ascontiguousarray(value)
                for key, value in arrays_of(maps[placement_id]).items()
            }
            with path.open("wb") as stream:
                np.savez_compressed(stream, **canonical)
                stream.flush()
                os.fsync(stream.fileno())
            entries.append(
                PlacementArtifact(
                    id=placement_id,
                    checksum=file_checksum(path),
                    extent=(0, 0, *size),
                    arrays=descriptors(maps[placement_id]),
                )
            )
        manifest = Manifest(
            generation_id=generation,
            preparation_inputs=inputs,
            semantics=SEMANTICS,
            placements=tuple(entries),
            provenance=provenance or {},
            content_digest=numerical_digest(maps),
        )
        manifest_path = self.workspace.template_map_manifest(name, generation, staging=True)
        write_bytes_atomic(
            manifest_path, json_bytes(manifest.model_dump(mode="json")), durable=True
        )
        checksum = file_checksum(manifest_path)
        self._load(name, generation, checksum, staging=True)
        checkpoint("validated")
        with self.calibration.lock(name):
            if current_inputs().identity() != inputs.identity():
                raise StalePreparation("Calibration changed; obsolete maps were not published")
            final = self.workspace.template_map_generation_dir(name, generation)
            final.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(final)
            checkpoint("generation")
            write_bytes_atomic(
                self.workspace.template_map_current(name),
                json_bytes(
                    {
                        "schema_version": SCHEMA,
                        "generation_id": generation,
                        "manifest_checksum": checksum,
                    }
                ),
                durable=True,
            )
            checkpoint("pointer")
        return manifest

    @contextmanager
    def acquire(
        self, name: str, inputs: PreparationInputs, *, target_size: tuple[int, int] | None = None
    ) -> Iterator[Acquired]:
        try:
            with self.calibration.lock(name):
                pointer = self._pointer(name)
                generation = pointer["generation_id"]
                key = self._key(name, generation)
                _READERS[key] = _READERS.get(key, 0) + 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError("Invalid prepared generation; prepare the template again") from exc
        try:
            try:
                acquired = self._load(name, generation, pointer["manifest_checksum"])
                if acquired.manifest.preparation_inputs.identity() != inputs.identity():
                    raise StalePreparation(
                        "Prepared maps are out of date; rebuild or prepare the template"
                    )
                if target_size is not None and target_size != (
                    inputs.photo.width,
                    inputs.photo.height,
                ):
                    raise ArtifactError("Shared colour photo dimensions differ from the main photo")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                if isinstance(exc, ArtifactError):
                    raise
                raise ArtifactError(
                    "Invalid prepared generation; prepare the template again"
                ) from exc
            # Exceptions from the renderer belong to the caller, not artifact loading.
            yield acquired
        finally:
            with self.calibration.lock(name):
                _READERS[key] -= 1
                if not _READERS[key]:
                    del _READERS[key]

    def readiness(
        self, name: str, inputs: PreparationInputs, *, target_size: tuple[int, int] | None = None
    ) -> Readiness:
        if not self.workspace.template_map_current(name).exists():
            return Readiness("needs_preparation", "missing_maps", "Prepare the template first")
        try:
            with self.acquire(name, inputs, target_size=target_size) as acquired:
                return Readiness("ready", content_digest=acquired.manifest.content_digest)
        except StalePreparation as exc:
            # The accepted inputs are immutable, so explain the first relevant change.
            reason = "placement_changed"
            try:
                pointer = self._pointer(name)
                accepted = self._load(
                    name, pointer["generation_id"], pointer["manifest_checksum"]
                ).manifest.preparation_inputs
                if accepted.photo != inputs.photo:
                    reason = "photo_changed"
                elif accepted.inference != inputs.inference:
                    reason = "inference_changed"
                elif {p.id: p.mask for p in accepted.placements} != {
                    p.id: p.mask for p in inputs.placements
                }:
                    reason = "mask_changed"
            except (OSError, ValueError, KeyError, TypeError):
                pass
            return Readiness("out_of_date", reason, str(exc))
        except ArtifactError as exc:
            reason = "unsupported_schema" if "Unsupported" in str(exc) else "invalid_artifact"
            if "dimensions differ" in str(exc):
                reason = "incompatible_dimensions"
            return Readiness("out_of_date", reason, str(exc))

    def cleanup(self, name: str, *, retained_generations: set[str] | None = None) -> list[str]:
        """Remove unreferenced generations; caller supplies all persisted job refs."""
        removed = []
        with self.calibration.lock(name):
            keep = set(retained_generations or ())
            with suppress(FileNotFoundError):
                keep.add(self._pointer(name)["generation_id"])
            for staging in (False, True):
                for generation in self.workspace.template_map_generations(name, staging=staging):
                    if generation in keep or _READERS.get(self._key(name, generation), 0):
                        continue
                    self.workspace.remove_map_generation(name, generation, staging=staging)
                    removed.append(generation)
        return removed
