"""Revision-bound transient composites; never publish maps or select models."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from PIL import Image

from etsy_listings.core.application.preparation.activity import interactive
from etsy_listings.core.application.preparation.evidence_reader import EvidenceReader
from etsy_listings.core.application.preparation.models import CropEvidence, placement_key
from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.preparation.artifacts import Artifacts, PlacementInput
from etsy_listings.core.preparation.numerics import Placement, prepare
from etsy_listings.core.render import (
    AnyTemplate,
    BoundingBox,
    MarigoldRenderer,
    MaterialLayer,
    MaterialMaps,
    MultipleTemplate,
    PreparationRequiredError,
    render_marigold_scene,
)
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import Calibration, CalibrationStore, MaskEdit

EDITOR_EDGE = 1024
EDITOR_ARTWORK_EDGE = 3072


def _maps_bytes(value: MaterialMaps) -> int:
    return sum(a.nbytes for a in vars(value).values() if isinstance(a, np.ndarray))


_MAP_CACHE: BoundedCache[tuple[str, ...], MaterialMaps] = BoundedCache(
    64 * 1024 * 1024, size=_maps_bytes
)


def _maps(key: tuple[str, ...], compute: Callable[[], MaterialMaps]) -> MaterialMaps:
    def frozen() -> MaterialMaps:
        value = compute()
        for array in vars(value).values():
            if isinstance(array, np.ndarray):
                array.flags.writeable = False
        return value

    return _MAP_CACHE.get_or_compute(key, frozen)


@dataclass(frozen=True)
class EditorDraft:
    """The calibrator's unsaved state: its geometry, the calibration
    ``revision`` it was drawn against, mask strokes not yet saved, and the
    colour-matrix photo it shows (``None`` for other kinds)."""

    config: AnyTemplate
    revision: str
    mask_edits: list[MaskEdit]
    colour: str | None = None


def _previewable_renderer(saved: Calibration, draft: EditorDraft) -> MarigoldRenderer:
    """The draft's Marigold renderer; refuses a draft the saved calibration
    has moved past, or one whose renderer or inference is not yet saved."""
    config = draft.config
    if saved.revision != draft.revision:
        raise PreparationRequiredError("Calibration changed; refresh the editor preview")
    if config.kind != saved.config.kind or not isinstance(config.renderer, MarigoldRenderer):
        raise PreparationRequiredError("Save the renderer selection before previewing")
    if (
        not isinstance(saved.config.renderer, MarigoldRenderer)
        or config.renderer.config.inference != saved.config.renderer.config.inference
    ):
        raise PreparationRequiredError("Prepare changed inference settings before previewing")
    return config.renderer


def _boxes(config: AnyTemplate) -> list[tuple[str | None, BoundingBox]]:
    if isinstance(config, MultipleTemplate):
        return [(p.id, p.bounding_box) for p in config.placements]
    return [(None, config.bounding_box)]


def _composite_target(
    workspace: Workspace,
    name: str,
    draft: EditorDraft,
    image: RGB,
    base: Callable[[Path], RGB],
) -> RGB:
    """The composite background. Shared maps are fitted against the fixed main
    photo ``image``; only this background follows the editor's colour."""
    target = (
        base(workspace.template_base_image(name, draft.colour))
        if draft.config.kind == "colour-matrix" and draft.colour is not None
        else image
    )
    if target.shape != image.shape:
        raise PreparationRequiredError("Colour photos must match the main photo dimensions")
    return target


def editor_preview(
    workspace: Workspace,
    name: str,
    draft: EditorDraft,
    *,
    base: Callable[[Path], RGB],
    artwork: Callable[[], tuple[RGBA, FloatMap]],
) -> Image.Image:
    """Fit original coordinates, rasterize a disposable 1024px editor image.

    Draft masks replay against exactly the client's acknowledged revision. A
    save racing this request cannot apply a stroke twice. The snapshot leaves
    the lock before fitting; the host/client must discard superseded responses.
    No generation pointer, history, PNG or approval identity is written.
    """
    config, revision, mask_edits = draft.config, draft.revision, draft.mask_edits
    with interactive(workspace):
        store = CalibrationStore(workspace)
        evidence_store = EvidenceReader(workspace)
        with store.lock(name):
            saved = store.read(name)
            renderer = _previewable_renderer(saved, draft)
            original = Artifacts(workspace).saved_inputs(name)
            boxes = _boxes(config)
            inputs = original.model_copy(
                update={
                    "placements": tuple(
                        PlacementInput.from_box(
                            key,
                            box,
                            mask="0" * 64,
                            evidence="0" * 64,
                        )
                        for key, box in boxes
                    )
                }
            )
            Artifacts(workspace).validate_inputs(inputs)
            selected = evidence_store.select(inputs, evidence_store.current(name))
            if len(selected) != len(boxes):
                raise PreparationRequiredError("Prepare the template to cover this placement")
            files, _ = store.apply_masks(name, config, mask_edits)
            size = (original.photo.width, original.photo.height)
            mask_bytes = {
                key: files.get(workspace.template_mask_file(name, key))
                or store.mask(name, key).edited
                for key, _ in boxes
            }
            masks = {
                key: np.asarray(
                    store.decode_mask(
                        mask_bytes[key],
                        size,
                    ),
                    dtype=np.float32,
                )
                / np.float32(255)
                for key, _ in boxes
            }
            image = base(workspace.template_main_photo(name, saved.config))
            target = _composite_target(workspace, name, draft, image, base)
            design, packed = artwork()
        layers = []
        for key, box in boxes:
            candidate = selected[placement_key(key)]
            quad = np.array([(p.x, p.y) for p in box], np.float32)
            cache_key = (
                original.photo.model_dump_json(),
                candidate.model_dump_json(exclude={"id"}),
                hashlib.sha256(quad.tobytes()).hexdigest(),
                hashlib.sha256(mask_bytes[key]).hexdigest(),
            )

            def compute(
                candidate: CropEvidence = candidate,
                quad: FloatMap = quad,
                mask: FloatMap = masks[key],
            ) -> MaterialMaps:
                evidence = evidence_store.load(candidate, inputs)
                return prepare(image, Placement(quad, mask), evidence, max_edge=EDITOR_EDGE).maps

            layers.append(
                MaterialLayer(design, _maps(cache_key, compute), key, premultiplied=packed)
            )

        width, height = layers[0].maps.size
        small = cast(RGB, cv2.resize(target, (width, height), interpolation=cv2.INTER_AREA))
        result = render_marigold_scene(small, layers, appearance=renderer.config.appearance)
        with store.lock(name):
            if store.read(name).revision != revision:
                raise PreparationRequiredError("Calibration changed during the editor preview")
        return result
