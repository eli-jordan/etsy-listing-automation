"""Durable calibration documents and mask edits, protected by template locks.

ADR-0054: revision tokens protect editor saves; they are not render hashes.
Import this module directly. Its storage implementation is not re-exported.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, NoReturn, cast

import yaml
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from etsy_listings.core.config.template_labels import saved_labels
from etsy_listings.core.errors import ConflictError, RefusedError, StaleError
from etsy_listings.core.render.config import (
    AnyTemplate,
    MultipleTemplate,
    PlacementId,
    dump_template_config,
    load_template_config,
)
from etsy_listings.core.workspace import locks
from etsy_listings.core.workspace.atomic import write_bytes_atomic, write_json_atomic
from etsy_listings.core.workspace.file_version import file_version
from etsy_listings.core.workspace.template_state import (
    CalibrationRepairRequiredError,
    TemplateAbsent,
    TemplateNeedsRepair,
    TemplateState,
    template_state,
)
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.yaml_source import edit_yaml_bytes

if TYPE_CHECKING:
    from etsy_listings.core.workspace import MaskSource, Workspace

MAX_MASK_EDIT_BYTES = 2_000_000
_MASKS: tuple[MaskSource, ...] = ("automatic", "edited")
_MASK_FILES: tuple[MaskSource, ...] = (*_MASKS, "metadata")
# What an edit leaves beside the automatic baseline; alone, they need repair.
_EDITED_FILES: tuple[MaskSource, ...] = ("edited", "metadata")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class _Record(BaseModel):
    """A durable JSON record. Each is written as ``json_bytes`` of its JSON
    dump, so its fields are exactly the keys the file has always held."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class MainPhotoIdentity(_Record):
    """The main photo a template's masks belong to: its filename, size and
    decoded RGB pixels. Enters the calibration revision as dumped."""

    file: str
    width: int
    height: int
    conversion: Literal["pillow-rgb-v1"]
    pixels: str

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


class MaskMetadata(_Record):
    """``_renderer/masks/metadata.json``: binds one placement's automatic and
    edited masks to the main photo they were drawn on."""

    schema_version: Literal[1]
    photo: MainPhotoIdentity
    algorithm_version: str
    automatic_checksum: str
    edited_checksum: str


class SaveReceipt(_Record):
    """The last save, so a retried request answers as the first did.
    ``config`` stays the raw template document: it is parsed only on replay,
    so a receipt from an older template format never blocks a new save."""

    request_id: str
    digest: str
    revision: str
    config: dict[str, Any]
    main_photo: str


class StagedFile(_Record):
    """One destination of a calibration transaction, its staged payload and
    backup, each relative to its own directory."""

    destination: str
    payload: str
    checksum: str
    backup: str


class TransactionManifest(_Record):
    """``calibration-transaction/manifest.json``. Durable ``commit_intent``
    means roll every file forward; recovery marks it ``complete`` before
    removing the transaction, a key absent until then."""

    schema_version: Literal[1]
    commit_intent: bool = False
    files: tuple[StagedFile, ...]
    complete: bool = Field(default=False, exclude_if=lambda complete: not complete)


@lru_cache(maxsize=128)
def _photo_identity(path: Path, _stamp: tuple[int | str, ...]) -> MainPhotoIdentity:
    # ``_stamp`` is read by lru_cache only: a changed photo is a new cache key.
    with Image.open(path) as image:
        pixels = image.convert("RGB")
        return MainPhotoIdentity(
            file=path.name,
            width=pixels.width,
            height=pixels.height,
            conversion="pillow-rgb-v1",
            pixels=digest(pixels.tobytes()),
        )


@lru_cache(maxsize=256)
def _validate_mask(data: bytes, size: tuple[int, int]) -> None:
    # Bounded by entries AND payload size at the caller. Keep compressed mask
    # bytes only, never decoded photo-sized images. Content keys detect damage.
    with Image.open(BytesIO(data)) as image:
        if image.format != "PNG" or image.mode != "L" or image.size != size:
            raise ValueError("Mask must be a full-photo grayscale PNG")
        image.load()


class CalibrationChangedError(StaleError):
    """The calibration revision a save or Prepare was made against is no
    longer the saved one; the caller reloads before asking again."""


class CalibrationRequestReusedError(ConflictError):
    """A save request ID came back with different content. A retry of the
    same save answers as the first did; this is not one."""


