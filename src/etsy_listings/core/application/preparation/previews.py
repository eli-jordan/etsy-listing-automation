import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from PIL import Image

from etsy_listings.core.application.preparation.activity import interactive
from etsy_listings.core.application.preparation.draft_rules import (
    EditorDraft,
    drawn_against,
    placement_boxes,
    previewable_renderer,
)
from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.preparation.artifacts import Artifacts, PlacementInput
from etsy_listings.core.preparation.evidence_reader import (
    CropEvidence,
    EvidenceReader,
    placement_key,
)
from etsy_listings.core.preparation.numerics import Placement, prepare
from etsy_listings.core.render import (
    MaterialLayer,
    MaterialMaps,
    PreparationRequiredError,
    render_marigold_scene,
)
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore

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


def _composite_target(
    workspace: Workspace,
    name: str,
    draft: EditorDraft,
    image: RGB,
    base: Callable[[Path], RGB],
) -> RGB:
    """Maps are fitted to the main photo; only the background follows the colour."""
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
    """The snapshot leaves the lock before fitting: the client must discard superseded responses."""
    config, mask_edits = draft.config, draft.mask_edits
    with interactive(workspace):
        store = CalibrationStore(workspace)
        evidence_store = EvidenceReader(workspace)
        with store.lock(name):
            saved = store.read(name)
            renderer = previewable_renderer(store, name, saved, draft)
            original = Artifacts(workspace).saved_inputs(name)
            boxes = placement_boxes(config)
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
            if not drawn_against(store, name, store.read(name), draft):
                raise PreparationRequiredError("Calibration changed during the editor preview")
        return result
