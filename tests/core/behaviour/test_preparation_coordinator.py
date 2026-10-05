from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.preparation.runtime import Capability
from etsy_listings.core.render import load_template_config
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


class Runtime:
    def inspect(self):
        return Capability(True, None, "1.0.0", installation_id="test")


def template(workspace_root, name="shirt"):
    workspace = Workspace.discover(root_override=workspace_root)
    workspace.template_dir(name).mkdir()
    photo = Image.new("RGB", (64, 64), "white")
    ImageDraw.Draw(photo).rectangle((8, 8, 55, 55), fill="navy")
    photo.save(workspace.template_scene_image(name))
    config = load_template_config(
        {
            "kind": "single",
            "bounding_box": [{"x": x, "y": y} for x, y in [(12, 12), (51, 12), (51, 51), (12, 51)]],
            "renderer": {"type": "marigold", "config": {}},
        }
    )
    workspace.save_template_config(name, config)
    return workspace


def test_submission_deduplicates_and_cancelled_jobs_stay_cancelled_on_restart(workspace_root):
    workspace = template(workspace_root)
    coordinator = Preparations(workspace, runtime=Runtime())
    revision = CalibrationStore(workspace).read("shirt").revision
    job = coordinator.submit("shirt", config_revision=revision, request_id="one")
    assert job.phase == "queued"
    assert coordinator.submit("shirt", config_revision=revision, request_id="one").id == job.id
    assert coordinator.submit("shirt", config_revision=revision, request_id="two").id == job.id
    with pytest.raises(ValueError, match="request ID"):
        coordinator.submit(
            "shirt", config_revision=revision, request_id="one", action="prepare_again"
        )
    assert coordinator.cancel(job.id).phase == "cancelled"
    restarted = Preparations(workspace, runtime=Runtime())
    restarted.recover()
    assert restarted.status(job.id).phase == "cancelled"
    events = restarted.events(job.id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].phase == "cancelled"


def wait_terminal(coordinator, identity):
    import time

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = coordinator.status(identity)
        if job.phase in {"completed", "failed", "cancelled", "superseded"}:
            return job
        coordinator.events(identity, after=len(job.events), wait=0.1)
    raise AssertionError("Preparation did not finish")


@pytest.mark.parametrize("kind", ["single", "colour-matrix", "multiple"])
def test_explicit_preparation_publishes_every_required_placement(workspace_root, kind):
    from etsy_listings.core.preparation.artifacts import Artifacts

    from tests.support.marigold import PreparationRuntime

    workspace = template(workspace_root)
    config = workspace.load_template_config("shirt").model_dump(mode="json")
    config["kind"] = kind
    if kind == "colour-matrix":
        config.pop("colour", None)
        config.pop("artwork", None)
        workspace.template_scene_image("shirt").rename(workspace.template_dir("shirt") / "navy.png")
    if kind == "multiple":
        box = config.pop("bounding_box")
        config.pop("colour", None)
        config.pop("artwork", None)
        config["placements"] = [
            {"id": key, "colour": "Navy", "bounding_box": box} for key in ["left", "right"]
        ]
    workspace.save_template_config("shirt", load_template_config(config))
    runtime = PreparationRuntime()
    coordinator = Preparations(workspace, runtime=runtime)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="prepare",
    )
    coordinator.start()
    result = wait_terminal(coordinator, job.id)
    coordinator.close()
    assert result.phase == "completed", result.error
    store = Artifacts(workspace)
    inputs = store.saved_inputs("shirt")
    assert store.readiness("shirt", inputs).state == "ready"
    with store.acquire("shirt", inputs) as generation:
        assert set(generation.maps) == ({"left", "right"} if kind == "multiple" else {None})
    assert [call[0] for call in runtime.workers[0].calls] == ["normals", "lighting", "depth"]


def prepare_template(workspace_root):
    from tests.support.marigold import PreparationRuntime

    workspace = template(workspace_root)
    runtime = PreparationRuntime()
    coordinator = Preparations(workspace, runtime=runtime)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="prepare",
    )
    coordinator.start()
    result = wait_terminal(coordinator, job.id)
    assert result.phase == "completed", result.error
    return workspace, runtime, coordinator, result


def move_box(workspace, amount):
    store = CalibrationStore(workspace)
    current = store.read("shirt")
    config = current.config.model_copy(
        update={
            "bounding_box": tuple(
                point.model_copy(update={"x": point.x + amount})
                for point in current.config.bounding_box
            )
        }
    )
    return store.save(
        "shirt", config, expected_revision=current.revision, request_id="move" + str(amount)
    )


def test_save_reconciliation_rebuilds_covered_inputs_without_worker_or_installation(workspace_root):
    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    saved = move_box(workspace, 1)
    calls = len(runtime.workers[0].calls)
    runtime.capability = Capability(False, "Runtime removed")
    job = coordinator.reconcile_saved("shirt")
    assert job.kind == "rebuild"
    assert job.config_revision == saved.revision
    result = wait_terminal(coordinator, job.id)
    coordinator.close()
    assert result.phase == "completed", result.error
    assert len(runtime.workers[0].calls) == calls
    assert result.result["generation_id"] != first.result["generation_id"]


