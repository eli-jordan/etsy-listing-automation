"""Pure pose maths in the template homography's frame (ADR-0058)."""

from random import Random

import numpy as np
import pytest
from pydantic import TypeAdapter

from etsy_listings.core.config.settings import TemplatePositionLimits
from etsy_listings.core.render.config import BoundingBox
from etsy_listings.core.render.positions import Pose, compose, decompose, nearest_allowed_pose

BOX = TypeAdapter(BoundingBox).validate_python(
    [
        {"x": 100, "y": 200},
        {"x": 500, "y": 170},
        {"x": 600, "y": 800},
        {"x": 50, "y": 850},
    ]
)
FLAT = TypeAdapter(BoundingBox).validate_python(
    [
        {"x": 10, "y": 20},
        {"x": 110, "y": 20},
        {"x": 110, "y": 220},
        {"x": 10, "y": 220},
    ]
)


def pixels(box: BoundingBox) -> list[tuple[float, float]]:
    return [(point.x, point.y) for point in box]


@pytest.mark.parametrize("box", [BOX, FLAT])
def test_identity_preserves_photo_corners(box: BoundingBox) -> None:
    np.testing.assert_allclose(pixels(compose(box, Pose())), pixels(box), atol=1e-8)
    fit = decompose(box, box)
    assert fit.pose.scale == pytest.approx(1)
    assert fit.residual_pixels < 1e-8


def test_known_unit_frame_move_and_scale() -> None:
    actual = compose(FLAT, Pose(scale=0.8, offset_x=0.1, offset_y=-0.1))
    np.testing.assert_allclose(pixels(actual), [(30, 20), (110, 20), (110, 180), (30, 180)])


@pytest.mark.parametrize("seed", range(25))
def test_similarity_round_trip_through_perspective(seed: int) -> None:
    random = Random(seed)
    box = tuple(
        point.model_copy(
            update={"x": point.x + random.uniform(-10, 10), "y": point.y + random.uniform(-10, 10)}
        )
        for point in BOX
    )
    pose = Pose(
        scale=random.uniform(0.5, 1.5),
        offset_x=random.uniform(-0.25, 0.25),
        offset_y=random.uniform(-0.25, 0.25),
        rotation=random.uniform(-30, 30),
    )
    quad = compose(box, pose)
    fitted = decompose(box, quad)
    assert fitted.pose.scale == pytest.approx(pose.scale)
    assert fitted.pose.offset_x == pytest.approx(pose.offset_x)
    assert fitted.pose.offset_y == pytest.approx(pose.offset_y)
    assert fitted.pose.rotation == pytest.approx(pose.rotation)
    assert fitted.residual_pixels < 1e-7
    np.testing.assert_allclose(pixels(compose(box, fitted.pose)), pixels(quad), atol=1e-7)


def test_residual_is_measured_in_photo_pixels() -> None:
    stretched = TypeAdapter(BoundingBox).validate_python(
        [
            {"x": 0, "y": 20},
            {"x": 120, "y": 20},
            {"x": 120, "y": 220},
            {"x": 0, "y": 220},
        ]
    )
    assert decompose(FLAT, stretched).residual_pixels > 1


def test_nearest_allowed_pose_repairs_nonuniform_stretch_by_fitting_first() -> None:
    stretched = TypeAdapter(BoundingBox).validate_python(
        [
            {"x": 0, "y": 20},
            {"x": 120, "y": 20},
            {"x": 120, "y": 220},
            {"x": 0, "y": 220},
        ]
    )
    # Unit-frame x scale 1.2 and y scale 1 average to uniform scale 1.1.
    repaired = compose(FLAT, nearest_allowed_pose(FLAT, stretched, TemplatePositionLimits()))
    np.testing.assert_allclose(pixels(repaired), [(5, 10), (115, 10), (115, 230), (5, 230)])


def test_singular_template_is_a_geometry_error() -> None:
    singular = TypeAdapter(BoundingBox).validate_python(
        [
            {"x": 0, "y": 0},
            {"x": 100, "y": 100},
            {"x": 200, "y": 200},
            {"x": 300, "y": 300},
        ]
    )
    with pytest.raises(ValueError, match="homography"):
        decompose(singular, FLAT)


@pytest.mark.parametrize("box", [BOX, FLAT])
def test_nearest_allowed_pose_fits_then_clamps_every_component(box: BoundingBox) -> None:
    outside = compose(box, Pose(scale=1.4, offset_x=0.2, offset_y=-0.3, rotation=25))
    nearest = nearest_allowed_pose(box, outside, TemplatePositionLimits())
    assert nearest == Pose(scale=1.1, offset_x=0.1, offset_y=-0.1, rotation=15)
    assert decompose(box, compose(box, nearest)).residual_pixels < 1e-7


@pytest.mark.parametrize(
    "pose",
    [Pose(scale=0.8, offset_x=-0.1, rotation=-15), Pose(scale=1.1, offset_y=0.1, rotation=15)],
)
def test_nearest_pose_leaves_allowed_boundary_unchanged(pose: Pose) -> None:
    box = compose(BOX, pose)
    nearest = nearest_allowed_pose(BOX, box, TemplatePositionLimits())
    np.testing.assert_allclose(pixels(compose(BOX, nearest)), pixels(box), atol=1e-7)
