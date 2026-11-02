"""Evidence coverage for Marigold listing positions (spec *Rendering →
Marigold (option B)*, *Evidence coverage*): a template whose evidence does not
reach its padded quad gets background inference for that quad once, through
the preparation queue; its own published maps are unchanged."""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.config.settings import TemplatePositionLimits
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.position_fits import PositionFits, padded_quads
from etsy_listings.core.render import load_template_config
from etsy_listings.core.workspace import Workspace

from tests.support.marigold import PreparationRuntime, prepare_template

WIDER = TemplatePositionLimits.model_validate({"scale": {"max": 1.25}, "rotation": 25})


def small_print(workspace_root, name="tee") -> Workspace:
    """A 128px photo whose 32px box's own crop stops well short of the
    padded quad, so positions need coverage inference."""
    workspace = Workspace.discover(root_override=workspace_root)
    workspace.template_dir(name).mkdir()
    photo = Image.new("RGB", (128, 128), "white")
    ImageDraw.Draw(photo).rectangle((24, 24, 103, 103), fill="navy")
    photo.save(workspace.template_scene_image(name))
    box = [{"x": x, "y": y} for x, y in [(48, 48), (80, 48), (80, 80), (48, 80)]]
    config = {"kind": "single", "bounding_box": box, "renderer": {"type": "marigold"}}
    workspace.save_template_config(name, load_template_config(config))
    return workspace


def covered(workspace, name, limits) -> bool:
    inputs = Artifacts(workspace).saved_inputs(name)
    quads = padded_quads(workspace.load_template_config(name), limits)
    return quads is not None and PositionFits(workspace).covers(name, inputs, quads)


def run_to_end(coordinator: Preparations, job_id: str):
    deadline = time.monotonic() + 60
    while coordinator.status(job_id).phase not in {"completed", "failed", "cancelled"}:
        assert time.monotonic() < deadline, "coverage did not finish"
        coordinator.events(job_id, after=coordinator.status(job_id).last_event_sequence, wait=0.2)
    return coordinator.status(job_id)


def test_coverage_infers_the_padded_crop_once_and_keeps_the_template_maps(workspace_root):
    workspace = small_print(workspace_root)
    prepared = prepare_template(workspace, "tee")
    limits = TemplatePositionLimits()
    assert not covered(workspace, "tee", limits)

    runtime = PreparationRuntime()
    coordinator = Preparations(workspace, runtime=runtime)
    coordinator.start()
    try:
        job = coordinator.cover("tee", limits)
        assert job is not None
        assert job.kind == "coverage"
        assert coordinator.cover("tee", limits).id == job.id  # joins, never doubles
        finished = run_to_end(coordinator, job.id)
        assert finished.phase == "completed", finished.error
        assert covered(workspace, "tee", limits)
        assert coordinator.cover("tee", limits) is None
        # One crop, three roles, sized to the padded quad, not the box.
        assert len(runtime.workers[0].calls) == 3
        with Artifacts(workspace).acquire("tee", Artifacts(workspace).saved_inputs("tee")) as maps:
            assert maps.manifest.content_digest == prepared.result.content_digest
        # Wider limits than the evidence reaches need inference again.
        assert not covered(workspace, "tee", WIDER)
    finally:
        coordinator.close()


def test_a_template_already_covered_or_photo_warp_queues_nothing(workspace_root):
    from tests.support.marigold import marigold_template

    workspace = marigold_template(workspace_root)
    marigold_template(workspace_root, name="flat", renderer="photo-warp")
    prepare_template(workspace)
    coordinator = Preparations(workspace, runtime=PreparationRuntime())
    try:
        assert coordinator.cover("shirt", TemplatePositionLimits()) is None
        assert coordinator.cover("flat", TemplatePositionLimits()) is None
        assert coordinator.list_jobs(template="flat") == []
    finally:
        coordinator.close()
