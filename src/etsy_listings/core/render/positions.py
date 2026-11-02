"""Similarity poses in a template's unit frame, mapped to photo pixels (ADR-0058).

Offsets are fractions of width/height; positive rotation is clockwise in image
coordinates. Fit in the unit frame, measure the maximum corner residual in photo
pixels. No workspace, listing or settings imports: limits use a structural protocol.
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
    """Uniform scale and clockwise degrees about (0.5, 0.5), then translation."""

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
    """Apply ``pose`` before the template homography; return TL, TR, BR, BL."""
    angle = radians(pose.rotation)
    a, b = pose.scale * cos(angle), pose.scale * sin(angle)
    unit = (_unit() - 0.5) @ np.array([[a, b], [-b, a]])
    unit += (0.5 + pose.offset_x, 0.5 + pose.offset_y)
    points = _map(unit, _homography(template_box))
    return (
        Point(x=points[0, 0], y=points[0, 1]),
        Point(x=points[1, 0], y=points[1, 1]),
        Point(x=points[2, 0], y=points[2, 1]),
        Point(x=points[3, 0], y=points[3, 1]),
    )


def decompose(template_box: BoundingBox, box: BoundingBox) -> PoseFit:
    """Least-squares orientation-preserving similarity, even for a non-similarity.

    Raises ValueError for singular geometry or a quad crossing projective infinity.
    The residual is the largest Euclidean photo-pixel error, not a unit-frame error.
    """
    try:
        inverse = np.linalg.inv(_homography(template_box))
    except np.linalg.LinAlgError as exc:
        raise ValueError("template box has no invertible homography") from exc
    target = _map(_pixels(box), inverse)
    centre = target.mean(axis=0)
    source = _unit() - 0.5
    centred = target - centre
    # The four unit corners have sum of squared distances 2.
    a = float(np.sum(source * centred) / 2)
    b = float(np.sum(source[:, 0] * centred[:, 1] - source[:, 1] * centred[:, 0]) / 2)
    pose = Pose(
        scale=hypot(a, b),
        offset_x=float(centre[0] - 0.5),
        offset_y=float(centre[1] - 0.5),
        rotation=degrees(atan2(b, a)),
    )
    residual = float(
        np.linalg.norm(_pixels(compose(template_box, pose)) - _pixels(box), axis=1).max()
    )
    return PoseFit(pose, residual)


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