class MaskUnavailableError(ConflictError):
    """Mask editing or Undo has no usable saved baseline/history."""


class MaskEditRefusedError(RefusedError):
    """Mask edits that no saved mask could take: too large a request, two
    entries for one placement, or a stroke outside the main photo."""


class MaskPhotoMismatchError(MaskUnavailableError):
    """Saved masks belong to another main photo and require an explicit reset."""


FiniteCoordinate = Annotated[float, Field(allow_inf_nan=False)]


class Stroke(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["stroke"]
    mode: Literal["mask", "unmask"]
    diameter_px: float = Field(gt=0, le=10000, allow_inf_nan=False)
    points: list[tuple[FiniteCoordinate, FiniteCoordinate]] = Field(min_length=1, max_length=10000)


class Undo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["undo"]


class Reset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["reset"]


MaskOperation = Annotated[Stroke | Undo | Reset, Field(discriminator="type")]


class BrushStroke(_Record):
    """One Undo step: the base64 PNG mask before ``operation`` painted it."""

    before: str
    operation: Stroke


class BrushHistory(_Record):
    """The cached Undo history of the edited mask whose digest is ``checksum``."""

    checksum: str
    strokes: tuple[BrushStroke, ...]


class MaskEdit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    placement_id: PlacementId | None = None
    operations: list[MaskOperation] = Field(min_length=1, max_length=256)


@dataclass(frozen=True)
class SavedMask:
    automatic: bytes
    edited: bytes
    checksum: str
    undo_count: int


@dataclass(frozen=True)
class Calibration:
    config: AnyTemplate
    revision: str
    main_photo: str = ""


@dataclass(frozen=True)
class AutomaticMask:
    """A generated visibility mask: its PNG bytes, the algorithm version that
    made it, and the placement it covers (``None`` for single-placement
    kinds)."""

    data: bytes
    algorithm_version: str
    placement_id: str | None = None


def _damaged(message: str) -> NoReturn:
    # S01 TRY301: the handler wraps this as a repair refusal.
    raise ValueError(message)


_DAMAGED_MASK = "Saved mask is damaged; repair or explicitly reset its baseline"


def _mask_metadata(path: Path) -> MaskMetadata:
    try:
        return MaskMetadata.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise CalibrationRepairRequiredError(_DAMAGED_MASK) from exc


def _replayed(receipt_path: Path, request_id: str, request_digest: str) -> Calibration | None:
    """The calibration a save with this request id already produced, so a
    retried request answers as the first did; None for a new request."""
    if not receipt_path.is_file():
        return None
    receipt = SaveReceipt.model_validate_json(receipt_path.read_bytes())
    if receipt.request_id != request_id:
        return None
    if receipt.digest != request_digest:
        raise CalibrationRequestReusedError("Save request ID was reused with different content")
    return Calibration(load_template_config(receipt.config), receipt.revision, receipt.main_photo)


def _renderer_settings(path: Path, current: AnyTemplate, config: AnyTemplate) -> bytes:
    """Every renderer's last settings, so switching renderer and back keeps
    them: the saved ones, then the current and the new renderer's."""
    settings = json.loads(path.read_bytes()) if path.is_file() else {}
    settings[current.renderer.type] = current.renderer.config.model_dump(mode="json")
    settings[config.renderer.type] = config.renderer.config.model_dump(mode="json")
    return json_bytes(settings)


def _checksum(path: Path, files: dict[Path, bytes]) -> str | None:
    """The digest of ``path`` as ``files`` is about to write it, else as it is
    on disk; None when there is neither."""
    data = files.get(path) if path in files else path.read_bytes() if path.is_file() else None
    return digest(data) if data is not None else None


class CalibrationStore:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    @contextmanager
    def lock(self, name: str, *more: str) -> Iterator[None]:
        """ADR-0054: the ``mockup-template`` domain of :mod:`.locks`, shared by
        calibration saves and map publication. An in-workspace alias shares
        its target's lock; one outside the workspace is refused."""
        with locks.hold(self.workspace, "mockup-template", name, *more):
            yield

    def state(self, name: str) -> TemplateState:
        """The owner's read (see :mod:`.template_state`): an interrupted
        transaction is rolled forward first, and one that cannot be trusted
        reads as needing repair."""
        with self.lock(name):
            try:
                self._recover(name)
            except CalibrationRepairRequiredError as exc:
                return TemplateNeedsRepair(str(exc))
            return template_state(self.workspace, name)

    def read(self, name: str) -> Calibration:
        """:meth:`state`'s config with its revision, which decodes the photo;
        the state's refusal when there is none."""
        with self.lock(name):
            config = self.state(name).require()
            return Calibration(
                config,
                self.revision(name, config),
                self.workspace.relative_path(self.workspace.template_main_photo(name, config)),
            )

    def save(
        self,
        name: str,
        config: AnyTemplate,
        *,
        expected_revision: str,
        request_id: str,
        mask_edits: list[MaskEdit] | None = None,
    ) -> Calibration:
        with self.lock(name):
            current = self.read(name)
            request_digest = digest(
                json_bytes(
                    {
                        "revision": expected_revision,
                        "config": dump_template_config(config),
                        "mask_edits": [edit.model_dump(mode="json") for edit in (mask_edits or [])],
                    }
                )
            )
            receipt_path = self.workspace.template_calibration_receipt(name)
            replayed = _replayed(receipt_path, request_id, request_digest)
            if replayed is not None:
                return replayed
            if current.revision != expected_revision:
                raise CalibrationChangedError("Calibration changed; reload before saving")
            # After the replay and revision checks: a retry answers as the
            # first save did, and a stale draft reloads before anything else.
            # The digest above stays the request's own, as it was sent.
            labels = saved_labels(config.labels, held=current.config.labels)
            config = config.model_copy(update={"labels": labels})
            files, histories = self.apply_masks(name, config, mask_edits or [])
            revision = self.revision(name, config, files)
            settings_path = self.workspace.template_renderer_settings_file(name)
            files[settings_path] = _renderer_settings(settings_path, current.config, config)
            receipt = SaveReceipt(
                request_id=request_id,
                digest=request_digest,
                revision=revision,
                config=dump_template_config(config),
                main_photo=current.main_photo,
            )
            self.commit(
                name,
                {
                    **files,
                    self.workspace.template_config_file(name): self.config_bytes(
                        name, config, before=current.config
                    ),
                    receipt_path: json_bytes(receipt.model_dump(mode="json")),
                },
            )
            # A crash after the durable commit may lose Undo, never the mask.
            for path, history in histories.items():
                write_json_atomic(path, history.model_dump(mode="json"))
            return self.read(name)

    def photo_identity(self, name: str, config: AnyTemplate) -> MainPhotoIdentity:
        path = self.workspace.template_main_photo(name, config)
        stamp = file_version(path)
        return _photo_identity(path.resolve(), stamp)

    def placement_ids(self, config: AnyTemplate) -> list[str | None]:
        return [p.id for p in config.placements] if isinstance(config, MultipleTemplate) else [None]

    def revision(
        self, name: str, config: AnyTemplate, files: dict[Path, bytes] | None = None
    ) -> str:
        files = files or {}
        masks = [
            {
                "id": placement_id,
                **{
                    source: _checksum(
                        self.workspace.template_mask_file(name, placement_id, source=source), files
                    )
                    for source in _MASKS
                },
            }
            for placement_id in sorted(self.placement_ids(config), key=lambda value: value or "")
        ]
        return digest(
            json_bytes(
                {
                    "config": dump_template_config(config),
                    "photo": self.photo_identity(name, config).model_dump(mode="json"),
                    "masks": masks,
                }
            )
        )

    def renderer_settings(self, name: str) -> dict[str, object]:
        with self.lock(name):
            current = self.read(name)
            path = self.workspace.template_renderer_settings_file(name)
            settings = json.loads(path.read_bytes()) if path.is_file() else {}
            settings[current.config.renderer.type] = current.config.renderer.config.model_dump(
                mode="json"
            )
            return settings

    def select_renderer(
        self,
        name: str,
        renderer_type: Literal["photo-warp", "marigold"],
        *,
        expected_revision: str,
        request_id: str,
    ) -> Calibration:
        """Restore the last saved settings; selection never prepares maps."""
        with self.lock(name):
            current = self.read(name)
            settings = self.renderer_settings(name)
            config = load_template_config(
                {
                    **dump_template_config(current.config),
                    "renderer": {"type": renderer_type, "config": settings.get(renderer_type, {})},
                }
            )
            return self.save(
                name, config, expected_revision=expected_revision, request_id=request_id
            )

    def mask(self, name: str, placement_id: str | None = None) -> SavedMask:
        with self.lock(name):
            # An observer's read: preparation inputs ask this from `plan`.
            config = template_state(self.workspace, name).require()
            if placement_id not in self.placement_ids(config):
                raise MaskUnavailableError("Mask placement does not belong to this template kind")
            paths = {
                source: self.workspace.template_mask_file(name, placement_id, source=source)
                for source in _MASK_FILES
            }
            if not all(path.is_file() for path in paths.values()):
                raise MaskUnavailableError(
                    "Prepare the template first to create its automatic mask"
                )
            automatic, edited = paths["automatic"].read_bytes(), paths["edited"].read_bytes()
            metadata = _mask_metadata(paths["metadata"])
            if metadata.photo != self.photo_identity(name, config):
                raise MaskPhotoMismatchError(
                    "Main photo changed; explicitly reset masks for this photo"
                )
            try:
                if metadata.automatic_checksum != digest(automatic) or (
                    metadata.edited_checksum != digest(edited)
                ):
                    _damaged("mask checksum mismatch")
                self.validate_mask(automatic, metadata.photo.size)
                self.validate_mask(edited, metadata.photo.size)
            except (OSError, ValueError) as exc:
                raise CalibrationRepairRequiredError(_DAMAGED_MASK) from exc
            history = self.history(name, placement_id, digest(edited))
            return SavedMask(automatic, edited, digest(edited), len(history))

    def history(self, name: str, placement_id: str | None, checksum: str) -> list[BrushStroke]:
        """The Undo steps cached for the edited mask ``checksum``; none when
        the cache is missing, damaged or belongs to another mask."""
        path = self.workspace.template_brush_history(name, placement_id)
        try:
            history = BrushHistory.model_validate_json(path.read_bytes())
        except (OSError, ValidationError):
            return []
        if history.checksum != checksum:
            return []
        config = template_state(self.workspace, name).config
        if config is None:
            return []
        try:
            size = self.photo_identity(name, config).size
            for entry in history.strokes:
                self.validate_mask(base64.b64decode(entry.before, validate=True), size)
        except (OSError, ValueError):
            return []
        return list(history.strokes)

    def validate_mask(self, data: bytes, size: tuple[int, int]) -> None:
        if len(data) <= 64 * 1024:
            _validate_mask(data, size)
        else:
            self.decode_mask(data, size)

    def decode_mask(self, data: bytes, size: tuple[int, int]) -> Image.Image:
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG" or image.mode != "L" or image.size != size:
                raise ValueError("Mask must be a full-photo grayscale PNG")
            image.load()
            return cast(Image.Image, image.copy())

    def encode_mask(self, image: Image.Image) -> bytes:
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def install_automatic(
        self,
        name: str,
        mask: AutomaticMask,
        *,
        expected_revision: str,
        reset_for_photo: bool = False,
        fresh: bool = False,
    ) -> Calibration:
        data, algorithm_version, placement_id = mask.data, mask.algorithm_version, mask.placement_id
        with self.lock(name):
            current = self.read(name)
            if current.revision != expected_revision:
                raise CalibrationChangedError(
                    "Calibration changed before automatic mask publication"
                )
            if placement_id not in self.placement_ids(current.config):
                raise MaskUnavailableError("Mask placement does not belong to this template kind")
            photo = self.photo_identity(name, current.config)
            self.decode_mask(data, photo.size)
            automatic_path = self.workspace.template_mask_file(
                name, placement_id, source="automatic"
            )
            if automatic_path.is_file():
                if self._keeps_saved_mask(
                    name, placement_id, fresh=fresh, reset_for_photo=reset_for_photo
                ):
                    return current
            elif any(
                self.workspace.template_mask_file(name, placement_id, source=source).exists()
                for source in _EDITED_FILES
            ):
                raise CalibrationRepairRequiredError(
                    "Automatic baseline is missing; repair it before rebuilding masks"
                )
            metadata = MaskMetadata(
                schema_version=1,
                photo=photo,
                algorithm_version=algorithm_version,
                automatic_checksum=digest(data),
                edited_checksum=digest(data),
            )
            self.commit(
                name,
                {
                    automatic_path: data,
                    self.workspace.template_mask_file(name, placement_id): data,
                    self.workspace.template_mask_file(
                        name, placement_id, source="metadata"
                    ): json_bytes(metadata.model_dump(mode="json")),
                },
            )
            self.workspace.template_brush_history(name, placement_id).unlink(missing_ok=True)
            return self.read(name)

    def _keeps_saved_mask(
        self, name: str, placement_id: str | None, *, fresh: bool, reset_for_photo: bool
    ) -> bool:
        """Whether a saved automatic mask stands rather than being replaced: it
        does unless ``fresh`` asks for a rebuild of one nobody has edited. A
        mask for another photo is replaced only with ``reset_for_photo``."""
        try:
            saved_mask = self.mask(name, placement_id)
        except MaskUnavailableError:
            if not reset_for_photo:
                raise
            return False
        return not fresh or saved_mask.automatic != saved_mask.edited

    def apply_masks(
        self, name: str, config: AnyTemplate, edits: list[MaskEdit]
    ) -> tuple[dict[Path, bytes], dict[Path, BrushHistory]]:
        files: dict[Path, bytes] = {}
        histories: dict[Path, BrushHistory] = {}
        if len(json_bytes([edit.model_dump(mode="json") for edit in edits])) > MAX_MASK_EDIT_BYTES:
            raise MaskEditRefusedError("Mask edit request is too large")
        ids = [edit.placement_id for edit in edits]
        if len(ids) != len(set(ids)):
            raise MaskEditRefusedError("Only one mask edit entry per placement is allowed")
        for edit in edits:
            if edit.placement_id not in self.placement_ids(config):
                raise MaskUnavailableError("Mask placement does not belong to saved template")
            edited, history = self._apply_edit(name, edit)
            files |= edited
            histories[self.workspace.template_brush_history(name, edit.placement_id)] = history
        return files, histories

    def _apply_edit(self, name: str, edit: MaskEdit) -> tuple[dict[Path, bytes], BrushHistory]:
        """One placement's edited mask and metadata files, and its new brush
        history."""
        mask = self.mask(name, edit.placement_id)
        history = self.history(name, edit.placement_id, mask.checksum)
        metadata_path = self.workspace.template_mask_file(
            name, edit.placement_id, source="metadata"
        )
        metadata = _mask_metadata(metadata_path)
        size = metadata.photo.size
        data = mask.edited
        for operation in edit.operations:
            if isinstance(operation, Reset):
                data, history = mask.automatic, []
            elif isinstance(operation, Undo):
                data = self._undone(history, size)
            else:
                data = self._stroked(data, operation, history, size)
        metadata = metadata.model_copy(update={"edited_checksum": digest(data)})
        files = {
            self.workspace.template_mask_file(name, edit.placement_id): data,
            metadata_path: json_bytes(metadata.model_dump(mode="json")),
        }
        return files, BrushHistory(checksum=digest(data), strokes=tuple(history))

    def _undone(self, history: list[BrushStroke], size: tuple[int, int]) -> bytes:
        """The mask before the last stroke, popped off ``history``."""
        if not history:
            raise MaskUnavailableError("Undo brush stroke unavailable; cached history was lost")
        data = base64.b64decode(history.pop().before, validate=True)
        self.decode_mask(data, size)
        return data

    def _stroked(
        self, data: bytes, stroke: Stroke, history: list[BrushStroke], size: tuple[int, int]
    ) -> bytes:
        """``data`` with ``stroke`` painted on, recorded in ``history``."""
        image = self.decode_mask(data, size)
        if any(x < 0 or y < 0 or x >= image.width or y >= image.height for x, y in stroke.points):
            raise MaskEditRefusedError("Brush coordinates must be within the main photo")
        history.append(BrushStroke(before=base64.b64encode(data).decode("ascii"), operation=stroke))
        draw = ImageDraw.Draw(image)
        fill = 0 if stroke.mode == "mask" else 255
        radius = stroke.diameter_px / 2
        draw.line(stroke.points, fill=fill, width=max(1, round(stroke.diameter_px)))
        for x, y in stroke.points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
        return self.encode_mask(image)

    def write_config(self, name: str, config: AnyTemplate) -> None:
        """Initial assignment and trusted local writers still use recovery storage."""
        with self.lock(name):
            self.workspace.template_dir(name).mkdir(parents=True, exist_ok=True)
            state = self.state(name)
            old = None if isinstance(state, TemplateAbsent) else state.require()
            path = self.workspace.template_renderer_settings_file(name)
            settings = json.loads(path.read_bytes()) if path.is_file() else {}
            config_path = self.workspace.template_config_file(name)
            if old is not None:
                settings[old.renderer.type] = old.renderer.config.model_dump(mode="json")
            settings[config.renderer.type] = config.renderer.config.model_dump(mode="json")
            self.commit(
                name,
                {
                    config_path: self.config_bytes(name, config, before=old),
                    path: json_bytes(settings),
                },
            )

    def config_bytes(self, name: str, config: AnyTemplate, *, before: AnyTemplate | None) -> bytes:
        """``template.yaml`` as it should be once ``config`` is saved.

        A new file is the full dump. An existing one keeps the seller's text
        and gains only what differs between ``before``, the config it holds,
        and ``config`` (ADR-0055); when nothing does, the bytes are the
        current ones, and commit recovery's checksum leaves the file alone."""
        path = self.workspace.template_config_file(name)
        dumped = dump_template_config(config)
        if before is None or not path.is_file():
            return yaml.safe_dump(dumped, sort_keys=False).encode("utf-8")
        return edit_yaml_bytes(path.read_bytes(), dumped, before=dump_template_config(before))

    def write_durable(self, path: Path, data: bytes) -> None:
        write_bytes_atomic(path, data, durable=True)

    def write_manifest(self, path: Path, manifest: TransactionManifest) -> None:
        self.write_durable(path, json_bytes(manifest.model_dump(mode="json")))

    def commit(self, name: str, files: dict[Path, bytes]) -> None:
        """Stage all payloads and backups before durable intent. ADR-0054.

        After intent, recovery rolls forward. Payloads remain until every
        destination is verified; an ordinary sequence of renames is insufficient.
        """

        with self.lock(name):
            self._recover(name)
            transaction = self.workspace.template_calibration_transaction(name)
            transaction.mkdir(parents=True)
            entries = []
            for index, (path, data) in enumerate(files.items()):
                relative = path.relative_to(self.workspace.template_dir(name)).as_posix()
                payload = f"payload-{index}"
                self.write_durable(transaction / payload, data)
                backup = f"backup-{index}"
                if path.is_file():
                    self.write_durable(transaction / backup, path.read_bytes())
                entries.append(
                    StagedFile(
                        destination=relative, payload=payload, checksum=digest(data), backup=backup
                    )
                )
            self.write_manifest(
                transaction / "manifest.json",
                TransactionManifest(schema_version=1, commit_intent=True, files=tuple(entries)),
            )
            self._recover(name)
            if transaction.exists():
                remove_tree(transaction)

    def _staged_payload(
        self, name: str, transaction: Path, entry: StagedFile
    ) -> tuple[Path, bytes, str]:
        """One manifest entry's destination, payload and checksum, each path
        confined to its directory and the payload checked against it."""
        target = self.workspace.resolve(entry.destination, self.workspace.template_dir(name))
        target.relative_to(self.workspace.template_dir(name).resolve())
        payload = self.workspace.resolve(entry.payload, transaction)
        payload.relative_to(transaction.resolve())
        data = payload.read_bytes()
        if digest(data) != entry.checksum:
            _damaged("transaction checksum mismatch")
        return target, data, entry.checksum

    def _roll_forward(self, target: Path, data: bytes, checksum: str) -> None:
        if not target.is_file() or digest(target.read_bytes()) != checksum:
            self.write_durable(target, data)
        if digest(target.read_bytes()) != checksum:
            raise CalibrationRepairRequiredError("Calibration transaction verification failed")

    def _recover(self, name: str) -> None:
        """Server-side recovery, always under the shared template lock."""

        with self.lock(name):
            transaction = self.workspace.template_calibration_transaction(name)
            if not transaction.exists():
                return
            manifest_path = transaction / "manifest.json"
            if not manifest_path.is_file():
                remove_tree(transaction)
                return

            # A ValidationError is a ValueError: an unreadable manifest, an
            # escaping path and a payload checksum all need the same repair.
            try:
                manifest = TransactionManifest.model_validate_json(manifest_path.read_bytes())
                if not manifest.commit_intent:
                    remove_tree(transaction)
                    return
                payloads = [
                    self._staged_payload(name, transaction, entry) for entry in manifest.files
                ]
            except (OSError, ValueError) as exc:
                raise CalibrationRepairRequiredError(
                    "Damaged calibration transaction; repair saved recovery payloads"
                ) from exc
            # Validate the whole set before replacing even one destination.
            for target, data, checksum in payloads:
                self._roll_forward(target, data, checksum)
            self.write_manifest(manifest_path, manifest.model_copy(update={"complete": True}))
            remove_tree(transaction)
