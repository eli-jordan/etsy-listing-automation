"""Photo warp scenes render at a listing's saved template position (spec:
*Rendering → Photo warp*, ADR-0058): the listing's box replaces the template's
in the layer's render config, so only scenes whose effective box changed
re-render, and the swatch still reads the template's own box."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.context import Event
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.plan import build_plan
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.render.config import BoundingBox
from etsy_listings.core.render.positions import Pose, compose

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, edit_listing
from tests.support.scenes import expected_scene

CHART = "colour-chart-01"
PLACEMENT = "fixture-placement-1"
FLAT = "flat-lay-01"
MEDIA = [
    *({"template": FLAT, "colour": colour} for colour in ("black", "blue-jean", "ivory", "moss")),
    {"template": CHART},
]


def _corners(box: BoundingBox) -> list[dict[str, float]]:
    return [point.model_dump() for point in box]


def _flat_box(root: Path, pose: Pose) -> BoundingBox:
    config = a_context(root).workspace.load_template_config(FLAT)
    return compose(config.bounding_box, pose)


def _placement_box(root: Path, pose: Pose) -> BoundingBox:
    config = a_context(root).workspace.load_template_config(CHART)
    placement = next(p for p in config.placements if p.id == PLACEMENT)
    return compose(placement.bounding_box, pose)


def _positions(
    flat: BoundingBox | None = None, placement: BoundingBox | None = None
) -> dict[str, object]:
    positions: dict[str, object] = {}
    if flat is not None:
        positions[FLAT] = {"bounding_box": _corners(flat)}
    if placement is not None:
        positions[CHART] = {"placements": {PLACEMENT: {"bounding_box": _corners(placement)}}}
    return positions


def _apply(root: Path, lock: Lockfile | None = None, events: list[Event] | None = None) -> Lockfile:
    ctx = a_context(root, on_event=events.append if events is not None else None)
    current = lock or a_lock()
    return execute(ctx, build_plan(ctx, LISTING, current, STAGES), current)


def _scene_states(root: Path, lock: Lockfile) -> dict[str, str]:
    ctx = a_context(root)
    planned = build_plan(ctx, LISTING, lock, STAGES)
    state = next(s for s in planned.states if s.stage.name == "render")
    stage = state.stage
    assert isinstance(stage, RenderStage)
    return {s.scene: s.state for s in stage.snapshot(state.desired, state.live).scenes}


def test_a_positioned_scene_renders_at_the_listing_box(workspace_root: Path) -> None:
    flat = _flat_box(workspace_root, Pose(scale=0.9, offset_x=0.05, rotation=8))
    placement = _placement_box(workspace_root, Pose(scale=1.05, offset_y=-0.05))
    edit_listing(workspace_root, media=MEDIA, template_positions=_positions(flat, placement))

    _apply(workspace_root)

    workspace = a_context(workspace_root).workspace
    design = {"black": "designs/take-a-hike.png", "moss": "designs/take-a-hike.png"}
    assert workspace.render_file(LISTING, FLAT, "black").read_bytes() == expected_scene(
        workspace_root, FLAT, "black", design, boxes={None: flat}
    )
    assert workspace.render_file(LISTING, CHART, None).read_bytes() == expected_scene(
        workspace_root, CHART, None, design, boxes={PLACEMENT: placement}
    )


def test_plan_is_a_no_op_while_positions_are_unchanged(workspace_root: Path) -> None:
    flat = _flat_box(workspace_root, Pose(scale=1.1, rotation=-5))
    edit_listing(workspace_root, media=MEDIA, template_positions=_positions(flat))
    lock = _apply(workspace_root)

    # Saved again unchanged, as the editor's PATCH does on an unrelated edit.
    edit_listing(workspace_root, template_positions=_positions(flat))
    planned = build_plan(a_context(workspace_root), LISTING, lock, STAGES)

    render = next(sp for sp in planned.plan.stage_plans if sp.stage == "render")
    assert render.will_run is False
    recorded = lock.applied["render"]["scene_config"][f"{FLAT}/black"]["layers"][0]
    assert json.loads(recorded["render_config"])["bounding_box"] == _corners(flat)


@pytest.mark.parametrize(
    ("edit", "stale"),
    [
        ("flat", {f"{FLAT}/{c}" for c in ("black", "blue-jean", "ivory", "moss")}),
        ("placement", {CHART}),
        ("reset", {f"{FLAT}/{c}" for c in ("black", "blue-jean", "ivory", "moss")}),
    ],
)
def test_a_position_change_re_renders_only_the_scenes_it_moves(
    workspace_root: Path, edit: str, stale: set[str]
) -> None:
    flat = _flat_box(workspace_root, Pose(scale=0.95))
    edit_listing(workspace_root, media=MEDIA, template_positions=_positions(flat))
    lock = _apply(workspace_root)

    if edit == "flat":
        changed = _positions(_flat_box(workspace_root, Pose(scale=0.95, offset_x=0.02)))
    elif edit == "placement":
        changed = _positions(flat, _placement_box(workspace_root, Pose(rotation=4)))
    else:
        changed = {}  # Reset to template removes the entry; the template box renders again.
    edit_listing(workspace_root, template_positions=changed)

    states = _scene_states(workspace_root, lock)
    assert {scene for scene, state in states.items() if state == "stale"} == stale
    assert {scene for scene, state in states.items() if state != "stale"} == set(states) - stale
    assert set(states.values()) <= {"stale", "cached"}


def test_the_swatch_keeps_sampling_the_templates_own_box(workspace_root: Path) -> None:
    """The swatch reads the garment's colour, not the print, so a listing's
    position must not move where it samples (plan PR 3)."""
    edit_listing(workspace_root, media=MEDIA)
    before: list[Event] = []
    lock = _apply(workspace_root, events=before)

    flat = _flat_box(workspace_root, Pose(scale=0.8, offset_x=0.1, offset_y=0.1, rotation=15))
    placement = _placement_box(workspace_root, Pose(scale=0.8, offset_x=-0.1, rotation=-15))
    edit_listing(workspace_root, template_positions=_positions(flat, placement))
    after: list[Event] = []
    _apply(workspace_root, lock, events=after)

    def swatches(events: list[Event]) -> dict[str, object]:
        return {e.message: e.swatches for e in events if e.message.startswith("rendered ")}

    assert len(swatches(after)) == len(MEDIA)
    assert swatches(after) == swatches(before)


def test_moving_one_placement_leaves_the_other_placements_pixels_alone(
    workspace_root: Path,
) -> None:
    """Compares the chart's right half before and after moving
    ``fixture-placement-1``. That half holds ``fixture-placement-2`` (x 614-836
    of 960), and placement 1 (x 134-356) cannot reach it at the default limits
    (scale ≤ 1.10, offset ±10%, tilt ±15°), so every pixel there must be
    unchanged while the left half moves."""
    edit_listing(workspace_root, media=MEDIA)
    lock = _apply(workspace_root)
    workspace = a_context(workspace_root).workspace
    with Image.open(workspace.render_file(LISTING, CHART, None)) as image:
        before = np.asarray(image.convert("RGB"))

    placement = _placement_box(workspace_root, Pose(scale=1.1, offset_x=0.1, rotation=15))
    edit_listing(workspace_root, template_positions=_positions(placement=placement))
    _apply(workspace_root, lock)
    with Image.open(workspace.render_file(LISTING, CHART, None)) as image:
        after = np.asarray(image.convert("RGB"))

    half = before.shape[1] // 2
    assert max(point.x for point in placement) < half
    assert np.array_equal(after[:, half:], before[:, half:])
    assert not np.array_equal(after[:, :half], before[:, :half])
