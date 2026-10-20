"""Revision-bound transient composites; never publish maps or select models."""

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from PIL import Image

from etsy_listings.core.application.preparation.activity import interactive
from etsy_listings.core.application.preparation.evidence_reader import EvidenceReader
from etsy_listings.core.application.preparation.models import CropEvidence, placement_key
from etsy_listings.core.preparation.artifacts import Artifacts, PlacementInput
from etsy_listings.core.preparation.numerics import prepare
from etsy_listings.core.render import (
    AnyTemplate,
    MarigoldRenderer,
    MaterialLayer,
    MaterialMaps,
    MultipleTemplate,
    PreparationRequired,
    render_marigold_scene,
)
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore, MaskEdit

EDITOR_EDGE = 256
_MAP_BUDGET = 64 * 1024 * 1024
_MAP_LOCK = threading.Lock()
_MAP_CACHE: OrderedDict[tuple[str, ...], tuple[MaterialMaps, int]] = OrderedDict()
_MAP_BYTES = 0


def _maps(key: tuple[str, ...], compute: Callable[[], MaterialMaps]) -> MaterialMaps:
    global _MAP_BYTES
    with _MAP_LOCK:
        cached = _MAP_CACHE.get(key)
        if cached is not None:
            _MAP_CACHE.move_to_end(key)
            return cached[0]
    value = compute()
    arrays = [a for a in vars(value).values() if isinstance(a, np.ndarray)]
    size = sum(a.nbytes for a in arrays)
    for array in arrays:
        array.flags.writeable = False
    with _MAP_LOCK:
        old = _MAP_CACHE.pop(key, None)
        if old is not None:
            _MAP_BYTES -= old[1]
        while _MAP_CACHE and _MAP_BYTES + size > _MAP_BUDGET:
            _, (_, removed) = _MAP_CACHE.popitem(last=False)
            _MAP_BYTES -= removed
        if size <= _MAP_BUDGET:
            _MAP_CACHE[key] = value, size
            _MAP_BYTES += size
    return value


def editor_preview(
    workspace: Workspace,
    name: str,
    *,
    config: AnyTemplate,
    revision: str,
    mask_edits: list[MaskEdit],
    base: Callable[[Path], RGB],
    artwork: Callable[[], RGBA],
    colour: str | None = None,
) -> Image.Image:
    """Fit original coordinates, rasterize a small disposable editor image.

    Draft masks replay against exactly the client's acknowledged revision. A
    save racing this request cannot apply a stroke twice. The snapshot leaves
    the lock before fitting; the host/client must discard superseded responses.
    No generation pointer, history, PNG or approval identity is written.
    """
    with interactive(workspace):
        store = CalibrationStore(workspace)
        evidence_store = EvidenceReader(workspace)
        with store.lock(name):
            saved = store.read(name)
            if saved.revision != revision:
                raise PreparationRequired("Calibration changed; refresh the editor preview")
            if config.kind != saved.config.kind or not isinstance(
                config.renderer, MarigoldRenderer
            ):
                raise PreparationRequired("Save the renderer selection before previewing")
            if (
                not isinstance(saved.config.renderer, MarigoldRenderer)
                or config.renderer.config.inference != saved.config.renderer.config.inference
            ):
                raise PreparationRequired("Prepare changed inference settings before previewing")
            original = Artifacts(workspace).saved_inputs(name)
            boxes = (
                [(p.id, p.bounding_box) for p in config.placements]
                if isinstance(config, MultipleTemplate)
                else [(None, config.bounding_box)]
            )
            inputs = original.model_copy(
                update={
                    "placements": tuple(
                        PlacementInput(
                            id=key,
                            quad=(
                                (box[0].x, box[0].y),
                                (box[1].x, box[1].y),
                                (box[2].x, box[2].y),
                                (box[3].x, box[3].y),
                            ),
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
                raise PreparationRequired("Prepare the template to cover this placement")
            files, _ = store.apply_masks(name, config, mask_edits)
            photo = original.photo.model_dump()
            mask_bytes = {
                key: files.get(workspace.template_mask_file(name, key))
                or store.mask(name, key).edited
                for key, _ in boxes
            }
            masks = {
                key: np.asarray(
                    store.decode_mask(
                        mask_bytes[key],
                        photo,
                    ),
                    dtype=np.float32,
                )
                / np.float32(255)
                for key, _ in boxes
            }
            image = base(workspace.template_main_photo(name, saved.config))
            # Fit shared maps against the fixed main photo. Only the final
            # composite background follows the editor's colour selection.
            target = (
                base(workspace.template_base_image(name, colour))
                if config.kind == "colour-matrix" and colour is not None
                else image
            )
            if target.shape != image.shape:
                raise PreparationRequired("Colour photos must match the main photo dimensions")
            design = artwork()
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
                return prepare(image, quad, evidence, mask=mask, max_edge=EDITOR_EDGE).maps

            layers.append(MaterialLayer(design, _maps(cache_key, compute), key))

        width, height = layers[0].maps.size
        small = cast(RGB, cv2.resize(target, (width, height), interpolation=cv2.INTER_AREA))
        result = render_marigold_scene(small, layers, appearance=config.renderer.config.appearance)
        with store.lock(name):
            if store.read(name).revision != revision:
                raise PreparationRequired("Calibration changed during the editor preview")
        return result
