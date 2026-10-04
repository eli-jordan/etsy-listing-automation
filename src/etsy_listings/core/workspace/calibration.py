"""Durable calibration documents and mask edits, protected by template locks.

ADR-0053: revision tokens protect editor saves; they are not render hashes.
Import this module directly. Its storage implementation is not re-exported.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

import yaml
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.render.config import (
    AnyTemplate,
    MultipleTemplate,
    PlacementId,
    dump_template_config,
    load_template_config,
)
from etsy_listings.core.workspace.atomic import write_bytes_atomic, write_json_atomic

if TYPE_CHECKING:
    from etsy_listings.core.workspace import Workspace

_GUARD = threading.Lock()
_LOCKS: dict[tuple[str, str], threading.RLock] = {}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class CalibrationRepairRequired(UserFacingError):
    """A calibration transaction is active or its recovery payload is damaged."""


class CalibrationConflict(UserFacingError):
    """The supplied revision or save request ID cannot be accepted."""


class MaskUnavailable(UserFacingError):
    """Mask editing or Undo has no usable saved baseline/history."""


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


class CalibrationStore:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    @contextmanager
    def lock(self, name: str) -> Iterator[None]:
        directory = self.workspace.template_dir(name)
        self.workspace.resolve(
            directory.relative_to(self.workspace.root).as_posix(), self.workspace.root
        )
        key = (str(self.workspace.root.resolve()).casefold(), name.casefold())
        with _GUARD:
            lock = _LOCKS.setdefault(key, threading.RLock())
        with lock:
            yield

    def config(self, name: str) -> AnyTemplate:
        """Recover and load under the lock without decoding a photo for a revision."""
        with self.lock(name):
            self.recover(name)
            return self.workspace.load_template_config(name)

    def read(self, name: str) -> Calibration:
        with self.lock(name):
            self.recover(name)
            config = self.workspace.load_template_config(name)
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
            if receipt_path.is_file():
                receipt = json.loads(receipt_path.read_bytes())
                if receipt["request_id"] == request_id:
                    if receipt["digest"] != request_digest:
                        raise CalibrationConflict(
                            "Save request ID was reused with different content"
                        )
                    return Calibration(
                        load_template_config(receipt["config"]),
                        receipt["revision"],
                        receipt["main_photo"],
                    )
            if current.revision != expected_revision:
                raise CalibrationConflict("Calibration changed; reload before saving")
            files, histories = self.apply_masks(name, config, mask_edits or [])
            revision = self.revision(name, config, files)
            settings_path = self.workspace.template_renderer_settings_file(name)
            settings = json.loads(settings_path.read_bytes()) if settings_path.is_file() else {}
            settings[current.config.renderer.type] = current.config.renderer.config.model_dump(
                mode="json"
            )
            settings[config.renderer.type] = config.renderer.config.model_dump(mode="json")
            files[settings_path] = json_bytes(settings)
            receipt = {
                "request_id": request_id,
                "digest": request_digest,
                "revision": revision,
                "config": dump_template_config(config),
                "main_photo": current.main_photo,
            }
            self.commit(
                name,
                {
                    **files,
                    self.workspace.template_config_file(name): yaml.safe_dump(
                        dump_template_config(config), sort_keys=False
                    ).encode("utf-8"),
                    receipt_path: json_bytes(receipt),
                },
            )
            # A crash after the durable commit may lose Undo, never the mask.
            for path, history in histories.items():
                write_json_atomic(path, history)
            return self.read(name)

    def photo_identity(self, name: str, config: AnyTemplate) -> dict[str, Any]:
        path = self.workspace.template_main_photo(name, config)
        with Image.open(path) as image:
            pixels = image.convert("RGB")
            return {
                "file": path.name,
                "width": pixels.width,
                "height": pixels.height,
                "conversion": "pillow-rgb-v1",
                "pixels": digest(pixels.tobytes()),
            }

    def placement_ids(self, config: AnyTemplate) -> list[str | None]:
        return [p.id for p in config.placements] if isinstance(config, MultipleTemplate) else [None]

    def revision(
        self, name: str, config: AnyTemplate, files: dict[Path, bytes] | None = None
    ) -> str:
        files = files or {}
        masks = []
        for placement_id in sorted(self.placement_ids(config), key=lambda value: value or ""):
            checksums = {}
            for source in ("automatic", "edited"):
                path = self.workspace.template_mask_file(name, placement_id, source=source)
                data = (
                    files.get(path)
                    if path in files
                    else path.read_bytes()
                    if path.is_file()
                    else None
                )
                checksums[source] = digest(data) if data is not None else None
            masks.append({"id": placement_id, **checksums})
        return digest(
            json_bytes(
                {
                    "config": dump_template_config(config),
                    "photo": self.photo_identity(name, config),
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
            calibration = self.read(name)
            if placement_id not in self.placement_ids(calibration.config):
                raise MaskUnavailable("Mask placement does not belong to this template kind")
            paths = {
                source: self.workspace.template_mask_file(name, placement_id, source=source)
                for source in ("automatic", "edited", "metadata")
            }
            if not all(path.is_file() for path in paths.values()):
                raise MaskUnavailable("Prepare the template first to create its automatic mask")
            automatic, edited = paths["automatic"].read_bytes(), paths["edited"].read_bytes()
            try:
                metadata = json.loads(paths["metadata"].read_bytes())
                if metadata["schema_version"] != 1:
                    raise ValueError("unsupported mask metadata schema")
                if metadata["photo"] != self.photo_identity(name, calibration.config):
                    raise MaskUnavailable(
                        "Main photo changed; explicitly reset masks for this photo"
                    )
                if metadata["automatic_checksum"] != digest(automatic) or metadata[
                    "edited_checksum"
                ] != digest(edited):
                    raise ValueError("mask checksum mismatch")
                self.decode_mask(automatic, metadata["photo"])
                self.decode_mask(edited, metadata["photo"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise CalibrationRepairRequired(
                    "Saved mask is damaged; repair or explicitly reset its baseline"
                ) from exc
            history = self.history(name, placement_id, digest(edited))
            return SavedMask(automatic, edited, digest(edited), len(history))

    def history(self, name: str, placement_id: str | None, checksum: str) -> list[dict[str, Any]]:
        path = self.workspace.template_brush_history(name, placement_id)
        try:
            history = json.loads(path.read_bytes())
            if history["checksum"] != checksum or not isinstance(history["strokes"], list):
                return []
            photo = self.photo_identity(name, self.workspace.load_template_config(name))
            for entry in history["strokes"]:
                Stroke.model_validate(entry["operation"])
                self.decode_mask(base64.b64decode(entry["before"], validate=True), photo)
            return cast(list[dict[str, Any]], history["strokes"])
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def decode_mask(self, data: bytes, photo: dict[str, Any]) -> Image.Image:
        with Image.open(BytesIO(data)) as image:
            if (
                image.format != "PNG"
                or image.mode != "L"
                or image.size != (photo["width"], photo["height"])
            ):
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
        data: bytes,
        *,
        algorithm_version: str,
        expected_revision: str,
        placement_id: str | None = None,
        reset_for_photo: bool = False,
        fresh: bool = False,
    ) -> Calibration:
        with self.lock(name):
            current = self.read(name)
            if current.revision != expected_revision:
                raise CalibrationConflict("Calibration changed before automatic mask publication")
            if placement_id not in self.placement_ids(current.config):
                raise MaskUnavailable("Mask placement does not belong to this template kind")
            photo = self.photo_identity(name, current.config)
            self.decode_mask(data, photo)
            automatic_path = self.workspace.template_mask_file(
                name, placement_id, source="automatic"
            )
            if not automatic_path.is_file() and any(
                self.workspace.template_mask_file(name, placement_id, source=source).exists()
                for source in ("edited", "metadata")
            ):
                raise CalibrationRepairRequired(
                    "Automatic baseline is missing; repair it before rebuilding masks"
                )
            if automatic_path.is_file():
                try:
                    saved_mask = self.mask(name, placement_id)
                    if not fresh or saved_mask.automatic != saved_mask.edited:
                        return current
                except MaskUnavailable:
                    if not reset_for_photo:
                        raise
            metadata = {
                "schema_version": 1,
                "photo": photo,
                "algorithm_version": algorithm_version,
                "automatic_checksum": digest(data),
                "edited_checksum": digest(data),
            }
            self.commit(
                name,
                {
                    automatic_path: data,
                    self.workspace.template_mask_file(name, placement_id): data,
                    self.workspace.template_mask_file(
                        name, placement_id, source="metadata"
                    ): json_bytes(metadata),
                },
            )
            self.workspace.template_brush_history(name, placement_id).unlink(missing_ok=True)
            return self.read(name)

    def apply_masks(
        self, name: str, config: AnyTemplate, edits: list[MaskEdit]
    ) -> tuple[dict[Path, bytes], dict[Path, object]]:
        files: dict[Path, bytes] = {}
        histories: dict[Path, object] = {}
        if len(json_bytes([edit.model_dump(mode="json") for edit in edits])) > 2_000_000:
            raise ValueError("Mask edit request is too large")
        ids = [edit.placement_id for edit in edits]
        if len(ids) != len(set(ids)):
            raise ValueError("Only one mask edit entry per placement is allowed")
        for edit in edits:
            if edit.placement_id not in self.placement_ids(config):
                raise MaskUnavailable("Mask placement does not belong to saved template")
            mask = self.mask(name, edit.placement_id)
            history = self.history(name, edit.placement_id, mask.checksum)
            metadata_path = self.workspace.template_mask_file(
                name, edit.placement_id, source="metadata"
            )
            metadata = json.loads(metadata_path.read_bytes())
            data = mask.edited
            for operation in edit.operations:
                if isinstance(operation, Reset):
                    data, history = mask.automatic, []
                elif isinstance(operation, Undo):
                    if not history:
                        raise MaskUnavailable(
                            "Undo brush stroke unavailable; cached history was lost"
                        )
                    data = base64.b64decode(history.pop()["before"], validate=True)
                    self.decode_mask(data, metadata["photo"])
                else:
                    image = self.decode_mask(data, metadata["photo"])
                    if any(
                        x < 0 or y < 0 or x >= image.width or y >= image.height
                        for x, y in operation.points
                    ):
                        raise ValueError("Brush coordinates must be within the main photo")
                    history.append(
                        {
                            "before": base64.b64encode(data).decode("ascii"),
                            "operation": operation.model_dump(mode="json"),
                        }
                    )
                    draw = ImageDraw.Draw(image)
                    fill = 0 if operation.mode == "mask" else 255
                    radius = operation.diameter_px / 2
                    draw.line(
                        operation.points, fill=fill, width=max(1, round(operation.diameter_px))
                    )
                    for x, y in operation.points:
                        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
                    data = self.encode_mask(image)
            metadata["edited_checksum"] = digest(data)
            files[self.workspace.template_mask_file(name, edit.placement_id)] = data
            files[metadata_path] = json_bytes(metadata)
            histories[self.workspace.template_brush_history(name, edit.placement_id)] = {
                "checksum": digest(data),
                "strokes": history,
            }
        return files, histories

    def write_config(self, name: str, config: AnyTemplate) -> None:
        """Initial assignment and trusted local writers still use recovery storage."""
        with self.lock(name):
            self.workspace.template_dir(name).mkdir(parents=True, exist_ok=True)
            self.recover(name)
            path = self.workspace.template_renderer_settings_file(name)
            settings = json.loads(path.read_bytes()) if path.is_file() else {}
            config_path = self.workspace.template_config_file(name)
            if config_path.is_file():
                old = self.workspace.load_template_config(name)
                settings[old.renderer.type] = old.renderer.config.model_dump(mode="json")
            settings[config.renderer.type] = config.renderer.config.model_dump(mode="json")
            self.commit(
                name,
                {
                    config_path: yaml.safe_dump(
                        dump_template_config(config), sort_keys=False
                    ).encode("utf-8"),
                    path: json_bytes(settings),
                },
            )

    def write_durable(self, path: Path, data: bytes) -> None:
        write_bytes_atomic(path, data, durable=True)

    def write_durable_json(self, path: Path, value: object) -> None:
        self.write_durable(path, json_bytes(value))

    def commit(self, name: str, files: dict[Path, bytes]) -> None:
        """Stage all payloads and backups before durable intent. ADR-0053.

        After intent, recovery rolls forward. Payloads remain until every
        destination is verified; an ordinary sequence of renames is insufficient.
        """
        from etsy_listings.core.workspace.workspace import remove_tree

        with self.lock(name):
            self.recover(name)
            transaction = self.workspace.template_calibration_transaction(name)
            transaction.mkdir()
            entries = []
            for index, (path, data) in enumerate(files.items()):
                relative = path.relative_to(self.workspace.template_dir(name)).as_posix()
                payload = f"payload-{index}"
                self.write_durable(transaction / payload, data)
                backup = f"backup-{index}"
                if path.is_file():
                    self.write_durable(transaction / backup, path.read_bytes())
                entries.append(
                    {
                        "destination": relative,
                        "payload": payload,
                        "checksum": digest(data),
                        "backup": backup,
                    }
                )
            self.write_durable_json(
                transaction / "manifest.json",
                {"schema_version": 1, "commit_intent": True, "files": entries},
            )
            self.recover(name)
            if transaction.exists():
                remove_tree(transaction)

    def recover(self, name: str) -> None:
        """Server-side recovery, always under the shared template lock."""
        from etsy_listings.core.workspace.workspace import remove_tree

        with self.lock(name):
            transaction = self.workspace.template_calibration_transaction(name)
            if not transaction.exists():
                return
            manifest_path = transaction / "manifest.json"
            if not manifest_path.is_file():
                remove_tree(transaction)
                return
            try:
                manifest = json.loads(manifest_path.read_bytes())
                if manifest["schema_version"] != 1:
                    raise ValueError("unsupported transaction schema")
                if not manifest.get("commit_intent"):
                    remove_tree(transaction)
                    return
                payloads = []
                for entry in manifest["files"]:
                    target = self.workspace.resolve(
                        entry["destination"], self.workspace.template_dir(name)
                    )
                    target.relative_to(self.workspace.template_dir(name).resolve())
                    payload = self.workspace.resolve(entry["payload"], transaction)
                    payload.relative_to(transaction.resolve())
                    data = payload.read_bytes()
                    if digest(data) != entry["checksum"]:
                        raise ValueError("transaction checksum mismatch")
                    payloads.append((target, data, entry["checksum"]))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise CalibrationRepairRequired(
                    "Damaged calibration transaction; repair saved recovery payloads"
                ) from exc
            # Validate the whole set before replacing even one destination.
            for target, data, checksum in payloads:
                if not target.is_file() or digest(target.read_bytes()) != checksum:
                    self.write_durable(target, data)
                if digest(target.read_bytes()) != checksum:
                    raise CalibrationRepairRequired("Calibration transaction verification failed")
            self.write_durable_json(manifest_path, {**manifest, "complete": True})
            remove_tree(transaction)
