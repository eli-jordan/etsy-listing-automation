"""Similarity poses in a template box's rectified frame, mapped to photo pixels (ADR-0058).

The rectified frame is the box's unit-square parameterisation scaled by
``(W, H)``, the mean lengths of its top/bottom and left/right sides in photo
pixels, so a tilt is a rigid rotation of a box with its real proportions
(ADR-0058 amendment, 2026-11-02). Offsets are fractions of W and H; positive
rotation is clockwise in image coordinates. Fit in the rectified frame, measure
the maximum corner residual in photo pixels. No workspace, listing or settings
imports: limits use a structural protocol.
"""

from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, radians, sin
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from etsy_listings.core.render.config import BoundingBox, Point

_HORIZON_TOLERANCE = 1e-12


class ScaleLimits(Protocol):
    @property
    def min(self) -> float: ...

    @property
    def max(self) -> float: ...


class PositionLimits(Protocol):
    @property
    def scale(self) -> ScaleLimits: ...

    @property
    def offset(self) -> float: ...

    @property
    def rotation(self) -> float: ...


@dataclass(frozen=True)
class Pose:
    """Uniform scale and clockwise degrees about the box centre in its rectified
    frame, then translation in fractions of W and H."""

    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation: float = 0.0


@dataclass(frozen=True)
class PoseFit:
    pose: Pose
    residual_pixels: float


def _pixels(box: BoundingBox) -> NDArray[np.float64]:
    return np.array([(point.x, point.y) for point in box], dtype=np.float64)


def _unit() -> NDArray[np.float64]:
    return np.array([(0, 0), (1, 0), (1, 1), (0, 1)], dtype=np.float64)


def _proportions(box: BoundingBox) -> NDArray[np.float64]:
    """``(W, H)``: mean top/bottom and left/right side lengths in photo pixels."""
    tl, tr, br, bl = _pixels(box)
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    if not width > 0 or not height > 0:
        raise ValueError("template box has no invertible homography")
    return np.array((width, height), dtype=np.float64)


def _homography(box: BoundingBox) -> NDArray[np.float64]:
    # Float64 avoids OpenCV getPerspectiveTransform's float32 corner rounding.
    rows = []
    values = []
    for (u, v), point in zip(_unit(), box, strict=True):
        rows.extend(
            [
                (u, v, 1, 0, 0, 0, -u * point.x, -v * point.x),
                (0, 0, 0, u, v, 1, -u * point.y, -v * point.y),
            ]
        )
        values.extend([point.x, point.y])
    try:
        return np.append(np.linalg.solve(np.array(rows), np.array(values)), 1).reshape(3, 3)
    except np.linalg.LinAlgError as exc:
        raise ValueError("template box has no invertible homography") from exc


def _map(points: NDArray[np.float64], matrix: NDArray[np.float64]) -> NDArray[np.float64]:
    projected = np.column_stack((points, np.ones(len(points)))) @ matrix.T
    denominators = projected[:, 2:]
    if not (
        np.all(denominators > _HORIZON_TOLERANCE) or np.all(denominators < -_HORIZON_TOLERANCE)
    ):
        raise ValueError("position crosses the template homography's horizon")
    result: NDArray[np.float64] = projected[:, :2] / denominators
    if not np.all(np.isfinite(result)):
        raise ValueError("position has non-finite photo corners")
    return result


def compose(template_box: BoundingBox, pose: Pose) -> BoundingBox:
    """Apply ``pose`` in the rectified frame, then the template homography;
    return TL, TR, BR, BL."""
    homography = _homography(template_box)
    size = _proportions(template_box)
    angle = radians(pose.rotation)
    a, b = pose.scale * cos(angle), pose.scale * sin(angle)
    rectified = ((_unit() - 0.5) * size) @ np.array([[a, b], [-b, a]])
    rectified += (pose.offset_x, pose.offset_y) * size
    points = _map(rectified / size + 0.5, homography)
    return (
        Point(x=points[0, 0], y=points[0, 1]),
        Point(x=points[1, 0], y=points[1, 1]),
        Point(x=points[2, 0], y=points[2, 1]),
        Point(x=points[3, 0], y=points[3, 1]),
    )


