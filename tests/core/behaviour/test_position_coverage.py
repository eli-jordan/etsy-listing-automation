"""Evidence coverage for Marigold listing positions (spec *Rendering →
Marigold (option B)*, *Evidence coverage*): a template whose evidence does not
reach its padded quad gets background inference for that quad once, through
the preparation queue; its own published maps are unchanged."""

from __future__ import annotations

import time

from etsy_listings.core.application.position_coverage import cover_prepared_templates
from etsy_listings.core.application.preparation.coordinator import (
    PreparationRequest,
    Preparations,
)
from etsy_listings.core.config.settings import TemplatePositionLimits
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.position_fits import PositionFits, padded_quads
from etsy_listings.core.workspace.calibration import CalibrationStore

from tests.support.marigold import (
    PreparationRuntime,
    marigold_template,
    prepare_template,
    small_print,
    wait_until,
)

WIDER = TemplatePositionLimits.model_validate({"scale": {"max": 1.25}, "rotation": 25})


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
    try:
        job = coordinator.cover("tee", limits)
        assert job is not None
        assert job.kind == "coverage"
        assert coordinator.cover("tee", limits).id == job.id  # joins, never doubles
        coordinator.start()
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


def test_a_finished_preparation_goes_on_to_cover_the_template(workspace_root):
    workspace = small_print(workspace_root)
    coordinator = Preparations(workspace, runtime=PreparationRuntime())
    coordinator.start()
    try:
        revision = CalibrationStore(workspace).read("tee").revision
        prepared = coordinator.submit(
            "tee", PreparationRequest(config_revision=revision, request_id="prepare-tee")
        )
        assert run_to_end(coordinator, prepared.id).phase == "completed"
        wait_until(lambda: len(coordinator.list_jobs(template="tee")) == 2, "coverage queueing")
        coverage = coordinator.list_jobs(template="tee")[1]
        assert coverage.kind == "coverage"
        assert run_to_end(coordinator, coverage.id).phase == "completed"
        assert covered(workspace, "tee", TemplatePositionLimits())
    finally:
        coordinator.close()


def test_catching_up_covers_only_prepared_marigold_templates(workspace_root):
    workspace = small_print(workspace_root)
    prepare_template(workspace, "tee")
    small_print(workspace_root, name="unprepared")
    marigold_template(workspace_root, name="flat", renderer="photo-warp")
    coordinator = Preparations(workspace, runtime=PreparationRuntime())
    try:
        jobs = cover_prepared_templates(coordinator)
        assert [(job.template, job.kind) for job in jobs] == [("tee", "coverage")]
    finally:
        coordinator.close()
