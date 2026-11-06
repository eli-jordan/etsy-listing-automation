"""Position refusals agree through pure validation and the public plan path."""

from pathlib import Path

import pytest

from etsy_listings.core.config.listing_validation import (
    CheckInputs,
    check_listing,
    check_template_positions,
)
from etsy_listings.core.config.settings import TemplatePositionLimits
from etsy_listings.core.engine.plan import build_plan
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.render.config import load_template_config
from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.core.workspace.calibration import CalibrationStore
from etsy_listings.core.workspace.template_state import template_state

from tests.support.builders import FIXTURE_LISTING, a_context, a_lock, edit_listing

TEMPLATE = "flat-lay-01"
KEY = f"{FIXTURE_LISTING}: template_positions.{TEMPLATE}"


def assert_plan_refuses(ctx, expected: str) -> None:
    planned = build_plan(ctx, FIXTURE_LISTING, a_lock(), STAGES)
    render = next(stage for stage in planned.plan.stage_plans if stage.stage == "render")
    assert render.blocked == expected


@pytest.mark.parametrize(
    ("pose", "message"),
    [
        (Pose(scale=1.18), "scales the design to 1.18; the limit is 0.80–1.10"),
        (Pose(scale=0.7), "scales the design to 0.70"),
        (Pose(offset_x=0.11), "horizontal offset"),
        (Pose(offset_y=-0.11), "vertical offset"),
        (Pose(rotation=16), "rotation"),
    ],
)
def test_limits_refuse_in_validation_and_plan(
    workspace_root: Path, pose: Pose, message: str
) -> None:
    ctx = a_context(workspace_root)
    config = template_state(ctx.workspace, TEMPLATE).require()
    box = compose(config.bounding_box, pose)
    position = {TEMPLATE: {"bounding_box": [point.model_dump() for point in box]}}
    edit_listing(workspace_root, template_positions=position)
    listing = ctx.workspace.load_listing(FIXTURE_LISTING)
    issues = check_template_positions(
        listing, {TEMPLATE: config}, TemplatePositionLimits(), name=FIXTURE_LISTING
    )
    assert issues[0].message.startswith(KEY)
    assert message in issues[0].message
    assert_plan_refuses(ctx, issues[0].message)


@pytest.mark.parametrize("change", ["limits", "recalibration"])
def test_current_limits_and_recalibration_revalidate_without_rewriting_positions(
    workspace_root: Path,
    change: str,
) -> None:
    ctx = a_context(workspace_root)
    template = template_state(ctx.workspace, TEMPLATE).require()
    position = compose(template.bounding_box, Pose(scale=1.1))
    edit_listing(
        workspace_root,
        template_positions={TEMPLATE: {"bounding_box": [point.model_dump() for point in position]}},
    )
    original = ctx.workspace.listing_file(FIXTURE_LISTING).read_bytes()
    planned = build_plan(ctx, FIXTURE_LISTING, a_lock(), STAGES)
    assert (
        next(stage for stage in planned.plan.stage_plans if stage.stage == "render").blocked is None
    )
    if change == "limits":
        ctx.workspace.settings_file().write_bytes(b"template_positions:\n  scale: {max: 1.0}\n")
    else:
        CalibrationStore(ctx.workspace).write_config(
            TEMPLATE,
            template.model_copy(
                update={"bounding_box": compose(template.bounding_box, Pose(scale=2))}
            ),
        )
    listing = ctx.workspace.load_listing(FIXTURE_LISTING)
    config = template_state(ctx.workspace, TEMPLATE).require()
    issues = check_template_positions(
        listing,
        {TEMPLATE: config},
        ctx.workspace.load_settings().template_positions,
        name=FIXTURE_LISTING,
    )
    assert "scales the design" in issues[0].message
    assert_plan_refuses(ctx, issues[0].message)
    assert ctx.workspace.listing_file(FIXTURE_LISTING).read_bytes() == original


def test_listing_health_check_includes_positions_with_the_supplied_limits(
    workspace_root: Path,
) -> None:
    from etsy_listings.core.workspace.facts import template_info

    ctx = a_context(workspace_root)
    template = template_state(ctx.workspace, TEMPLATE).require()
    box = compose(template.bounding_box, Pose(scale=1.1))
    edit_listing(
        workspace_root,
        template_positions={TEMPLATE: {"bounding_box": [point.model_dump() for point in box]}},
    )
    listing = ctx.workspace.load_listing(FIXTURE_LISTING)
    inputs = CheckInputs(
        garment_profile=None,
        garment_profile_names=(),
        templates={TEMPLATE: template_info(ctx.workspace, TEMPLATE, template)},
        template_position_limits=TemplatePositionLimits.model_validate({"scale": {"max": 1}}),
        listing_name=FIXTURE_LISTING,
    )
    issues = check_listing(listing, inputs, design_paths={})
    assert any(issue.message.startswith(KEY) and "1.00" in issue.message for issue in issues)


