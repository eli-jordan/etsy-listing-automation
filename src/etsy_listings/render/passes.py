"""Pure render passes: warp -> displace -> shade -> export/export_many. A7.

No I/O, no globals, no clock. Every array is 8-bit sRGB; RGBA where alpha
matters (the design and its warped/displaced/shaded print layer), RGB for the
opaque mockup base photo. Every ``cv2`` call passes explicit ``interpolation``
and ``borderMode`` -- relying on defaults makes output depend on the library
version (CLAUDE.md invariant; PRD risk 9), so ``tests/unit/test_no_bare_cv2.py``
greps this module for the ones that aren't.
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np
from PIL import Image

from etsy_listings.render.config import BoundingBox, DisplaceConfig, ShadeConfig
from etsy_listings.render.types import RGB, RGBA, FloatMap

DISPLACE_MAX_PX = 24.0
"""Pixel displacement at strength=1.0. A calibration constant, not derived --
tuned by eye in the calibrator, per template."""


def warp(design: RGBA, bounding_box: BoundingBox, output_size: tuple[int, int]) -> RGBA:
    """Homography from the design's own rectangle onto ``bounding_box``.

    ``output_size`` is ``(width, height)`` of the template canvas the design is
    being placed onto -- the warped result is canvas-sized so later passes never
    need to know where on the canvas the print area sits.
    """
    h, w = design.shape[:2]
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    dst = np.array([[p.x, p.y] for p in bounding_box], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst)
    result = cv2.warpPerspective(
        design,
        matrix,
        output_size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return np.asarray(result, dtype=np.uint8)


def displace(img: RGBA, cfg: DisplaceConfig, height: FloatMap) -> RGBA:
    """Standard Photoshop apparel-mockup displacement: remap by the gradient of
    a height field derived from the mockup's own luminance (see
    :mod:`etsy_listings.render.maps`). Off unless ``cfg.enabled``."""
    if not cfg.enabled or cfg.strength <= 0:
        return img

    h, w = img.shape[:2]
    grad_x = np.asarray(
        cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3, borderType=cv2.BORDER_REPLICATE),
        dtype=np.float32,
    )
    grad_y = np.asarray(
        cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3, borderType=cv2.BORDER_REPLICATE),
        dtype=np.float32,
    )
    scale = cfg.strength * DISPLACE_MAX_PX

    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_x = xs + grad_x * scale
    map_y = ys + grad_y * scale

    result = cv2.remap(
        img,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return np.asarray(result, dtype=np.uint8)


def _soft_light(base: FloatMap, light: FloatMap) -> FloatMap:
    """Photoshop-style soft-light blend, both operands in [0, 1]."""
    dark = 2 * base * light + base**2 * (1 - 2 * light)
    bright = np.sqrt(base) * (2 * light - 1) + 2 * base * (1 - light)
    return np.where(light <= 0.5, dark, bright)


def shade(img: RGBA, cfg: ShadeConfig, luminance: FloatMap) -> RGBA:
    """Blend the mockup's own lighting/fold shadows over the design so the
    print picks up the garment's shape. ``multiply`` crushes dark garments;
    ``soft-light``/``grey-pivot`` exist for those (PRD)."""
    if not cfg.enabled or cfg.opacity <= 0:
        return img

    rgb = img[..., :3].astype(np.float32) / 255.0
    alpha = img[..., 3:4]
    lum = luminance[..., None]

    if cfg.blend == "multiply":
        blended = rgb * lum
    elif cfg.blend == "soft-light":
        blended = _soft_light(rgb, lum)
    else:  # grey-pivot: push toward the luminance around a neutral mid-grey
        blended = np.clip(rgb + (lum - 0.5) * 2.0, 0.0, 1.0)

    out_rgb = np.clip(rgb * (1 - cfg.opacity) + blended * cfg.opacity, 0.0, 1.0)
    out_rgb_u8 = (out_rgb * 255.0 + 0.5).astype(np.uint8)
    result: RGBA = np.concatenate([out_rgb_u8, alpha], axis=-1)
    return result


def export(base: RGB, print_layer: RGBA) -> Image.Image:
    """Alpha-composite ``print_layer`` (canvas-sized RGBA) over the opaque
    ``base`` mockup photo. Straight (non-premultiplied) alpha, composited in
    float32 and rounded rather than truncated -- documented here since this is
    the one place the alpha compositing order matters for determinism."""
    base_f = base[..., :3].astype(np.float32)
    print_rgb = print_layer[..., :3].astype(np.float32)
    alpha = print_layer[..., 3:4].astype(np.float32) / 255.0

    composite = base_f * (1 - alpha) + print_rgb * alpha
    composite_u8 = np.clip(composite + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(composite_u8, mode="RGB")


def export_many(base: RGB, print_layers: Sequence[RGBA]) -> Image.Image:
    """Alpha-composite several canvas-sized RGBA layers over ``base`` in list
    order (``multiple``-kind scenes only -- a separate function rather than a
    generalisation of :func:`export`, so the single-layer path used by
    ``colour-matrix``/``single`` kinds, and every golden that exercises it,
    stays untouched). Same straight-alpha, float32, round-not-truncate
    arithmetic as :func:`export`, folded across every layer in turn."""
    composite = base[..., :3].astype(np.float32)
    for layer in print_layers:
        layer_rgb = layer[..., :3].astype(np.float32)
        alpha = layer[..., 3:4].astype(np.float32) / 255.0
        composite = composite * (1 - alpha) + layer_rgb * alpha
    composite_u8 = np.clip(composite + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(composite_u8, mode="RGB")