def decompose(template_box: BoundingBox, box: BoundingBox) -> PoseFit:
    """Least-squares orientation-preserving similarity, even for a non-similarity.

    Raises ValueError for singular geometry or a quad crossing projective infinity.
    The residual is the largest Euclidean photo-pixel error, not a rectified-frame error.
    """
    try:
        inverse = np.linalg.inv(_homography(template_box))
    except np.linalg.LinAlgError as exc:
        raise ValueError("template box has no invertible homography") from exc
    size = _proportions(template_box)
    target = (_map(_pixels(box), inverse) - 0.5) * size
    centre = target.mean(axis=0)
    source = (_unit() - 0.5) * size
    centred = target - centre
    # The four centred corners have sum of squared distances W² + H².
    norm = float(np.sum(source * source))
    a = float(np.sum(source * centred) / norm)
    b = float(np.sum(source[:, 0] * centred[:, 1] - source[:, 1] * centred[:, 0]) / norm)
    pose = Pose(
        scale=hypot(a, b),
        offset_x=float(centre[0] / size[0]),
        offset_y=float(centre[1] / size[1]),
        rotation=degrees(atan2(b, a)),
    )
    residual = float(
        np.linalg.norm(_pixels(compose(template_box, pose)) - _pixels(box), axis=1).max()
    )
    return PoseFit(pose, residual)


def padded_box(template_box: BoundingBox, limits: PositionLimits) -> BoundingBox:
    """The smallest rectified-frame rectangle holding every pose ``limits``
    allow, mapped to photo corners: the *padded quad* a Marigold template's
    evidence must cover before any listing position on it can be fitted (spec
    *Rendering -> Marigold (option B)*, *Evidence coverage*).

    A ``W`` by ``H`` box at the largest scale ``s`` and tilt ``t`` reaches
    ``s * (W cos t + H sin t) / 2`` across and ``s * (W sin t + H cos t) / 2``
    down from its centre, plus the offset limit on each axis. The settings cap
    tilt at 30 degrees, where both sums still grow, so the largest tilt is the
    worst.
    """
    width, height = _proportions(template_box)
    angle = radians(limits.rotation)
    scale, offset = limits.scale.max, limits.offset
    half_x = scale * (cos(angle) + height / width * sin(angle)) / 2 + offset
    half_y = scale * (width / height * sin(angle) + cos(angle)) / 2 + offset
    unit = (_unit() - 0.5) * (2 * half_x, 2 * half_y) + 0.5
    points = _map(unit, _homography(template_box))
    return (
        Point(x=points[0, 0], y=points[0, 1]),
        Point(x=points[1, 0], y=points[1, 1]),
        Point(x=points[2, 0], y=points[2, 1]),
        Point(x=points[3, 0], y=points[3, 1]),
    )


def clamp_pose(pose: Pose, limits: PositionLimits) -> Pose:
    """Clamp each fitted component. Only explicit editor repair calls this."""
    return Pose(
        scale=max(limits.scale.min, min(limits.scale.max, pose.scale)),
        offset_x=max(-limits.offset, min(limits.offset, pose.offset_x)),
        offset_y=max(-limits.offset, min(limits.offset, pose.offset_y)),
        rotation=max(-limits.rotation, min(limits.rotation, pose.rotation)),
    )


def nearest_allowed_pose(
    template_box: BoundingBox, box: BoundingBox, limits: PositionLimits
) -> Pose:
    """Fit, then clamp (interactions: *Position outside the limits*).

    Compose the returned pose to obtain replacement absolute corners. This is the
    specified repair, not a pixel-space search for the closest quad.
    """
    return clamp_pose(decompose(template_box, box).pose, limits)
