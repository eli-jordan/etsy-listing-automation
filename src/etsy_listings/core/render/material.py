"""Prepared CPU sampling maps and scene composition. ADR-0053.

Schema v1 stores photo pixel centres in row/column order. Material channels
are U right, V down. 0/1 map to first/last artwork centres. Material sampling
uses linear interpolation with a zero border. Visibility outside the quad is zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from etsy_listings.core.render import _material_math as material_math
from etsy_listings.core.render.config import MarigoldAppearance
from etsy_listings.core.render.types import RGB, RGBA, FloatMap


@dataclass(frozen=True)
class MaterialMaps:
    material: FloatMap
    visibility: FloatMap
    estimated: FloatMap
    photographic: FloatMap
    texture: FloatMap
    residual: FloatMap
    patch_ids: NDArray[np.int32] | None = None

    @property
    def size(self) -> tuple[int, int]:
        return self.visibility.shape[1], self.visibility.shape[0]


Float = FloatMap
Pixels = RGBA


def sample(field: Float, xy: Float, border: int = cv2.BORDER_REPLICATE) -> Float:
    xy = np.asarray(xy, np.float32)
    return cast(
        Float,
        cv2.remap(
            field,
            xy[..., 0],
            xy[..., 1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=border,
            borderValue=(0,),
        ).astype(np.float32),
    )


def patch_derivative(material: Float, labels: NDArray[np.int32], axis: int) -> Float:
    """Centred differences inside a patch; one-sided at its boundary."""
    forward = np.roll(material, -1, axis=axis) - material
    backward = material - np.roll(material, 1, axis=axis)
    valid_forward = labels == np.roll(labels, -1, axis=axis)
    valid_backward = labels == np.roll(labels, 1, axis=axis)
    end: list[slice | int] = [slice(None), slice(None)]
    end[axis] = -1
    valid_forward[tuple(end)] = False
    end[axis] = 0
    valid_backward[tuple(end)] = False
    count = valid_forward.astype(np.float32) + valid_backward
    return cast(
        Float,
        (forward * valid_forward[..., None] + backward * valid_backward[..., None])
        / np.maximum(count[..., None], 1),
    )


def filtered_sample(
    artwork: Pixels, material: Float, patch_ids: NDArray[np.int32] | None = None
) -> Float:
    """Derivative-selected mip filtering in premultiplied linear colour."""
    packed = material_math.premultiply(artwork)
    h, w = artwork.shape[:2]
    labels = np.ones(material.shape[:2], np.int32) if patch_ids is None else patch_ids
    dy, dx = (patch_derivative(material, labels, axis) for axis in (0, 1))
    du_y, dv_y = dy[..., 0], dy[..., 1]
    du_x, dv_x = dx[..., 0], dx[..., 1]
    footprint = np.maximum(np.hypot(du_x * w, dv_x * h), np.hypot(du_y * w, dv_y * h))
    levels = min(10, int(np.log2(max(2, min(h, w)))))
    lod = np.clip(np.log2(np.maximum(footprint, 1)), 0, levels)
    low = np.floor(lod).astype(int)
    fraction = lod - low
    result = np.zeros((*material.shape[:2], 4), np.float32)
    for level in range(levels + 1):
        weight = np.where(low == level, 1 - fraction, 0) + np.where(low + 1 == level, fraction, 0)
        if np.any(weight > 0):
            xy = material * np.array([packed.shape[1] - 1, packed.shape[0] - 1], np.float32)
            result += sample(packed, xy, cv2.BORDER_CONSTANT) * weight[..., None]
        if level < levels:
            packed = cast(
                Float,
                cv2.resize(
                    packed,
                    (max(1, packed.shape[1] // 2), max(1, packed.shape[0] // 2)),
                    interpolation=cv2.INTER_AREA,
                ),
            )
    return result


@dataclass(frozen=True)
class MaterialLayer:
    design: RGBA
    maps: MaterialMaps
    placement_id: str | None = None


def render_marigold_scene(
    base: RGB, layers: Sequence[MaterialLayer], *, appearance: MarigoldAppearance | None = None
) -> Image.Image:
    """Compose in caller's placement order, retaining one linear colour buffer.

    Map acquisition validates the reference identity. This pure boundary also
    refuses colour photos with different dimensions. Artwork never uses albedo.
    """
    settings = appearance or MarigoldAppearance()
    if base.ndim != 3 or base.shape[2] != 3 or base.dtype != np.uint8:
        raise ValueError("Background must be uint8 RGB")
    result = material_math.linear(base)
    changed = np.zeros(base.shape[:2], bool)
    for layer in layers:
        maps = layer.maps
        if maps.size != (base.shape[1], base.shape[0]):
            raise ValueError("Shared colour photo dimensions differ from the main photo")
        if (
            layer.design.ndim != 3
            or layer.design.shape[2] != 4
            or layer.design.dtype != np.uint8
            or min(layer.design.shape[:2]) < 1
        ):
            raise ValueError("Artwork must be nonempty uint8 RGBA")
        sampled = filtered_sample(layer.design, maps.material, maps.patch_ids)
        selected_gain = (
            maps.estimated if settings.lighting_source == "estimated" else maps.photographic
        )
        gain = 1 + settings.lighting_strength * (selected_gain - 1)
        alpha = sampled[..., 3] * maps.visibility
        ink = (
            sampled[..., :3] * gain * (1 + settings.fabric_texture * (maps.texture - 1))[..., None]
            + sampled[..., 3, None] * settings.print_shine * maps.residual
        )
        result = ink * maps.visibility[..., None] + result * (1 - alpha[..., None])
        changed |= alpha > 0
    output = material_math.display(result)
    output[~changed] = base[~changed]
    return Image.fromarray(output)