def test_save_without_covered_evidence_waits_for_explicit_prepare(workspace_root):
    workspace = template(workspace_root)
    runtime = Runtime()
    coordinator = Preparations(workspace, runtime=runtime)
    move_box(workspace, 1)
    assert coordinator.reconcile_saved("shirt") is None
    assert coordinator.list_jobs() == []


def test_startup_closes_gap_between_calibration_commit_and_cpu_job(workspace_root):
    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    coordinator.close()
    move_box(workspace, 1)
    restarted = Preparations(workspace, runtime=runtime)
    restarted.start()
    jobs = restarted.list_jobs()
    assert len(jobs) == 2
    result = wait_terminal(restarted, jobs[-1].id)
    restarted.close()
    assert result.kind == "rebuild"
    assert result.phase == "completed", result.error
    assert len(runtime.workers) == 1


def test_status_and_cancel_remain_available_during_another_runtime_probe(workspace_root):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from tests.support.marigold import PreparationRuntime

    workspace = template(workspace_root)
    template(workspace_root, "second")
    runtime = PreparationRuntime()
    coordinator = Preparations(workspace, runtime=runtime)
    first = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    entered = threading.Event()
    release = threading.Event()

    def inspect():
        entered.set()
        assert release.wait(10)
        return runtime.capability

    runtime.inspect = inspect
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(
            coordinator.submit,
            "second",
            config_revision=CalibrationStore(workspace).read("second").revision,
            request_id="second",
        )
        assert entered.wait(5)
        try:
            observed = executor.submit(coordinator.status, first.id).result(timeout=1)
            assert observed.phase == "queued"
            assert (
                executor.submit(coordinator.cancel, first.id).result(timeout=1).phase == "cancelled"
            )
        finally:
            release.set()
        assert pending.result().phase == "queued"
    coordinator.close()


def test_active_cancel_saves_current_role_and_retry_reuses_it_with_warm_worker(workspace_root):
    from tests.support.marigold import PreparationRuntime, PreparationWorker

    workspace = template(workspace_root)
    runtime = PreparationRuntime()
    worker = PreparationWorker(workspace.cache("preparation"))
    worker.release.clear()
    runtime.factory = lambda root: worker
    coordinator = Preparations(workspace, runtime=runtime)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    coordinator.start()
    assert worker.entered.wait(5)
    assert coordinator.cancel(job.id).phase == "cancelling"
    assert worker.cancelled
    worker.release.set()
    result = wait_terminal(coordinator, job.id)
    assert result.phase == "cancelled"
    assert len(result.evidence[0].predictions) == 1
    assert not worker.closed
    retry = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="retry",
        action="retry",
        previous_job=job.id,
    )
    assert wait_terminal(coordinator, retry.id).phase == "completed"
    coordinator.close()
    assert [call[0] for call in worker.calls] == ["normals", "lighting", "depth"]


def test_cancel_during_worker_startup_prevents_undispatched_model_call(workspace_root):
    from tests.support.marigold import PreparationRuntime, PreparationWorker

    workspace = template(workspace_root)
    runtime = PreparationRuntime()
    worker = PreparationWorker(workspace.cache("preparation"))
    worker.dispatch_release.clear()
    runtime.factory = lambda root: worker
    coordinator = Preparations(workspace, runtime=runtime)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    coordinator.start()
    assert worker.dispatch_entered.wait(5)
    assert coordinator.cancel(job.id).phase == "cancelling"
    worker.dispatch_release.set()
    assert wait_terminal(coordinator, job.id).phase == "cancelled"
    coordinator.close()
    assert worker.calls == []
    assert not workspace.template_map_current("shirt").exists()


class ProcessExit(BaseException):
    pass


@pytest.mark.parametrize(
    "step",
    [
        "mask_publication",
        "mask_committed",
        "fitting",
        "flattening",
        "baking",
        "lighting",
        "validated",
        "generation",
        "pointer",
    ],
)
def test_restart_at_cpu_mask_and_publication_checkpoints_finishes_coherently(workspace_root, step):
    import threading

    from etsy_listings.core.preparation.artifacts import Artifacts

    from tests.support.marigold import PreparationRuntime

    workspace = template(workspace_root)
    runtime = PreparationRuntime()
    exited = threading.Event()

    def crash(identity, checkpoint):
        if checkpoint == step:
            exited.set()
            raise ProcessExit()

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=crash)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    coordinator.start()
    assert exited.wait(10)
    with pytest.raises(ProcessExit):
        coordinator.close()
    restarted = Preparations(workspace, runtime=runtime)
    restarted.start()
    result = wait_terminal(restarted, job.id)
    restarted.close()
    assert result.phase == "completed", result.error
    assert (
        Artifacts(workspace).readiness("shirt", Artifacts(workspace).saved_inputs("shirt")).state
        == "ready"
    )
    assert sum(len(w.calls) for w in runtime.workers) == 3
