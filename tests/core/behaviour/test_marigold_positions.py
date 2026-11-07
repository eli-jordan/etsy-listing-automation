"""Marigold scenes render a listing position with a fit of its posed quad
(spec *Rendering → Marigold (option B: a fit per position)*): never the
template's own maps, fitted once per distinct position and shared, waited
for while another caller fits it."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from etsy_listings.core.engine import build_plan
from etsy_listings.core.engine.stage import Blocked
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.preparation import position_fits
from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.core.workspace.template_state import template_state

from tests.support.builders import FIXTURE_LISTING, a_context, a_lock, copy_listing, edit_listing
from tests.support.marigold import listing_with_marigold, listing_with_prepared_marigold

POSE = Pose(scale=0.9, offset_x=0.05, offset_y=-0.04, rotation=10)


def position(workspace, pose: Pose = POSE) -> dict[str, object]:
    box = compose(template_state(workspace, "shirt").require().bounding_box, pose)
    return {"shirt": {"bounding_box": [point.model_dump() for point in box]}}


def plan(root: Path, listing: str = FIXTURE_LISTING):
    planned = build_plan(a_context(root), listing, a_lock(), (RenderStage(),))
    assert planned.plan.stage_plans[0].blocked is None, planned.plan.stage_plans[0].blocked
    return planned


def map_content(root: Path, listing: str = FIXTURE_LISTING) -> str:
    desired = RenderStage().desired(a_context(root), listing, None)
    assert not isinstance(desired, Blocked), desired
    return desired.works[0].recipe()["map_content"]


@pytest.fixture
def counted_fits(monkeypatch):
    calls = []
    real = position_fits.prepare

    def counting(*args, **kwargs):
        calls.append(args[1].box.tolist())
        return real(*args, **kwargs)

    monkeypatch.setattr(position_fits, "prepare", counting)
    return calls


def test_identical_positions_share_one_fit_and_only_positioned_scenes_change(
    workspace_root, counted_fits
):
    workspace = listing_with_prepared_marigold(workspace_root)
    unpositioned = map_content(workspace_root)
    edit_listing(workspace_root, template_positions=position(workspace))
    copy_listing(workspace_root, "twin")

    first = map_content(workspace_root)
    assert first != unpositioned
    assert map_content(workspace_root, "twin") == first
    plan(workspace_root)
    plan(workspace_root, "twin")
    assert len(counted_fits) == 1
    assert len(workspace.position_fits()) == 1

    # Another pose is another fit; removing the position restores the
    # template's own map identity, so its lockfile entry is unchanged.
    edit_listing(workspace_root, "twin", template_positions=position(workspace, Pose(scale=0.85)))
    assert map_content(workspace_root, "twin") not in (first, unpositioned)
    assert len(counted_fits) == 2
    edit_listing(workspace_root, "twin", template_positions=None)
    assert map_content(workspace_root, "twin") == unpositioned


def test_a_damaged_fit_is_refitted_rather_than_trusted(workspace_root, counted_fits):
    workspace = listing_with_prepared_marigold(workspace_root)
    edit_listing(workspace_root, template_positions=position(workspace))
    first = map_content(workspace_root)
    (key,) = workspace.position_fits()
    archive = workspace.position_fit(key) / "maps.npz"
    archive.write_bytes(archive.read_bytes()[:-16])
    position_fits._FITS.clear()
    assert map_content(workspace_root) == first
    assert len(counted_fits) == 2


def test_plan_waits_for_a_fit_already_running(workspace_root, monkeypatch):
    workspace = listing_with_prepared_marigold(workspace_root)
    edit_listing(workspace_root, template_positions=position(workspace))
    started, release = threading.Event(), threading.Event()
    calls = []
    real = position_fits.prepare

    def slow(*args, **kwargs):
        calls.append(1)
        started.set()
        assert release.wait(20)
        return real(*args, **kwargs)

    monkeypatch.setattr(position_fits, "prepare", slow)
    warming = threading.Thread(target=map_content, args=(workspace_root,))
    warming.start()
    assert started.wait(20)
    planned: list[str] = []
    planning = threading.Thread(target=lambda: planned.append(map_content(workspace_root)))
    planning.start()
    planning.join(0.5)
    assert planning.is_alive(), "plan must wait for the running fit, not use template maps"
    release.set()
    warming.join(20)
    planning.join(20)
    assert len(calls) == 1
    assert len(planned) == 1
    assert planned[0] == map_content(workspace_root)


def test_evidence_that_misses_the_position_blocks_the_plan(workspace_root):
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    edit_listing(workspace_root, template_positions=position(workspace))
    planned = build_plan(a_context(workspace_root), FIXTURE_LISTING, a_lock(), (RenderStage(),))
    refusal = planned.plan.stage_plans[0].blocked
    assert refusal is not None
    assert "cover listing positions" in refusal
    assert workspace.position_fits() == []