def shape_case(case: str, box):
    renderer = {"type": "marigold" if case.startswith("marigold") else "photo-warp"}
    template = {"kind": "single", "bounding_box": box, "renderer": renderer}
    position = {TEMPLATE: {"bounding_box": box}}
    if case == "shear":
        changed = [dict(point) for point in box]
        changed[0]["x"] += 20
        position = {TEMPLATE: {"bounding_box": changed}}
    if case in {"stale-placement", "box-on-multiple"}:
        template = {
            "kind": "multiple",
            "placements": [{"id": "left", "colour": "black", "bounding_box": box}],
            "renderer": renderer,
        }
    if case in {"stale-placement", "placements-on-single"}:
        position = {TEMPLATE: {"placements": {"gone": {"bounding_box": box}}}}
    if case == "stale-template":
        position = {"unused": {"bounding_box": box}}
    return load_template_config(template), position


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("shear", "not a plain move, resize or tilt"),
        ("stale-template", "not in media"),
        ("stale-placement", "placements.gone names a placement that no longer exists"),
        ("placements-on-single", "placements on a single template"),
        ("box-on-multiple", "bounding_box on a multiple template"),
    ],
)
def test_shape_and_membership_refuse_in_validation_and_plan(
    workspace_root: Path,
    case: str,
    message: str,
) -> None:
    ctx = a_context(workspace_root)
    original = template_state(ctx.workspace, TEMPLATE).require()
    config, position = shape_case(case, [point.model_dump() for point in original.bounding_box])
    CalibrationStore(ctx.workspace).write_config(TEMPLATE, config)
    edit_listing(workspace_root, media=[{"template": TEMPLATE}], template_positions=position)
    listing = ctx.workspace.load_listing(FIXTURE_LISTING)
    issues = check_template_positions(
        listing, {TEMPLATE: config}, TemplatePositionLimits(), name=FIXTURE_LISTING
    )
    assert message in issues[0].message
    assert_plan_refuses(ctx, issues[0].message)


def test_marigold_positions_validate_like_photo_warp_ones(workspace_root: Path) -> None:
    """Spec rule 5 is lifted (option B): a Marigold position is refused only
    for what refuses any position, and a limits change lists it."""
    from etsy_listings.core.config.listing_validation import positions_outside_limits

    ctx = a_context(workspace_root)
    original = template_state(ctx.workspace, TEMPLATE).require()
    config, _ = shape_case("marigold", [point.model_dump() for point in original.bounding_box])
    box = compose(config.bounding_box, Pose(scale=1.05, rotation=10))
    edit_listing(
        workspace_root,
        media=[{"template": TEMPLATE}],
        template_positions={TEMPLATE: {"bounding_box": [point.model_dump() for point in box]}},
    )
    listing = ctx.workspace.load_listing(FIXTURE_LISTING)
    assert check_template_positions(listing, {TEMPLATE: config}, TemplatePositionLimits()) == []
    narrow = TemplatePositionLimits.model_validate({"rotation": 5})
    assert "rotation 10" in check_template_positions(listing, {TEMPLATE: config}, narrow)[0].message
    assert positions_outside_limits(listing, {TEMPLATE: config}, narrow) == [
        f"template_positions.{TEMPLATE}"
    ]


def test_unreadable_settings_refuse_a_positioned_listing_instead_of_raising(
    workspace_root: Path,
) -> None:
    ctx = a_context(workspace_root)
    template = template_state(ctx.workspace, TEMPLATE).require()
    box = compose(template.bounding_box, Pose(scale=1.05))
    edit_listing(
        workspace_root,
        template_positions={TEMPLATE: {"bounding_box": [point.model_dump() for point in box]}},
    )
    ctx.workspace.settings_file().write_bytes(b"template_positions:\n  rotation: lots\n")
    planned = build_plan(ctx, FIXTURE_LISTING, a_lock(), STAGES)
    render = next(stage for stage in planned.plan.stage_plans if stage.stage == "render")
    assert render.blocked is not None
    assert "settings.yaml" in render.blocked
    assert "template_positions.rotation" in render.blocked
