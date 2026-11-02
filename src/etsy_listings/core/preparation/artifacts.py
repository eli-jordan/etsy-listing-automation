"""Validated immutable map generations, independent of inference installation.

ADR-0054: manifests describe numerical semantics. ZIP timestamps, generation
names, paths and diagnostic provenance do not enter the content digest.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import weakref
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Literal
from uuid import uuid4

import numpy as np
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    model_serializer,
    model_validator,
)

from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.render.config import (
    AnyTemplate,
    BoundingBox,
    MarigoldInference,
    MarigoldRenderer,
    MultipleTemplate,
    PlacementId,
)
from etsy_listings.core.render.material import MaterialMaps
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import (
    CalibrationStore,
    MaskPhotoMismatchError,
    json_bytes,
)
from etsy_listings.core.workspace.file_version import file_version

SCHEMA: Literal[2] = 2
MAX_PIXELS = 32 * 1024 * 1024
MAX_DIMENSION = 8192
MAX_POINTER_BYTES = 64 * 1024
_EXTENTS_SCHEMA = 2  # the manifest schema that records placement extents
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


ReadinessReason = Literal[
    "missing_maps",
    "missing_placements",
    "placement_changed",
    "photo_changed",
    "inference_changed",
    "mask_changed",
    "unsupported_schema",
    "incompatible_dimensions",
    "invalid_artifact",
]


class ArtifactError(ValueError):
    """Prepare the template again instead of interpreting an invalid map.

    ``reason`` is the readiness cause each refusal reports, so status is read
    from the type raised and never from its message."""

    reason: ClassVar[ReadinessReason] = "invalid_artifact"


class StalePreparationError(ArtifactError):
    """Current geometry, masks or evidence changed before publication."""

    reason: ClassVar[ReadinessReason] = "placement_changed"


class UnsupportedSchemaError(ArtifactError):
    """A map pointer or manifest this version cannot read."""

    reason: ClassVar[ReadinessReason] = "unsupported_schema"


class IncompatibleDimensionsError(ArtifactError):
    """A target photo whose size differs from the prepared main photo."""

    reason: ClassVar[ReadinessReason] = "incompatible_dimensions"


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

    @classmethod
    def from_box(
        cls, placement_id: PlacementId | None, box: BoundingBox, *, mask: str, evidence: str
    ) -> PlacementInput:
        return cls(
            id=placement_id,
            quad=(
                (box[0].x, box[0].y),
                (box[1].x, box[1].y),
                (box[2].x, box[2].y),
                (box[3].x, box[3].y),
            ),
            mask=mask,
            evidence=evidence,
        )

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


def _exact_schema(value: object) -> object:
    # JSON ``true`` and ``1.0`` are not schema 1.
    if type(value) is not int:
        raise ValueError("Map schema version must be an integer")
    return value


MapSchema = Annotated[Literal[1, 2], BeforeValidator(_exact_schema)]


class MapPointer(Record):
    """``_renderer/maps/current.json``: the accepted generation and the
    checksum its manifest must have."""

    schema_version: MapSchema
    generation_id: str
    manifest_checksum: str


class Provenance(BaseModel):
    """Who published a generation: diagnostics only, never numerical identity.

    Unknown keys are ignored, so a diagnostic cannot invalidate a generation
    whose numerical content is sound."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    job_id: str | None = None
    engine_version: str | None = None
    installation_id: str | None = None

    @model_serializer(mode="wrap")
    def _recorded(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        # Only the keys the publisher recorded, so a generation published
        # without provenance still records ``{}``.
        dumped: dict[str, object] = handler(self)
        return {key: value for key, value in dumped.items() if key in self.model_fields_set}


class Manifest(Record):
    schema_version: MapSchema
    generation_id: PlacementId
    preparation_inputs: PreparationInputs
    semantics: dict[str, str]
    placements: tuple[PlacementArtifact, ...]
    provenance: Provenance = Field(default_factory=Provenance)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


_UNSUPPORTED = "Unsupported map schema; migrate or prepare the template again"


def _unsupported(exc: ValidationError) -> bool:
    """Whether ``exc`` refuses a record's schema version, which this version
    cannot read, rather than the rest of its shape."""
    return any(error["loc"] == ("schema_version",) for error in exc.errors())


@dataclass(frozen=True)
class Acquired:
    manifest: Manifest
    maps: Mapping[str | None, MaterialMaps]


@dataclass(frozen=True)
class Readiness:
    state: Literal["needs_preparation", "out_of_date", "ready", "not_required"]
    reason: ReadinessReason | None = None
    message: str | None = None
    content_digest: str | None = None

    @property
    def can_render(self) -> bool:
        return self.state in ("ready", "not_required")


_ZERO_DIGEST = "0" * 64  # the identity of an absent mask or evidence


def _bounding_box(config: AnyTemplate, placement_id: str | None) -> BoundingBox:
    if isinstance(config, MultipleTemplate):
        return next(p.bounding_box for p in config.placements if p.id == placement_id)
    return config.bounding_box


def arrays_of(maps: MaterialMaps) -> dict[str, Any]:
    return {name: getattr(maps, name) for name in BOUNDS if getattr(maps, name) is not None}


def _within(extent: tuple[int, int, int, int], size: tuple[int, int]) -> bool:
    """Whether the half-open ``extent`` is non-empty and inside the photo."""
    photo_width, photo_height = size
    left, top, right, bottom = extent
    return 0 <= left < right <= photo_width and 0 <= top < bottom <= photo_height


def _layout(name: str, extent: tuple[int, int, int, int]) -> tuple[tuple[int, ...], np.dtype]:
    """The shape and dtype array ``name`` must have over ``extent``."""
    left, top, right, bottom = extent
    width, height = right - left, bottom - top
    channels = BOUNDS[name][2]
    shape = (height, width, channels) if channels else (height, width)
    return shape, np.dtype("int32" if name == "patch_ids" else "float32")


def validate_maps(maps: MaterialMaps, size: tuple[int, int]) -> None:
    left, top, right, bottom = maps.extent
    if maps.size != size or not _within(maps.extent, size):
        raise ArtifactError("Prepared map extent does not match main photo")
    width, height = right - left, bottom - top
    if min(size) < 1 or max(size) > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise UnsupportedSchemaError("Unsupported prepared-map dimensions")
    arrays = arrays_of(maps)
    for name in BOUNDS:
        if name == "patch_ids" and name not in arrays:
            continue
        _check_array(name, arrays[name], maps.extent)


def _check_array(name: str, value: Any, extent: tuple[int, int, int, int]) -> None:
    low, high, _ = BOUNDS[name]
    shape, dtype = _layout(name, extent)
    if value.shape != shape or value.dtype != dtype or not np.isfinite(value).all():
        raise ArtifactError(f"Invalid {name} shape, dtype or finite values")
    if np.any(value < low - 1e-6) or np.any(value > high + 1e-6):
        raise ArtifactError(f"Prepared {name} values outside declared bounds")


_DESCRIPTOR_LOCK = threading.Lock()
_DESCRIPTORS: dict[
    int, tuple[weakref.ReferenceType[MaterialMaps], tuple[Any, ...], dict[str, ArrayDescriptor]]
] = {}


def _forget_descriptors(reference: weakref.ReferenceType[MaterialMaps], key: int) -> None:
    with _DESCRIPTOR_LOCK:
        entry = _DESCRIPTORS.get(key)
        if entry is not None and entry[0] is reference:
            del _DESCRIPTORS[key]


def descriptors(maps: MaterialMaps) -> dict[str, ArrayDescriptor]:
    arrays = arrays_of(maps)
    immutable = all(not a.flags.writeable and a.flags.owndata for a in arrays.values())
    signature = tuple((name, id(a), a.shape, a.dtype.str, a.strides) for name, a in arrays.items())
    if immutable:
        with _DESCRIPTOR_LOCK:
            entry = _DESCRIPTORS.get(id(maps))
            if entry is not None and entry[0]() is maps and entry[1] == signature:
                return entry[2].copy()
    result = {
        name: ArrayDescriptor(
            shape=array.shape,
            dtype="int32" if name == "patch_ids" else "float32",
            checksum=hashlib.sha256(np.ascontiguousarray(array)).hexdigest(),
        )
        for name, array in arrays.items()
    }
    if immutable:
        key = id(maps)
        reference = weakref.ref(maps, lambda ref: _forget_descriptors(ref, key))
        with _DESCRIPTOR_LOCK:
            _DESCRIPTORS[key] = reference, signature, result
    return result.copy()


def numerical_digest(placements: Mapping[str | None, MaterialMaps]) -> str:
    return _descriptor_digest(
        {key: descriptors(value) for key, value in placements.items()},
        extents={key: value.extent for key, value in placements.items()},
    )


def _descriptor_digest(
    placements: Mapping[str | None, Mapping[str, ArrayDescriptor]],
    *,
    extents: Mapping[str | None, tuple[int, int, int, int]] | None = None,
) -> str:
    content = [
        {
            "id": key,
            **({"extent": extents[key]} if extents is not None else {}),
            "arrays": {
                name: descriptor.model_dump(mode="json")
                for name, descriptor in placements[key].items()
            },
        }
        for key in sorted(placements, key=lambda v: v or "")
    ]
    return hashlib.sha256(json_bytes({"semantics": SEMANTICS, "placements": content})).hexdigest()


def _manifest_digest(manifest: Manifest) -> str:
    """The content digest ``manifest``'s descriptors imply; only schema 2
    records extents."""
    return _descriptor_digest(
        {p.id: p.arrays for p in manifest.placements},
        extents={p.id: p.extent for p in manifest.placements}
        if manifest.schema_version == _EXTENTS_SCHEMA
        else None,
    )


def file_checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_maps(
    path: Path,
    descriptor: PlacementArtifact,
    size: tuple[int, int],
    *,
    known_maps: MaterialMaps | None = None,
) -> MaterialMaps:
    """Check all NPY headers and uncompressed byte budgets before allocation."""
    if not _within(descriptor.extent, size):
        raise ArtifactError("Prepared map extent does not match main photo")
    if known_maps is not None and any(a.flags.writeable for a in arrays_of(known_maps).values()):
        known_maps = None
    try:
        maps = _read_checked_maps(path, descriptor, size, known_maps)
    except (OSError, ValueError, zipfile.BadZipFile, EOFError, KeyError, TypeError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError("Invalid prepared artifact; prepare the template again") from exc
    else:
        return maps


def _read_checked_maps(
    path: Path,
    descriptor: PlacementArtifact,
    size: tuple[int, int],
    known_maps: MaterialMaps | None,
) -> MaterialMaps:
    """``known_maps`` are the read-only arrays just written to ``path``; they
    are kept, after their written bytes are proven, instead of loading a copy."""
    if path.stat().st_size > MAX_ARCHIVE_BYTES or file_checksum(path) != descriptor.checksum:
        raise ArtifactError("Prepared archive size/checksum mismatch")
    names = set(descriptor.arrays)
    if names not in (set(BOUNDS) - {"patch_ids"}, set(BOUNDS)):
        raise ArtifactError("Prepared array descriptor set is incomplete")
    with zipfile.ZipFile(path) as archive:
        _check_archive(archive, descriptor, names, verify_payload=known_maps is not None)
    if known_maps is None:
        with np.load(path, allow_pickle=False) as loaded:
            arrays = {name: loaded[name] for name in names}
        left, top, _, _ = descriptor.extent
        maps = MaterialMaps(**arrays, origin=(left, top), photo_size=size)
    else:
        maps = known_maps
        arrays = arrays_of(maps)
    validate_maps(maps, size)
    if descriptors(maps) != descriptor.arrays:
        raise ArtifactError("Prepared numerical checksum mismatch")
    for array in arrays.values():
        array.flags.writeable = False
    return maps


def _check_archive(
    archive: zipfile.ZipFile,
    descriptor: PlacementArtifact,
    names: set[str],
    *,
    verify_payload: bool,
) -> None:
    members = archive.infolist()
    if len(members) != len(names) or {m.filename for m in members} != {
        name + ".npy" for name in names
    }:
        raise ArtifactError("Prepared archive has unexpected or duplicate members")
    if sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
        raise ArtifactError("Prepared arrays exceed allocation budget")
    for member in members:
        _check_member(archive, member, descriptor, verify_payload=verify_payload)


_NPY_HEADER_READERS: Mapping[tuple[int, int], Callable[[Any], tuple[Any, bool, np.dtype]]] = {
    (1, 0): np.lib.format.read_array_header_1_0,
    (2, 0): np.lib.format.read_array_header_2_0,
}


def _check_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    descriptor: PlacementArtifact,
    *,
    verify_payload: bool,
) -> None:
    name = member.filename[:-4]
    expected = descriptor.arrays[name]
    shape, dtype = _layout(name, descriptor.extent)
    if expected.shape != shape or expected.dtype != str(dtype):
        raise ArtifactError("Unsafe prepared array descriptor")
    with archive.open(member) as stream:
        read_header = _NPY_HEADER_READERS.get(np.lib.format.read_magic(stream))
        if read_header is None:
            raise UnsupportedSchemaError("Unsupported prepared NPY format")
        actual_shape, fortran, actual_dtype = read_header(stream)
        header_size = stream.tell()
    if (
        actual_shape != shape
        or actual_dtype != dtype
        or fortran
        or member.file_size != header_size + math.prod(shape) * dtype.itemsize
    ):
        raise ArtifactError("Prepared array header has unsafe shape, dtype or byte length")
    if verify_payload:
        # Verify written payload bytes and ZIP CRC only after header,
        # shape, dtype and byte-budget checks have passed.
        _check_payload(archive, member, header_size, expected.checksum)


def _check_payload(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo, header_size: int, checksum: str
) -> None:
    with archive.open(member) as stream:
        stream.read(header_size)
        payload = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            payload.update(chunk)
        if payload.hexdigest() != checksum:
            raise ArtifactError("Prepared numerical checksum mismatch")


_READERS: dict[tuple[str, str], int] = {}


def _maps_bytes(maps: Mapping[str | None, MaterialMaps]) -> int:
    return sum(a.nbytes for m in maps.values() for a in arrays_of(m).values())


# Cache validation proofs, never arrays. A status poll must not decompress and
# hash hundreds of MiB while holding the calibration lock. Immutable generation
# files are revalidated after replacement, writes, removal or process restart.
_VALIDATED: BoundedCache[tuple[Any, ...], bool] = BoundedCache(128)
MAP_CACHE_BYTES = 512 * 1024 * 1024
_MAPS: BoundedCache[tuple[Any, ...], Mapping[str | None, MaterialMaps]] = BoundedCache(
    MAP_CACHE_BYTES, size=_maps_bytes
)


def _no_checkpoint(_step: str) -> None:
    return None


@dataclass(frozen=True)
class PublishOptions:
    """How :meth:`Artifacts.publish` records and paces a generation.
    ``provenance`` is stored in its manifest; ``checkpoint`` is told each
    durable step and may raise to stop before the next. ``copy_maps=False``
    transfers immutable array ownership to the bounded reader cache: the
    coordinator uses it after freezing its private maps, and ordinary callers
    keep the default independent input snapshot."""

    provenance: Provenance = field(default_factory=Provenance)
    checkpoint: Callable[[str], None] = _no_checkpoint
    copy_maps: bool = True


@dataclass(frozen=True)
class _Publication:
    inputs: PreparationInputs
    maps: Mapping[str | None, MaterialMaps]
    current_inputs: Callable[[], PreparationInputs]
    options: PublishOptions


class Artifacts:
    """One complete set in, one leased immutable set out.

    Template locks serialize pointer changes and reader ownership in the
    single-server workspace model. Cleanup keeps the current generation and
    every one a publisher or reader has leased.
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

    def _pointer(self, name: str) -> MapPointer:
        path = self.workspace.template_map_current(name)
        if path.stat().st_size > MAX_POINTER_BYTES:
            raise ArtifactError("Invalid current map pointer")
        try:
            pointer = MapPointer.model_validate_json(path.read_bytes())
        except ValidationError as exc:
            # A pointer missing or adding a key is damaged, whatever its schema.
            reshaped = any(e["type"] in ("missing", "extra_forbidden") for e in exc.errors())
            if _unsupported(exc) and not reshaped:
                raise UnsupportedSchemaError(_UNSUPPORTED) from exc
            raise ArtifactError("Invalid current map pointer; prepare the template again") from exc
        self.workspace.template_map_generation_dir(name, pointer.generation_id)
        return pointer

    def _current(self, name: str) -> tuple[MapPointer, Manifest]:
        """The current pointer and the validated manifest it names."""
        pointer = self._pointer(name)
        return pointer, self._read_manifest(name, pointer.generation_id, pointer.manifest_checksum)

    def _read_manifest(
        self, name: str, generation: str, checksum: str, *, staging: bool = False
    ) -> Manifest:
        path = self.workspace.template_map_manifest(name, generation, staging=staging)
        if path.stat().st_size > 1024 * 1024 or file_checksum(path) != checksum:
            raise ArtifactError("Prepared manifest checksum mismatch")
        try:
            manifest = Manifest.model_validate_json(path.read_bytes())
        except ValidationError as exc:
            if _unsupported(exc):
                raise UnsupportedSchemaError(_UNSUPPORTED) from exc
            raise ArtifactError("Invalid prepared manifest; prepare the template again") from exc
        if manifest.generation_id != generation or manifest.semantics != SEMANTICS:
            raise UnsupportedSchemaError("Unsupported map coordinate semantics")
        ids = [p.id for p in manifest.placements]
        if len(ids) != len(set(ids)) or set(ids) != set(manifest.preparation_inputs.ids):
            raise ArtifactError("Prepared generation does not contain the exact placement set")
        return manifest

    def _signature(
        self, name: str, manifest: Manifest, checksum: str, *, staging: bool = False
    ) -> tuple[Any, ...]:
        paths = [
            self.workspace.template_map_manifest(name, manifest.generation_id, staging=staging)
        ]
        paths.extend(
            self.workspace.template_map_file(name, manifest.generation_id, p.id, staging=staging)
            for p in manifest.placements
        )
        return (
            checksum,
            *((str(path.resolve()).casefold(), *file_version(path)) for path in paths),
        )

    def inspect(
        self, name: str, inputs: PreparationInputs, *, target_size: tuple[int, int] | None = None
    ) -> Manifest:
        """Inspect a validated immutable generation without retaining its arrays.

        The template lock protects the pointer and files for the entire read.
        Validation proofs are bounded and invalidated by every file's identity,
        size and nanosecond write/change times. No model or prediction is read.
        """
        try:
            with self.calibration.lock(name):
                pointer, manifest = self._current(name)
                generation, checksum = pointer.generation_id, pointer.manifest_checksum
                self._check_inputs(manifest, inputs, target_size)
                signature = self._signature(name, manifest, checksum)
                if _VALIDATED.get(signature) is None:
                    manifest = self._load(name, generation, checksum).manifest
                return manifest
        except (OSError, ValueError) as exc:
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError("Invalid prepared generation; prepare the template again") from exc

    @staticmethod
    def _check_inputs(
        manifest: Manifest, inputs: PreparationInputs, target_size: tuple[int, int] | None
    ) -> None:
        if manifest.preparation_inputs.identity() != inputs.identity():
            raise StalePreparationError(
                "Prepared maps are out of date; rebuild or prepare the template"
            )
        if target_size is not None and target_size != (inputs.photo.width, inputs.photo.height):
            raise IncompatibleDimensionsError(
                "Shared colour photo dimensions differ from the main photo"
            )

    def _load(
        self,
        name: str,
        generation: str,
        checksum: str,
        *,
        staging: bool = False,
        known_maps: Mapping[str | None, MaterialMaps] | None = None,
    ) -> Acquired:
        manifest = self._read_manifest(name, generation, checksum, staging=staging)
        signature = self._signature(name, manifest, checksum, staging=staging)
        cached = _MAPS.get(signature)
        if cached is not None:
            return Acquired(manifest, cached)
        if (
            sum(
                math.prod(descriptor.shape) * 4
                for placement in manifest.placements
                for descriptor in placement.arrays.values()
            )
            > MAX_ARCHIVE_BYTES
        ):
            raise ArtifactError("Prepared generation exceeds allocation budget")
        maps = {
            placement.id: self._read_placement(
                name,
                manifest,
                placement,
                staging=staging,
                known_maps=known_maps.get(placement.id) if known_maps is not None else None,
            )
            for placement in manifest.placements
        }
        if _manifest_digest(manifest) != manifest.content_digest:
            raise ArtifactError("Prepared generation numerical identity mismatch")
        if self._signature(name, manifest, checksum, staging=staging) != signature:
            raise ArtifactError("Prepared files changed during validation")
        _VALIDATED.put(signature, value=True)
        frozen = MappingProxyType(maps)
        _MAPS.put(signature, frozen)
        return Acquired(manifest, frozen)

    def _read_placement(
        self,
        name: str,
        manifest: Manifest,
        placement: PlacementArtifact,
        *,
        staging: bool,
        known_maps: MaterialMaps | None,
    ) -> MaterialMaps:
        photo = manifest.preparation_inputs.photo
        size = (photo.width, photo.height)
        if manifest.schema_version == 1 and placement.extent != (0, 0, *size):
            raise ArtifactError("Prepared map extent does not match main photo")
        return read_maps(
            self.workspace.template_map_file(
                name, manifest.generation_id, placement.id, staging=staging
            ),
            placement,
            size,
            known_maps=known_maps,
        )

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
                raise ValueError(  # noqa: TRY004 -- callers record this ValueError as a bad template
                    "Prepared inputs require a Marigold template"
                )
            ids = self.calibration.placement_ids(config)
            if evidence is None:
                evidence = self._accepted_evidence(name)
            elif set(evidence) != set(ids):
                raise ArtifactError("Evidence identity must cover the exact placement set")
            placements = tuple(
                PlacementInput.from_box(
                    placement_id,
                    _bounding_box(config, placement_id),
                    mask=self._mask_checksum(name, placement_id, reset=reset_masks_for_photo),
                    evidence=evidence.get(placement_id, _ZERO_DIGEST),
                )
                for placement_id in ids
            )
            return PreparationInputs(
                photo=PhotoIdentity.model_validate(
                    self.calibration.photo_identity(name, config).model_dump()
                ),
                placements=placements,
                inference=config.renderer.config.inference,
            )

    def _accepted_evidence(self, name: str) -> Mapping[str | None, str]:
        """Each placement's evidence identity in the current generation; none
        when there is no readable generation."""
        try:
            _, manifest = self._current(name)
        except (OSError, ValueError):
            return {}
        return {p.id: p.evidence for p in manifest.preparation_inputs.placements}

    def _mask_checksum(self, name: str, placement_id: str | None, *, reset: bool) -> str:
        """The saved mask's identity, or zero for none. A photo reset also
        counts a mask belonging to another photo as none."""
        if not self._has_mask(name, placement_id, reset=reset):
            return _ZERO_DIGEST
        try:
            return self.calibration.mask(name, placement_id).checksum
        except MaskPhotoMismatchError:
            if not reset:
                raise
            return _ZERO_DIGEST

    def _has_mask(self, name: str, placement_id: str | None, *, reset: bool) -> bool:
        if self.workspace.template_mask_file(name, placement_id).exists():
            return True
        return reset and (
            self.workspace.template_mask_file(name, placement_id, source="automatic").exists()
            or self.workspace.template_mask_file(name, placement_id, source="metadata").exists()
        )

    def publish(
        self,
        name: str,
        inputs: PreparationInputs,
        maps: Mapping[str | None, MaterialMaps],
        *,
        current_inputs: Callable[[], PreparationInputs],
        options: PublishOptions = PublishOptions(),
    ) -> Manifest:
        """Publish a complete validated generation of ``maps``, prepared from
        ``inputs``; ``current_inputs`` re-reads them before the switch."""
        generation = uuid4().hex
        with self._lease(name, generation):
            return self._publish(
                name, generation, _Publication(inputs, maps, current_inputs, options)
            )

    def _publish(self, name: str, generation: str, publication: _Publication) -> Manifest:
        inputs, maps = publication.inputs, publication.maps
        current_inputs = publication.current_inputs
        provenance = publication.options.provenance
        checkpoint = publication.options.checkpoint
        copy_maps = publication.options.copy_maps
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
                np.savez(stream, **canonical)
                stream.flush()
                os.fsync(stream.fileno())
            entries.append(
                PlacementArtifact(
                    id=placement_id,
                    checksum=file_checksum(path),
                    extent=maps[placement_id].extent,
                    arrays=descriptors(maps[placement_id]),
                )
            )
        manifest = Manifest(
            schema_version=SCHEMA,
            generation_id=generation,
            preparation_inputs=inputs,
            semantics=SEMANTICS,
            placements=tuple(entries),
            provenance=provenance,
            content_digest=_descriptor_digest(
                {p.id: p.arrays for p in entries}, extents={p.id: p.extent for p in entries}
            ),
        )
        manifest_path = self.workspace.template_map_manifest(name, generation, staging=True)
        write_bytes_atomic(
            manifest_path, json_bytes(manifest.model_dump(mode="json")), durable=True
        )
        checksum = file_checksum(manifest_path)
        validated = self._load(
            name, generation, checksum, staging=True, known_maps=None if copy_maps else maps
        )
        staging_signature = self._signature(name, manifest, checksum, staging=True)
        checkpoint("validated")
        with self.calibration.lock(name):
            if current_inputs().identity() != inputs.identity():
                raise StalePreparationError("Calibration changed; obsolete maps were not published")
            final = self.workspace.template_map_generation_dir(name, generation)
            final.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(final)
            final_signature = self._signature(name, manifest, checksum)
            _VALIDATED.put(final_signature, value=True)
            _MAPS.discard(staging_signature)
            _MAPS.put(final_signature, validated.maps)
            checkpoint("generation")
            pointer = MapPointer(
                schema_version=SCHEMA, generation_id=generation, manifest_checksum=checksum
            )
            write_bytes_atomic(
                self.workspace.template_map_current(name),
                json_bytes(pointer.model_dump(mode="json")),
                durable=True,
            )
            checkpoint("pointer")
        return manifest

    @contextmanager
    def reusable(
        self, name: str, inputs: PreparationInputs
    ) -> Iterator[Mapping[str | None, MaterialMaps]]:
        """Lease exact unchanged placements while a replacement is fitted.

        Photo, inference and compatibility must all match. Each retained map
        additionally needs the same placement ID, quad, mask and evidence.
        Missing/damaged old maps provide no reuse and never authorize inference.
        """
        with ExitStack() as lease:
            reused: dict[str | None, MaterialMaps] = {}
            try:
                with self.calibration.lock(name):
                    _, manifest = self._current(name)
                    accepted = manifest.preparation_inputs
                    unchanged: set[str | None] = set()
                    if (
                        accepted.photo == inputs.photo
                        and accepted.inference == inputs.inference
                        and accepted.compatibility == inputs.compatibility
                    ):
                        unchanged = {p.id for p in inputs.placements if p in accepted.placements}
                # acquire registers its own generation lease before loading. Keep
                # archive reads outside the template lock so previews can snapshot.
                if unchanged:
                    acquired = lease.enter_context(self.acquire(name, accepted))
                    reused = {key: acquired.maps[key].cropped_to_visibility() for key in unchanged}
            except (OSError, ValueError):
                pass
            yield MappingProxyType(reused)

    @contextmanager
    def acquire(
        self, name: str, inputs: PreparationInputs, *, target_size: tuple[int, int] | None = None
    ) -> Iterator[Acquired]:
        try:
            with self.calibration.lock(name):
                pointer, manifest = self._current(name)
                key = self._key(name, pointer.generation_id)
                _READERS[key] = _READERS.get(key, 0) + 1
        except (OSError, ValueError) as exc:
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError("Invalid prepared generation; prepare the template again") from exc
        try:
            try:
                self._check_inputs(manifest, inputs, target_size)
                acquired = self._load(name, pointer.generation_id, pointer.manifest_checksum)
            except (OSError, ValueError) as exc:
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
            manifest = self.inspect(name, inputs, target_size=target_size)
            return Readiness("ready", content_digest=manifest.content_digest)
        except StalePreparationError as exc:
            return Readiness("out_of_date", self._stale_reason(name, inputs, exc), str(exc))
        except ArtifactError as exc:
            return Readiness("out_of_date", exc.reason, str(exc))

    def _stale_reason(
        self, name: str, inputs: PreparationInputs, exc: StalePreparationError
    ) -> ReadinessReason:
        """The first relevant change since the accepted, immutable inputs."""
        try:
            _, manifest = self._current(name)
        except (OSError, ValueError):
            return exc.reason
        accepted = manifest.preparation_inputs
        if accepted.photo != inputs.photo:
            return "photo_changed"
        if accepted.inference != inputs.inference:
            return "inference_changed"
        if {p.id: p.mask for p in accepted.placements} != {p.id: p.mask for p in inputs.placements}:
            return "mask_changed"
        return exc.reason

    def cleanup(self, name: str) -> list[str]:
        """Remove every generation that is neither current nor leased."""
        removed = []
        with self.calibration.lock(name):
            keep: set[str] = set()
            with suppress(FileNotFoundError):
                keep.add(self._pointer(name).generation_id)
            for staging in (False, True):
                for generation in self.workspace.template_map_generations(name, staging=staging):
                    if generation in keep or _READERS.get(self._key(name, generation), 0):
                        continue
                    self.workspace.remove_map_generation(name, generation, staging=staging)
                    removed.append(generation)
        return removed
