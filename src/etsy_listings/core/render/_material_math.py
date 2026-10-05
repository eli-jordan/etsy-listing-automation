"""Internal numerical helpers ported from the evaluated prototype. ADR-0053."""

from __future__ import annotations

from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

Float = NDArray[np.float32]
Pixels = NDArray[np.uint8]


def blur(array: Float, sigma: float) -> Float:
    return cast(Float, cv2.GaussianBlur(array, (0, 0), sigma, borderType=cv2.BORDER_REFLECT_101))


def linear(rgb: NDArray[Any]) -> Float:
    values = rgb.astype(np.float32) / 255
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def display(rgb: Float) -> Pixels:
    values = np.clip(rgb, 0, 1)
    values = np.where(values <= 0.0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - 0.055)
    return np.round(np.clip(values, 0, 1) * 255).astype(np.uint8)


def graph(mesh: int) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any]]:
    ids = np.arange(mesh * mesh).reshape(mesh, mesh)
    starts = np.concatenate(
        [ids[:, :-1].ravel(), ids[:-1, :].ravel(), ids[:-1, :-1].ravel(), ids[:-1, 1:].ravel()]
    )
    ends = np.concatenate(
        [ids[:, 1:].ravel(), ids[1:, :].ravel(), ids[1:, 1:].ravel(), ids[1:, :-1].ravel()]
    )
    degree = np.bincount(np.concatenate([starts, ends]), minlength=mesh * mesh).astype(np.float64)
    return starts, ends, degree


def signed_areas(uv: Float) -> Float:
    a, b, c, d = uv[:-1, :-1], uv[:-1, 1:], uv[1:, :-1], uv[1:, 1:]

    def cross(x: Float, y: Float) -> Float:
        return x[..., 0] * y[..., 1] - x[..., 1] * y[..., 0]

    return np.stack([cross(b - a, c - a), cross(c - d, b - d)])


def bake(uv: Float, box: Float, size: tuple[int, int]) -> tuple[Float, Float]:
    """Fixed diagonal triangle interpolation; photo -> material, never inverted by negation."""
    width, height = size
    mesh = uv.shape[0]
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    matrix = cv2.getPerspectiveTransform(
        box, np.array([[0, 0], [255, 0], [255, 255], [0, 255]], np.float32)
    )
    den = matrix[2, 0] * xx + matrix[2, 1] * yy + matrix[2, 2]
    den = np.where(np.abs(den) < 1e-8, np.nan, den)
    x = (matrix[0, 0] * xx + matrix[0, 1] * yy + matrix[0, 2]) / den / 255
    y = (matrix[1, 0] * xx + matrix[1, 1] * yy + matrix[1, 2]) / den / 255
    valid = (x >= 0) & (x <= 1) & (y >= 0) & (y <= 1) & np.isfinite(x + y)
    gx = np.clip(np.nan_to_num(x), 0, 1) * (mesh - 1)
    gy = np.clip(np.nan_to_num(y), 0, 1) * (mesh - 1)
    ix, iy = np.minimum(gx.astype(int), mesh - 2), np.minimum(gy.astype(int), mesh - 2)
    fx, fy = gx - ix, gy - iy
    a, b, c, d = uv[iy, ix], uv[iy, ix + 1], uv[iy + 1, ix], uv[iy + 1, ix + 1]
    lower = a + fx[..., None] * (b - a) + fy[..., None] * (c - a)
    upper = d + (1 - fx[..., None]) * (c - d) + (1 - fy[..., None]) * (b - d)
    material = np.where((fx + fy <= 1)[..., None], lower, upper).astype(np.float32)
    return material, valid.astype(np.float32)


def premultiply(artwork: Pixels) -> Float:
    rgb = linear(artwork[..., :3])
    alpha = artwork[..., 3].astype(np.float32) / 255
    return np.concatenate([rgb * alpha[..., None], alpha[..., None]], axis=2)
