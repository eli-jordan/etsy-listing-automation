"""Pure authoring preparation. Crop and fitting never touch a workspace."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np

from etsy_listings.core.preparation import _geometry as geometry
from etsy_listings.core.render import _material_math as material_math
from etsy_listings.core.render.material import MaterialMaps
from etsy_listings.core.render.types import RGB, FloatMap


@dataclass(frozen=True)
class Crop:
    rectangle: tuple[int, int, int, int]
    photo_size: tuple[int, int]
    prediction_size: tuple[int, int]
    photo_to_prediction: tuple[float, float, float, float]
    padding: tuple[int, int, int, int] = (0, 0, 0, 0)

    def __post_init__(self) -> None:
        left, top, right, bottom = self.rectangle
        pl, pt, pr, pb = self.padding
        if (
            min(self.photo_size) < 1
            or min(self.prediction_size) < 1
            or min(self.padding) < 0
            or not (
                0 <= left < right <= self.photo_size[0] and 0 <= top < bottom <= self.photo_size[1]
            )
        ):
            raise ValueError("Invalid crop dimensions or photo bounds")
        width, height = self.prediction_size
        if width <= pl + pr or height <= pt + pb:
            raise ValueError("Prediction padding leaves no crop pixels")
        sx, sy = (width - pl - pr) / (right - left), (height - pt - pb) / (bottom - top)
        expected = (sx, sy, (-left + 0.5) * sx - 0.5 + pl, (-top + 0.5) * sy - 0.5 + pt)
        if not np.allclose(self.photo_to_prediction, expected, rtol=0, atol=1e-9):
            raise ValueError("Crop transform does not preserve declared pixel centres")

    def resized(
        self, size: tuple[int, int], *, padding: tuple[int, int, int, int] = (0, 0, 0, 0)
    ) -> Crop:
        left, top, right, bottom = self.rectangle
        pl, pt, pr, pb = padding
        sx, sy = (size[0] - pl - pr) / (right - left), (size[1] - pt - pb) / (bottom - top)
        return Crop(
            self.rectangle,
            self.photo_size,
            size,
            (sx, sy, (-left + 0.5) * sx - 0.5 + pl, (-top + 0.5) * sy - 0.5 + pt),
            padding,
        )


def plan_crop(box: FloatMap, photo_size: tuple[int, int]) -> Crop:
    """40% per side, outward rounding, clipped half-open photo rectangle."""
    if box.shape != (4, 2) or not np.isfinite(box).all() or min(photo_size) < 1:
        raise ValueError("Invalid placement or photo dimensions")
    lo, hi = box.min(axis=0).astype(float), box.max(axis=0).astype(float)
    if np.any(hi <= lo):
        raise ValueError("Placement must have positive width and height")
    margin = (hi - lo) * 0.4
    left, top = max(0, math.floor(lo[0] - margin[0])), max(0, math.floor(lo[1] - margin[1]))
    right, bottom = (
        min(photo_size[0], math.ceil(hi[0] + margin[0])),
        min(photo_size[1], math.ceil(hi[1] + margin[1])),
    )
    if right <= left or bottom <= top:
        raise ValueError("Placement does not intersect photo")
    return Crop(
        (left, top, right, bottom),
        photo_size,
        (right - left, bottom - top),
        (1.0, 1.0, -float(left), -float(top)),
    )


@dataclass(frozen=True)
class EvidenceIdentity:
    photo: str
    checkpoints: str
    inference: str
    preprocessing: str


def evidence_covers(
    crop: Crop,
    identity: EvidenceIdentity,
    box: FloatMap,
    photo_size: tuple[int, int],
    required_identity: EvidenceIdentity,
) -> bool:
    if identity != required_identity or crop.photo_size != photo_size:
        return False
    required = plan_crop(box, photo_size).rectangle
    left, top, right, bottom = crop.rectangle
    return (
        left <= required[0]
        and top <= required[1]
        and right >= required[2]
        and bottom >= required[3]
    )


@dataclass(frozen=True)
class Evidence:
    crop: Crop
    identity: EvidenceIdentity
    normals: FloatMap
    shading: FloatMap
    albedo: FloatMap
    residual: FloatMap
    depth: FloatMap

    def __post_init__(self) -> None:
        width, height = self.crop.prediction_size
        for array, channels in [
            (self.normals, 3),
            (self.shading, 3),
            (self.albedo, 3),
            (self.residual, 3),
            (self.depth, 0),
        ]:
            shape = (height, width, channels) if channels else (height, width)
            if array.shape != shape or array.dtype != np.float32 or not np.isfinite(array).all():
                raise ValueError("Invalid evidence shape, dtype or finite values")
        if np.any(np.abs(self.normals) > 1.01) or not np.allclose(
            np.linalg.norm(self.normals, axis=-1), 1, atol=0.02
        ):
            raise ValueError("Evidence normals must be unit vectors")
        if any(
            np.any((array < 0) | (array > 1))
            for array in [self.shading, self.albedo, self.residual, self.depth]
        ):
            raise ValueError("Evidence lighting/depth must be in [0,1]")

    def sample(self, array: FloatMap, xy: FloatMap) -> FloatMap:
        sx, sy, ox, oy = self.crop.photo_to_prediction
        return geometry.sample(
            array, xy * np.array([sx, sy], np.float32) + np.array([ox, oy], np.float32)
        )


@dataclass(frozen=True)
class Preparation:
    maps: MaterialMaps
    diagnostics: dict[str, Any]


def prepare(
    base: RGB,
    box: FloatMap,
    evidence: Evidence,
    *,
    mask: FloatMap,
    checkpoint: Callable[[str], None] = lambda _: None,
) -> Preparation:
    """Fit one placement from explicit evidence, with cancellation between phases.

    A supplied mask is the durable edited visibility, not brush history. The
    checkpoint callback may raise to cancel without publishing partial maps.
    """
    height, width = base.shape[:2]
    size = (width, height)
    if not evidence_covers(evidence.crop, evidence.identity, box, size, evidence.identity):
        raise ValueError("Evidence does not cover the full placement margin")
    if not cv2.isContourConvex(box) or cv2.contourArea(box) < 1:
        raise ValueError("Choose a convex uncrossed placement in TL, TR, BR, BL order")
    if (
        mask.shape != (height, width)
        or mask.dtype != np.float32
        or not np.isfinite(mask).all()
        or np.any((mask < 0) | (mask > 1))
    ):
        raise ValueError("Visibility mask must be finite float32 photo pixels in [0,1]")
    grid = geometry.placement_grid(box, 49)
    placement_width = float((np.linalg.norm(box[1] - box[0]) + np.linalg.norm(box[2] - box[3])) / 2)
    normals = evidence.sample(evidence.normals, grid)
    normals /= np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-8)
    confidence = geometry.sample(mask, grid)
    grid_ids = np.ones((49, 49), np.int32)
    checkpoint("fitting")
    surface, diagnostics = geometry.integrate(
        grid / placement_width, normals, confidence, grid_ids, evidence.sample(evidence.depth, grid)
    )
    checkpoint("flattening")
    uv, flat_diagnostics = geometry.flatten(surface, grid_ids)
    checkpoint("baking")
    neutral = geometry.placement_grid(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), 49)
    material, valid = material_math.bake(neutral, box, size)
    material += geometry.sample(uv - neutral, material * 48)
    valid *= mask
    labels = (valid > 0).astype(np.int32)
    checkpoint("lighting")
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    xy = np.stack([xx, yy], -1)
    full_normals = evidence.sample(evidence.normals, xy)
    _, full_confidence = geometry.slopes(full_normals)
    fields, light_diagnostics = geometry.lighting_fields(
        base,
        evidence.sample(evidence.shading, xy),
        evidence.sample(evidence.albedo, xy),
        evidence.sample(evidence.residual, xy),
        mask * geometry.polygon_mask(size, box.tolist()),
        full_confidence,
    )
    return Preparation(
        MaterialMaps(
            material,
            valid,
            fields["iid"],
            fields["photographic"],
            fields["texture"],
            fields["residual"],
            labels,
        ),
        {**diagnostics, **flat_diagnostics, **light_diagnostics},
    )


@dataclass(frozen=True)
class MaskProposal:
    mask: FloatMap
    diagnostics: dict[str, Any]
    algorithm: str = "seeded-grabcut-v1"


_MASK_PROPOSAL_LOCK = threading.Lock()


def propose_mask(base: RGB, box: FloatMap) -> MaskProposal:
    h, w = base.shape[:2]
    scale = min(1, 640 / max(h, w))
    small = cv2.resize(
        base, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_LINEAR
    )
    centre = box.mean(axis=0)
    inner = centre + (box - centre) * 0.5
    outer = centre + (box - centre) * 1.55
    seed = np.zeros(small.shape[:2], np.uint8)
    region = seed.copy()
    cv2.fillPoly(seed, [np.rint(inner * scale).astype(np.int32)], (1,), lineType=cv2.LINE_8)
    cv2.fillPoly(region, [np.rint(outer * scale).astype(np.int32)], (1,), lineType=cv2.LINE_8)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    ab = lab[..., 1:]
    values = ab[seed > 0]
    if len(values) < 20:
        return MaskProposal(
            np.ones((h, w), np.float32),
            {"fallback": "manual visibility; too few reliable colour seeds"},
        )
    median = np.median(values, axis=0)
    deviation = np.maximum(np.median(np.abs(values - median), axis=0) * 1.4826, 4)
    distance = np.linalg.norm((ab - median) / deviation, axis=-1)
    mask = np.full(seed.shape, cv2.GC_BGD, np.uint8)
    mask[region > 0] = cv2.GC_PR_BGD
    mask[(region > 0) & (distance < 3.5)] = cv2.GC_PR_FGD
    mask[(seed > 0) & (distance < 1.7)] = cv2.GC_FGD
    # Strong chroma disagreement excludes skin on these development shirts;
    # lighting changes and dark creases alone do not supply background seeds.
    mask[(region > 0) & (distance > 5)] = cv2.GC_BGD
    if (mask == cv2.GC_FGD).sum() < 20 or not np.any(mask == cv2.GC_BGD):
        return MaskProposal(
            np.ones((h, w), np.float32),
            {
                "adapter": "seeded GrabCut",
                "fallback": "manual visibility; too few reliable colour seeds",
            },
        )
    # OpenCV RNG state is thread-owned. Seed and GrabCut run on this same
    # thread; the lock serializes this module's proposals, not external callers.
    with _MASK_PROPOSAL_LOCK:
        cv2.setRNGSeed(2026)
        cv2.grabCut(
            small[..., ::-1].copy(),
            mask,
            (0, 0, 0, 0),
            np.zeros((1, 65)),
            np.zeros((1, 65)),
            3,
            cv2.GC_INIT_WITH_MASK,
        )
    cloth = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.float32)
    cloth = cv2.resize(cloth, (w, h), interpolation=cv2.INTER_LINEAR)
    return MaskProposal(
        cast(FloatMap, cloth),
        {
            "adapter": "seeded GrabCut",
            "kind": "unapproved automatic colour proposal",
            "limitations": (
                "hair, jewellery, similar-coloured foreground and cloth overlap need review"
            ),
            "seed_chroma_lab": median.tolist(),
        },
    )
