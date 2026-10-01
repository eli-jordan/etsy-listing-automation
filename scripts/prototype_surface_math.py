"""THROWAWAY: classical surface/fold calibration, not the production A7 pipeline.

Question: does bounded, appearance-derived relief reduce authoring effort?
The photo supplies a height *proxy*, not measured depth. No AI or SciPy required.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

Float = NDArray[np.float32]
Pixels = NDArray[np.uint8]
SIZE = 256
MESH = 17


def resize(array: NDArray, size: tuple[int, int]) -> NDArray:
    return cv2.resize(array, size, interpolation=cv2.INTER_LINEAR)


def blur(array: Float, sigma: float) -> Float:
    return cv2.GaussianBlur(array, (0, 0), sigma, borderType=cv2.BORDER_REFLECT_101)


def linear(rgb: NDArray) -> Float:
    values = rgb.astype(np.float32) / 255
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def display(rgb: Float) -> Pixels:
    values = np.clip(rgb, 0, 1)
    values = np.where(values <= 0.0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - 0.055)
    return np.round(np.clip(values, 0, 1) * 255).astype(np.uint8)


def rectification(box: Float) -> Float:
    dst = np.array([[0, 0], [SIZE - 1, 0], [SIZE - 1, SIZE - 1], [0, SIZE - 1]], np.float32)
    return cv2.getPerspectiveTransform(box, dst)


def rectify(array: NDArray, box: Float) -> NDArray:
    return cv2.warpPerspective(
        array,
        rectification(box),
        (SIZE, SIZE),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def graph() -> tuple[NDArray, NDArray, NDArray]:
    ids = np.arange(MESH * MESH).reshape(MESH, MESH)
    starts = np.concatenate(
        [ids[:, :-1].ravel(), ids[:-1, :].ravel(), ids[:-1, :-1].ravel(), ids[:-1, 1:].ravel()]
    )
    ends = np.concatenate(
        [ids[:, 1:].ravel(), ids[1:, :].ravel(), ids[1:, 1:].ravel(), ids[1:, :-1].ravel()]
    )
    incidence = np.zeros((len(starts), MESH * MESH), np.float64)
    incidence[np.arange(len(starts)), starts] = -1
    incidence[np.arange(len(starts)), ends] = 1
    return starts, ends, incidence


@dataclass
class Analysis:
    crop: Pixels
    labels: NDArray[np.int32]
    folds: list[dict[str, float | int]]
    target: Float
    confidence: Float
    light: Float
    curvature: float


def analyse(base: Pixels, box: Float, exclusion: Pixels) -> Analysis:
    crop = rectify(base, box)
    excluded = rectify(exclusion, box).astype(np.float32) / 255
    rgb = linear(crop)
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    log_lum = np.log(np.maximum(luminance, 0.005))
    # Texture suppression before Hessian analysis; background is outside this ROI.
    smooth = blur(log_lum, 2.0)
    residual = smooth - blur(smooth, 18)
    best = np.zeros((SIZE, SIZE), np.float32)
    for sigma in (3.0, 6.0, 10.0):
        image = blur(log_lum, sigma)
        xx = cv2.Sobel(image, cv2.CV_32F, 2, 0, ksize=3, borderType=cv2.BORDER_REFLECT_101)
        yy = cv2.Sobel(image, cv2.CV_32F, 0, 2, ksize=3, borderType=cv2.BORDER_REFLECT_101)
        xy = cv2.Sobel(image, cv2.CV_32F, 1, 1, ksize=3, borderType=cv2.BORDER_REFLECT_101)
        disc = np.sqrt((xx - yy) ** 2 + 4 * xy**2)
        a, b = (xx + yy + disc) / 2, (xx + yy - disc) / 2
        large = np.maximum(np.abs(a), np.abs(b))
        small = np.minimum(np.abs(a), np.abs(b))
        ridge = large * sigma**2 * np.clip(1 - 2 * small / (large + 1e-6), 0, 1)
        best = np.maximum(best, ridge)
    allowed = excluded < 0.1
    allowed[:20] = allowed[-20:] = False
    allowed[:, :20] = allowed[:, -20:] = False
    best *= allowed
    threshold = max(0.075, float(np.percentile(best[allowed], 88))) if allowed.any() else 1
    binary = (best > threshold).astype(np.uint8)
    count, regions, stats, centres = cv2.connectedComponentsWithStats(binary, connectivity=8)
    candidates = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area >= 18 and max(w, h) >= 12:
            candidates.append(
                (int(area), label, float(centres[label, 0]), float(centres[label, 1]))
            )
    labels = np.zeros_like(regions)
    folds = []
    for index, (area, label, x, y) in enumerate(sorted(candidates, reverse=True)[:12], 1):
        labels[regions == label] = index
        folds.append({"id": index, "x": x / (SIZE - 1), "y": y / (SIZE - 1), "area": area})
    confidence = np.clip(best / max(threshold * 2, 0.01), 0, 1)
    confidence *= labels > 0
    # Signed brightness residual is a deliberately weak relief hypothesis.
    # Neither sign nor amplitude of physical depth can be identified this way.
    scale = max(float(np.percentile(np.abs(residual[allowed]), 95)), 0.05) if allowed.any() else 1
    target = np.clip(residual / scale, -1, 1)
    coarse = blur(log_lum, 28)
    profile = np.median(coarse[60:196], axis=0)
    centre = float(np.median(profile[100:156]))
    sides = float(np.median(np.concatenate([profile[25:65], profile[191:231]])))
    curvature = float(np.clip((centre - sides) * 0.18, 0, 0.18))
    # Mask-normalized illumination, so a painted-out chain/arm does not darken ink.
    mask = (1 - excluded).astype(np.float32)
    low = blur(luminance * mask, 8) / np.maximum(blur(mask, 8), 1e-5)
    reference = max(float(np.percentile(low[allowed], 65)), 0.005) if allowed.any() else 0.5
    gain = np.clip(low / reference, 0.45, 1.35)
    detail = np.clip(luminance / np.maximum(low, 0.005), 0.85, 1.15)
    return Analysis(crop, labels, folds, target, confidence, gain * detail**0.25, curvature)


def fit_surface(
    analysis: Analysis, aspect: float, curvature: float, relief: float, disabled: list[int]
) -> tuple[Float, Float]:
    yy, xx = np.meshgrid(np.linspace(0, aspect, MESH), np.linspace(0, 1, MESH), indexing="ij")
    broad = curvature * np.sqrt(np.maximum(0, 1 - (1.8 * (xx - 0.5)) ** 2))
    confidence = analysis.confidence.copy()
    confidence[np.isin(analysis.labels, disabled)] = 0
    confidence = resize(blur(confidence, 3), (MESH, MESH)).ravel().astype(np.float64)
    target = resize(analysis.target, (MESH, MESH)).ravel().astype(np.float64)
    _, _, incidence = graph()
    laplacian = incidence.T @ incidence
    # Penalized least squares: fold proxy constraints + smoothness + broad prior.
    weights = 0.25 + confidence * 5
    fitted = np.linalg.solve(np.diag(weights) + 0.6 * laplacian, confidence * 5 * target * relief)
    fitted = fitted.reshape(MESH, MESH)
    # Do not turn ROI boundary/seams into a floating edge.
    fade = np.sin(np.pi * xx) * np.sin(np.pi * yy / aspect)
    z = broad + fitted * fade
    return np.stack([xx, yy, z], axis=-1).astype(np.float32), broad.astype(np.float32)


def signed_areas(uv: Float) -> Float:
    a, b, c, d = uv[:-1, :-1], uv[:-1, 1:], uv[1:, :-1], uv[1:, 1:]

    def cross(x: Float, y: Float) -> Float:
        return x[..., 0] * y[..., 1] - x[..., 1] * y[..., 0]

    return np.stack([cross(b - a, c - a), cross(c - d, b - d)])


def flatten(surface: Float) -> tuple[Float, dict[str, float | int]]:
    starts, ends, incidence = graph()
    p = surface.reshape(-1, 3).astype(np.float64)
    rest = np.linalg.norm(p[ends] - p[starts], axis=1)
    width = float(np.mean(np.linalg.norm(np.diff(surface, axis=1), axis=2).sum(axis=1)))
    height = float(np.mean(np.linalg.norm(np.diff(surface, axis=0), axis=2).sum(axis=0)))
    yy, xx = np.meshgrid(np.linspace(0, height, MESH), np.linspace(0, width, MESH), indexing="ij")
    uv = np.stack([xx, yy], axis=-1).reshape(-1, 2)
    corners = np.array([0, MESH - 1, MESH * MESH - 1, MESH * (MESH - 1)])
    free = np.setdiff1d(np.arange(MESH * MESH), corners)
    laplacian = incidence.T @ incidence
    system = laplacian[np.ix_(free, free)]
    # Solve the same positive-definite system with many RHSs; numpy only.
    inverse = np.linalg.solve(system, np.eye(len(free)))
    fixed = laplacian[np.ix_(free, corners)] @ uv[corners]
    for _ in range(24):
        edges = uv[ends] - uv[starts]
        target = edges * (rest / np.maximum(np.linalg.norm(edges, axis=1), 1e-8))[:, None]
        rhs = incidence.T @ target
        proposal = uv.copy()
        proposal[free] = inverse @ (rhs[free] - fixed)
        delta = float(np.max(np.abs(proposal - uv)))
        uv = proposal
        if delta < 1e-6:
            break
    strain = np.linalg.norm(uv[ends] - uv[starts], axis=1) / rest - 1
    uv = (uv / [width, height]).reshape(MESH, MESH, 2).astype(np.float32)
    yy, xx = np.meshgrid(np.linspace(0, 1, MESH), np.linspace(0, 1, MESH), indexing="ij")
    neutral = np.stack([xx, yy], axis=-1).astype(np.float32)
    amount = 1.0
    while signed_areas(uv).min() < 1e-5 and amount > 1 / 128:
        amount /= 2
        uv = neutral + (uv - neutral) * 0.5
    if signed_areas(uv).min() <= 0:
        raise ValueError("surface map has flipped cells; reduce relief or curvature")
    return uv, {
        "flipped_cells": int((signed_areas(uv) <= 0).sum()),
        "rms_edge_strain": float(np.sqrt(np.mean(strain**2))),
        "safety_blend": amount,
        "max_material_shift": float(np.max(np.linalg.norm(uv - neutral, axis=2))),
    }


def bake(uv: Float, box: Float, size: tuple[int, int]) -> tuple[Float, Float]:
    """Fixed diagonal triangle interpolation; photo -> material, never inverted by negation."""
    width, height = size
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    matrix = rectification(box)
    den = matrix[2, 0] * xx + matrix[2, 1] * yy + matrix[2, 2]
    den = np.where(np.abs(den) < 1e-8, np.nan, den)
    x = (matrix[0, 0] * xx + matrix[0, 1] * yy + matrix[0, 2]) / den / (SIZE - 1)
    y = (matrix[1, 0] * xx + matrix[1, 1] * yy + matrix[1, 2]) / den / (SIZE - 1)
    valid = (x >= 0) & (x <= 1) & (y >= 0) & (y <= 1) & np.isfinite(x + y)
    gx = np.clip(np.nan_to_num(x), 0, 1) * (MESH - 1)
    gy = np.clip(np.nan_to_num(y), 0, 1) * (MESH - 1)
    ix, iy = np.minimum(gx.astype(int), MESH - 2), np.minimum(gy.astype(int), MESH - 2)
    fx, fy = gx - ix, gy - iy
    a, b, c, d = uv[iy, ix], uv[iy, ix + 1], uv[iy + 1, ix], uv[iy + 1, ix + 1]
    lower = a + fx[..., None] * (b - a) + fy[..., None] * (c - a)
    upper = d + (1 - fx[..., None]) * (c - d) + (1 - fy[..., None]) * (b - d)
    material = np.where((fx + fy <= 1)[..., None], lower, upper).astype(np.float32)
    return material, valid.astype(np.float32)


def project(field: Float, box: Float, size: tuple[int, int], outside: float) -> Float:
    return cv2.warpPerspective(
        field,
        np.linalg.inv(rectification(box)),
        size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=outside,
    )


def premultiply(artwork: Pixels) -> Float:
    rgb = linear(artwork[..., :3])
    alpha = artwork[..., 3].astype(np.float32) / 255
    return np.concatenate([rgb * alpha[..., None], alpha[..., None]], axis=2)


def composite(
    base: Pixels,
    artwork: Pixels | Float,
    material: Float,
    valid: Float,
    light: Float,
    lighting: float,
) -> Pixels:
    packed = premultiply(artwork) if artwork.dtype == np.uint8 else artwork
    sampled = cv2.remap(
        packed,
        material[..., 0] * (artwork.shape[1] - 1),
        material[..., 1] * (artwork.shape[0] - 1),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    ink = sampled[..., :3] * (1 + lighting * (light - 1))[..., None]
    alpha = sampled[..., 3] * valid
    result = ink * valid[..., None] + linear(base) * (1 - alpha[..., None])
    output = display(result)
    # A7-style integrity check: preserve byte-identical pixels outside visible print.
    output[alpha == 0] = base[alpha == 0]
    return output
