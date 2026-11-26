from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

Float = NDArray[np.float32]
Pixels = NDArray[np.uint8]

# The sRGB transfer function's linear segment ends here, in encoded and in
# linear terms (IEC 61966-2-1).
_SRGB_ENCODED_KNEE = 0.04045
_SRGB_LINEAR_KNEE = 0.0031308
_DEGENERATE_HOMOGRAPHY = 1e-8
_BAKE_TILE_ROWS = 128


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


def blur(array: Float, sigma: float) -> Float:
    return cast(Float, cv2.GaussianBlur(array, (0, 0), sigma, borderType=cv2.BORDER_REFLECT_101))


def _srgb_decode(values: NDArray[Any]) -> Float:
    return cast(
        Float,
        np.where(values <= _SRGB_ENCODED_KNEE, values / 12.92, ((values + 0.055) / 1.055) ** 2.4),
    )


_LINEAR_BYTE_TABLE = _srgb_decode(np.arange(256, dtype=np.float32) / 255)
_LINEAR_BYTE_TABLE.setflags(write=False)


def linear(rgb: NDArray[Any]) -> Float:
    if rgb.dtype == np.uint8:
        return cast(Float, _LINEAR_BYTE_TABLE[rgb])
    return _srgb_decode(rgb.astype(np.float32) / 255)


def display(rgb: Float) -> Pixels:
    values = np.clip(rgb, 0, 1)
    values = np.where(
        values <= _SRGB_LINEAR_KNEE, values * 12.92, 1.055 * values ** (1 / 2.4) - 0.055
    )
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


def bake(
    uv: Float, box: Float, size: tuple[int, int], *, origin: tuple[int, int] = (0, 0)
) -> tuple[Float, Float]:
    """Fixed diagonal triangle interpolation; photo -> material, never inverted by negation."""
    width, height = size
    mesh = uv.shape[0]
    coordinate = np.arange(mesh, dtype=np.float32) / (mesh - 1)
    neutral = np.array_equal(
        uv[..., 0], np.broadcast_to(coordinate, (mesh, mesh))
    ) and np.array_equal(uv[..., 1], np.broadcast_to(coordinate[:, None], (mesh, mesh)))
    matrix = cv2.getPerspectiveTransform(
        box, np.array([[0, 0], [255, 0], [255, 255], [0, 255]], np.float32)
    )
    material = np.empty((height, width, 2), np.float32)
    visibility = np.empty((height, width), np.float32)
    # Row tiles bound the float64 triangle temporaries' memory.
    for top in range(0, height, _BAKE_TILE_ROWS):
        bottom = min(top + _BAKE_TILE_ROWS, height)
        yy, xx = np.mgrid[
            origin[1] + top : origin[1] + bottom, origin[0] : origin[0] + width
        ].astype(np.float32)
        den = matrix[2, 0] * xx + matrix[2, 1] * yy + matrix[2, 2]
        den = np.where(np.abs(den) < _DEGENERATE_HOMOGRAPHY, np.nan, den)
        x = (matrix[0, 0] * xx + matrix[0, 1] * yy + matrix[0, 2]) / den / 255
        y = (matrix[1, 0] * xx + matrix[1, 1] * yy + matrix[1, 2]) / den / 255
        valid = (x >= 0) & (x <= 1) & (y >= 0) & (y <= 1) & np.isfinite(x + y)
        gx = np.clip(np.nan_to_num(x), 0, 1) * (mesh - 1)
        gy = np.clip(np.nan_to_num(y), 0, 1) * (mesh - 1)
        ix, iy = np.minimum(gx.astype(int), mesh - 2), np.minimum(gy.astype(int), mesh - 2)
        cell = _Cell(ix, iy, gx - ix, gy - iy)
        tile = _neutral_grid_tile(coordinate, cell) if neutral else _triangle_tile(uv, cell)
        material[top:bottom] = tile
        visibility[top:bottom] = valid
    return material, visibility


@dataclass(frozen=True)
class _Cell:
    """Each pixel's mesh cell (``ix``, ``iy``) and position inside it (``fx``, ``fy``)."""

    ix: NDArray[np.intp]
    iy: NDArray[np.intp]
    fx: NDArray[Any]
    fy: NDArray[Any]


def _triangle_tile(uv: Float, cell: _Cell) -> Float:
    ix, iy, fx, fy = cell.ix, cell.iy, cell.fx, cell.fy
    a, b, c, d = uv[iy, ix], uv[iy, ix + 1], uv[iy + 1, ix], uv[iy + 1, ix + 1]
    lower = a + fx[..., None] * (b - a) + fy[..., None] * (c - a)
    upper = d + (1 - fx[..., None]) * (c - d) + (1 - fy[..., None]) * (b - d)
    return cast(Float, np.where((fx + fy <= 1)[..., None], lower, upper).astype(np.float32))


def _neutral_grid_tile(coordinate: Float, cell: _Cell) -> Float:
    """:func:`_triangle_tile`'s bytes on the neutral grid, whose triangle
    components are separable, without loading four two-channel fields per pixel."""
    ix, iy, fx, fy = cell.ix, cell.iy, cell.fx, cell.fy
    ax, bx = coordinate[ix], coordinate[ix + 1]
    ay, dy = coordinate[iy], coordinate[iy + 1]
    lower_x = ax + fx * (bx - ax)
    lower_y = ay + fy * (dy - ay)
    upper_x = bx + (1 - fx) * (ax - bx)
    upper_y = dy + (1 - fy) * (ay - dy)
    lower_triangle = fx + fy <= 1
    return np.stack(
        [np.where(lower_triangle, lower_x, upper_x), np.where(lower_triangle, lower_y, upper_y)],
        -1,
    ).astype(np.float32)


def premultiply(artwork: Pixels) -> Float:
    rgb = linear(artwork[..., :3])
    alpha = artwork[..., 3].astype(np.float32) / 255
    return np.concatenate([rgb * alpha[..., None], alpha[..., None]], axis=2)
