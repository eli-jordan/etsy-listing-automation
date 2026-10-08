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


def wait_checkpoint(coordinator, identity, reached):
    """Await a crash boundary under the same budget as ordinary job completion."""
    import sys
    import time
    import traceback

    deadline = time.monotonic() + 30
    while not reached.is_set():
        job = coordinator.status(identity)
        assert job.phase not in {"failed", "cancelled", "superseded", "completed"}, job.model_dump(
            mode="json"
        )
        if time.monotonic() >= deadline:
            stacks = {
                key: "".join(traceback.format_stack(frame))
                for key, frame in sys._current_frames().items()
            }
            raise AssertionError(
                f"Checkpoint not reached: {job.model_dump(mode='json')}; threads={stacks}"
            )
        coordinator.events(identity, after=job.last_event_sequence, wait=0.1)


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
        "predictions_staging",
        "predictions_validated",
        "predictions_pointer",
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


def multiple_template(workspace_root):
    workspace = template(workspace_root)
    document = workspace.load_template_config("shirt").model_dump(mode="json")
    box = document.pop("bounding_box")
    document.pop("colour")
    document.pop("artwork")
    document["kind"] = "multiple"
    document["placements"] = [
        {"id": key, "colour": "Navy", "bounding_box": box} for key in ["left", "right"]
    ]
    workspace.save_template_config("shirt", load_template_config(document))
    return workspace


def test_multiple_first_mask_crash_never_exposes_partial_maps_and_preserves_new_manual_edit(
    workspace_root,
):
    import threading

    from etsy_listings.core.workspace.calibration import MaskEdit, Stroke

    from tests.support.marigold import PreparationRuntime

    workspace = multiple_template(workspace_root)
    runtime = PreparationRuntime()
    exited = threading.Event()

    def crash(identity, step):
        if step == "mask_committed":
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
    assert not workspace.template_map_current("shirt").exists()
    assert workspace.template_mask_file("shirt", "left").exists()
    assert not workspace.template_mask_file("shirt", "right").exists()
    store = CalibrationStore(workspace)
    current = store.read("shirt")
    store.save(
        "shirt",
        current.config,
        expected_revision=current.revision,
        request_id="manual",
        mask_edits=[
            MaskEdit(
                placement_id="left",
                operations=[
                    Stroke(type="stroke", mode="mask", diameter_px=5, points=[(30, 30), (35, 35)])
                ],
            )
        ],
    )
    checksum = store.mask("shirt", "left").checksum
    restarted = Preparations(workspace, runtime=runtime)
    restarted.start()
    assert restarted.status(job.id).phase == "superseded"
    for record in restarted.list_jobs():
        if record.phase not in {"superseded", "completed"}:
            assert wait_terminal(restarted, record.id).phase == "completed"
    restarted.close()
    assert store.mask("shirt", "left").checksum == checksum
    assert len(runtime.workers[0].calls) == 3


def test_cpu_preparation_overlaps_next_template_gpu_work_with_serial_model_calls(workspace_root):
    import threading

    from tests.support.marigold import PreparationRuntime

    workspace = template(workspace_root)
    template(workspace_root, "second")
    runtime = PreparationRuntime()
    entered = threading.Event()
    release = threading.Event()

    def checkpoint(identity, step):
        if step == "fitting" and not entered.is_set():
            entered.set()
            assert release.wait(15)

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=checkpoint)
    first = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    coordinator.start()
    assert entered.wait(10)
    second = coordinator.submit(
        "second",
        config_revision=CalibrationStore(workspace).read("second").revision,
        request_id="second",
    )
    try:
        import time

        deadline = time.monotonic() + 10
        while len(runtime.workers[0].calls) < 6 and time.monotonic() < deadline:
            coordinator.events(second.id, after=len(coordinator.status(second.id).events), wait=0.1)
        assert len(runtime.workers) == 1
        assert [call[0] for call in runtime.workers[0].calls] == [
            "normals",
            "lighting",
            "depth",
        ] * 2
        assert coordinator.status(first.id).phase == "running"
    finally:
        release.set()
    assert wait_terminal(coordinator, first.id).phase == "completed"
    assert wait_terminal(coordinator, second.id).phase == "completed"
    coordinator.close()


def test_cleanup_preserves_last_complete_predictions_failed_retry_and_active_render(workspace_root):
    import json

    from etsy_listings.core.preparation.artifacts import Artifacts

    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    first_pointer = json.loads(workspace.preparation_prediction_current("shirt").read_bytes())
    worker = runtime.workers[0]
    worker.failure = RuntimeError("Worker exited unexpectedly; retry preparation")
    refresh = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="refresh",
        action="prepare_again",
    )
    assert wait_terminal(coordinator, refresh.id).phase == "failed"
    coordinator.cleanup("shirt")
    assert (
        json.loads(workspace.preparation_prediction_current("shirt").read_bytes())["id"]
        == first_pointer["id"]
    )
    assert workspace.preparation_work(refresh.id).exists()
    assert workspace.template_mask_file("shirt").exists()
    assert workspace.template_mask_file("shirt", source="automatic").exists()
    worker.failure = None
    artifacts = Artifacts(workspace)
    with artifacts.acquire("shirt", artifacts.saved_inputs("shirt")) as leased:
        retry = coordinator.submit(
            "shirt",
            config_revision=CalibrationStore(workspace).read("shirt").revision,
            request_id="retry",
            action="retry",
            previous_job=refresh.id,
        )
        result = wait_terminal(coordinator, retry.id)
        assert result.phase == "completed", result.error
        assert result.result["generation_id"] != leased.manifest.generation_id
        removed = coordinator.cleanup("shirt")
        assert removed["generations"] == []
    removed = coordinator.cleanup("shirt")
    assert removed["generations"] == [first.result["generation_id"]]
    coordinator.close()


def test_edits_during_model_work_stop_remaining_calls_without_new_inference_authorization(
    workspace_root,
):
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
    move_box(workspace, 1)
    worker.release.set()
    result = wait_terminal(coordinator, job.id)
    coordinator.close()
    assert result.phase == "superseded"
    assert [call[0] for call in worker.calls] == ["normals"]
    assert len(result.evidence[0].predictions) == 1
    assert len(coordinator.list_jobs()) == 1
    assert not workspace.template_map_current("shirt").exists()


def test_queued_cpu_rebuilds_coalesce_to_latest_saved_geometry(workspace_root):
    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    coordinator.close()
    queued = Preparations(workspace, runtime=runtime)
    move_box(workspace, 1)
    obsolete = queued.reconcile_saved("shirt")
    move_box(workspace, 2)
    latest = queued.reconcile_saved("shirt")
    assert queued.status(obsolete.id).phase == "superseded"
    assert latest.id != obsolete.id
    queued.start()
    assert wait_terminal(queued, latest.id).phase == "completed"
    queued.close()
    assert len(runtime.workers) == 1
    assert len(runtime.workers[0].calls) == 3


def test_new_photo_refuses_old_masks_without_reinterpreting_corrections(workspace_root):
    from etsy_listings.core.workspace.calibration import MaskUnavailable

    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    before = workspace.template_mask_file("shirt").read_bytes()
    Image.new("RGB", (64, 64), "red").save(workspace.template_scene_image("shirt"))
    with pytest.raises(MaskUnavailable):
        coordinator.reconcile_saved("shirt")
    assert workspace.template_mask_file("shirt").read_bytes() == before
    assert len(runtime.workers[0].calls) == 3
    coordinator.close()


def test_inference_setting_change_requires_prepare_and_missing_runtime_is_actionable(
    workspace_root,
):
    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    current = CalibrationStore(workspace).read("shirt")
    document = current.config.model_dump(mode="json")
    document["renderer"]["config"]["inference"]["ensemble_size"] = 2
    saved = CalibrationStore(workspace).save(
        "shirt",
        load_template_config(document),
        expected_revision=current.revision,
        request_id="settings",
    )
    assert coordinator.reconcile_saved("shirt") is None
    runtime.capability = Capability(False, "Run etsy-listings marigold setup")
    with pytest.raises(ValueError, match="marigold setup"):
        coordinator.submit("shirt", config_revision=saved.revision, request_id="changed")
    assert len(coordinator.list_jobs()) == 1
    coordinator.close()


def test_model_lighting_component_order_preserves_estimated_shading_gradient(workspace_root):
    import numpy as np

    from etsy_listings.core.preparation.artifacts import Artifacts
    from etsy_listings.core.render import MarigoldAppearance, MaterialLayer, render_marigold_scene

    from tests.support.marigold import PreparationRuntime, PreparationWorker

    class DistinctLighting(PreparationWorker):
        def infer(self, **request):
            result = super().infer(**request)
            if request["role"] == "lighting":
                path = self.root / request["output"]
                width, height = request["size"]
                prediction = np.zeros((3, height, width, 3), np.float32)
                prediction[0] = 0.25  # Worker channel zero is albedo.
                prediction[1] = np.linspace(0.2, 0.8, width, dtype=np.float32)[None, :, None]
                np.savez_compressed(path, prediction=prediction)
                import hashlib

                result["checksum"] = hashlib.sha256(path.read_bytes()).hexdigest()
            return result

    workspace = template(workspace_root)
    runtime = PreparationRuntime()
    runtime.factory = DistinctLighting
    coordinator = Preparations(workspace, runtime=runtime)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="distinct",
    )
    coordinator.start()
    result = wait_terminal(coordinator, job.id)
    coordinator.close()
    assert result.phase == "completed", result.error
    artifacts = Artifacts(workspace)
    with artifacts.acquire("shirt", artifacts.saved_inputs("shirt")) as acquired:
        maps = acquired.maps[None]
        assert maps.estimated[30, 40, 0] > maps.estimated[30, 20, 0] * 1.4
        image = render_marigold_scene(
            np.zeros((64, 64, 3), np.uint8),
            [MaterialLayer(np.full((8, 8, 4), 255, np.uint8), maps)],
            appearance=MarigoldAppearance(fabric_texture=0, print_shine=0),
        )
        assert image.getpixel((40, 30))[0] > image.getpixel((20, 30))[0] + 25


def test_other_jobs_remain_responsive_while_save_verifies_maps(workspace_root):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from etsy_listings.core.preparation.artifacts import Artifacts

    workspace, runtime, initial, first = prepare_template(workspace_root)
    initial.close()
    template(workspace_root, "second")
    move_box(workspace, 1)
    entered = threading.Event()
    release = threading.Event()

    class HeldArtifacts(Artifacts):
        def readiness(self, *args, **kwargs):
            entered.set()
            assert release.wait(10)
            return super().readiness(*args, **kwargs)

    coordinator = Preparations(workspace, runtime=runtime, artifacts=HeldArtifacts(workspace))
    other = coordinator.submit(
        "second",
        config_revision=CalibrationStore(workspace).read("second").revision,
        request_id="other",
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(coordinator.reconcile_saved, "shirt")
        assert entered.wait(5)
        try:
            assert executor.submit(coordinator.status, other.id).result(timeout=1).phase == "queued"
            assert (
                executor.submit(coordinator.cancel, other.id).result(timeout=1).phase == "cancelled"
            )
        finally:
            release.set()
        assert pending.result().kind == "rebuild"
    coordinator.close()


def test_cleanup_cannot_remove_an_active_prediction_replacement(workspace_root):
    import json
    import threading

    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    coordinator.close()
    before = json.loads(workspace.preparation_prediction_current("shirt").read_bytes())["id"]
    staged = threading.Event()
    release = threading.Event()

    def checkpoint(identity, step):
        if step == "predictions_staging":
            staged.set()
            assert release.wait(10)

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=checkpoint)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="refresh",
        action="prepare_again",
    )
    coordinator.start()
    assert staged.wait(10)
    try:
        replacement = set(workspace.preparation_prediction_sets("shirt")) - {before}
        assert len(replacement) == 1
        coordinator.cleanup("shirt")
        assert replacement <= set(workspace.preparation_prediction_sets("shirt"))
        assert workspace.preparation_prediction_set("shirt", before).exists()
    finally:
        release.set()
    assert wait_terminal(coordinator, job.id).phase == "completed"
    coordinator.close()
    assert not workspace.preparation_prediction_set("shirt", before).exists()


def test_later_complete_replacement_retires_historical_cancelled_and_failed_predictions(
    workspace_root,
):
    import json

    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    worker = runtime.workers[0]
    previous = json.loads(workspace.preparation_prediction_current("shirt").read_bytes())["id"]
    worker.entered.clear()
    worker.release.clear()
    cancelled = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="cancel",
        action="prepare_again",
    )
    assert worker.entered.wait(5)
    coordinator.cancel(cancelled.id)
    worker.release.set()
    assert wait_terminal(coordinator, cancelled.id).phase == "cancelled"
    assert coordinator.status(cancelled.id).evidence
    worker.failure = RuntimeError("worker failed")
    failed = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="fail",
        action="prepare_again",
    )
    assert wait_terminal(coordinator, failed.id).phase == "failed"
    assert workspace.preparation_prediction_set("shirt", previous).exists()
    worker.failure = None
    replacement = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="replace",
        action="prepare_again",
    )
    assert wait_terminal(coordinator, replacement.id).phase == "completed"
    coordinator.close()
    assert coordinator.status(cancelled.id).evidence == ()
    assert coordinator.status(failed.id).evidence == ()
    assert not workspace.preparation_work(cancelled.id).exists()
    assert not workspace.preparation_work(failed.id).exists()
    assert not workspace.preparation_prediction_set("shirt", previous).exists()
    assert len(workspace.preparation_prediction_sets("shirt")) == 1


def test_queue_order_and_worker_installation_are_pinned_across_restart_update(workspace_root):
    from dataclasses import replace

    from tests.support.marigold import PreparationRuntime

    workspace = template(workspace_root)
    template(workspace_root, "second")
    runtime = PreparationRuntime()
    selections = []
    original_worker = runtime.worker

    def worker(selected, **options):
        selections.append((selected.engine_version, selected.installation_id))
        return original_worker(selected, **options)

    runtime.worker = worker
    coordinator = Preparations(workspace, runtime=runtime)
    first = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    second = coordinator.submit(
        "second",
        config_revision=CalibrationStore(workspace).read("second").revision,
        request_id="second",
    )
    coordinator.close()
    runtime.capability = replace(runtime.capability, engine_version="2.0.0", installation_id="new")
    restarted = Preparations(workspace, runtime=runtime)
    assert [j.id for j in restarted.list_jobs()] == [first.id, second.id]
    restarted.start()
    assert wait_terminal(restarted, first.id).phase == "completed"
    assert wait_terminal(restarted, second.id).phase == "completed"
    restarted.close()
    assert selections == [("1.0.0", "test")]
    inputs = [call[1] for call in runtime.workers[0].calls]
    assert all(first.id in path for path in inputs[:3])
    assert all(second.id in path for path in inputs[3:])


def test_restart_revalidates_corrupted_partial_prediction_and_only_restarts_that_call(
    workspace_root,
):
    import threading

    from tests.support.marigold import PreparationRuntime

    workspace = template(workspace_root)
    runtime = PreparationRuntime()
    entered = threading.Event()

    def crash(identity, step):
        if step == "normals_saved":
            entered.set()
            raise ProcessExit()

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=crash)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    coordinator.start()
    assert entered.wait(10)
    with pytest.raises(ProcessExit):
        coordinator.close()
    prediction = coordinator.status(job.id).evidence[0].predictions[0]
    (workspace.cache("preparation") / prediction.path).write_bytes(b"damaged archive")
    restarted = Preparations(workspace, runtime=runtime)
    restarted.start()
    result = wait_terminal(restarted, job.id)
    restarted.close()
    assert result.phase == "completed", result.error
    assert [call[0] for w in runtime.workers for call in w.calls] == [
        "normals",
        "normals",
        "lighting",
        "depth",
    ]


def test_geometry_save_during_cpu_phase_refuses_old_publication_and_rebuilds_latest(workspace_root):
    import threading

    workspace, runtime, initial, first = prepare_template(workspace_root)
    initial.close()
    entered = threading.Event()
    release = threading.Event()

    def checkpoint(identity, step):
        if step == "flattening" and not entered.is_set():
            entered.set()
            assert release.wait(10)

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=checkpoint)
    move_box(workspace, 1)
    old = coordinator.reconcile_saved("shirt")
    coordinator.start()
    assert entered.wait(10)
    move_box(workspace, 2)
    latest = coordinator.reconcile_saved("shirt")
    release.set()
    assert wait_terminal(coordinator, old.id).phase == "superseded"
    result = wait_terminal(coordinator, latest.id)
    coordinator.close()
    assert result.phase == "completed", result.error
    assert len(runtime.workers) == 1
    assert len(runtime.workers[0].calls) == 3


def test_cpu_cancel_stops_at_phase_boundary_and_is_persisted(workspace_root):
    import threading

    workspace, runtime, initial, first = prepare_template(workspace_root)
    initial.close()
    entered = threading.Event()
    release = threading.Event()

    def checkpoint(identity, step):
        if step == "flattening":
            entered.set()
            assert release.wait(10)

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=checkpoint)
    move_box(workspace, 1)
    job = coordinator.reconcile_saved("shirt")
    coordinator.start()
    assert entered.wait(10)
    assert coordinator.cancel(job.id).cancel_intent
    release.set()
    assert wait_terminal(coordinator, job.id).phase == "cancelled"
    coordinator.close()
    restarted = Preparations(workspace, runtime=runtime)
    restarted.recover()
    assert restarted.status(job.id).phase == "cancelled"
    assert len(restarted.list_jobs()) == 2
    restarted.close()


def test_request_receipts_do_not_emit_duplicate_step_events(workspace_root):
    workspace = template(workspace_root)
    coordinator = Preparations(workspace, runtime=Runtime())
    revision = CalibrationStore(workspace).read("shirt").revision
    first = coordinator.submit("shirt", config_revision=revision, request_id="first")
    for number in range(10):
        assert (
            coordinator.submit("shirt", config_revision=revision, request_id=str(number)).id
            == first.id
        )
    assert coordinator.status(first.id).last_event_sequence == 1
    assert coordinator.events(first.id, after=1) == ()
    with pytest.raises(ValueError, match="resync"):
        coordinator.events(first.id, after=2)
    coordinator.close()


def test_prepare_again_refreshes_models_even_with_matching_active_cpu_rebuild(workspace_root):
    import threading

    workspace, runtime, initial, first = prepare_template(workspace_root)
    initial.close()
    entered = threading.Event()
    release = threading.Event()

    def checkpoint(identity, step):
        if step == "flattening" and not entered.is_set():
            entered.set()
            assert release.wait(10)

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=checkpoint)
    saved = move_box(workspace, 1)
    rebuilding = coordinator.reconcile_saved("shirt")
    coordinator.start()
    assert entered.wait(10)
    try:
        assert (
            coordinator.submit("shirt", config_revision=saved.revision, request_id="ordinary").id
            == rebuilding.id
        )
        refresh = coordinator.submit(
            "shirt", config_revision=saved.revision, request_id="fresh", action="prepare_again"
        )
        assert refresh.id != rebuilding.id
    finally:
        release.set()
    assert wait_terminal(coordinator, refresh.id).phase == "completed"
    assert wait_terminal(coordinator, rebuilding.id).phase == "completed"
    coordinator.close()
    assert sum(len(w.calls) for w in runtime.workers) == 6


def test_invalid_current_map_pointer_does_not_prevent_explicit_preparation_repair(workspace_root):
    import json

    from etsy_listings.core.preparation.artifacts import Artifacts

    workspace, runtime, initial, first = prepare_template(workspace_root)
    initial.close()
    pointer = json.loads(workspace.template_map_current("shirt").read_bytes())
    pointer["schema_version"] = 2
    workspace.template_map_current("shirt").write_text(json.dumps(pointer), encoding="utf-8")
    coordinator = Preparations(workspace, runtime=runtime)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="repair",
    )
    coordinator.start()
    result = wait_terminal(coordinator, job.id)
    coordinator.close()
    assert result.phase == "completed", result.error
    assert (
        Artifacts(workspace)
        .readiness("shirt", Artifacts(workspace).saved_inputs("shirt"))
        .can_render
    )
    assert len(runtime.workers) == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_explicit_photo_reset_is_durable_and_cancellation_preserves_old_masks(
    workspace_root, cancel
):
    from etsy_listings.core.preparation.artifacts import Artifacts
    from etsy_listings.core.workspace.calibration import MaskPhotoMismatch

    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    coordinator.close()
    before = workspace.template_mask_file("shirt").read_bytes()
    Image.new("RGB", (64, 64), "red").save(workspace.template_scene_image("shirt"))
    coordinator = Preparations(workspace, runtime=runtime)
    revision = CalibrationStore(workspace).read("shirt").revision
    with pytest.raises(MaskPhotoMismatch):
        coordinator.submit("shirt", config_revision=revision, request_id="ordinary")
    with pytest.raises(ValueError, match="Prepare again"):
        coordinator.submit(
            "shirt", config_revision=revision, request_id="wrong", reset_masks_for_photo=True
        )
    job = coordinator.submit(
        "shirt",
        config_revision=revision,
        request_id="reset",
        action="prepare_again",
        reset_masks_for_photo=True,
    )
    assert job.reset_masks_for_photo
    assert all(p.mask == "0" * 64 for p in job.snapshot.placements)
    assert not workspace.preparation_work(job.id, "mask-.png").exists()
    with pytest.raises(ValueError, match="request ID"):
        coordinator.submit(
            "shirt", config_revision=revision, request_id="reset", action="prepare_again"
        )
    if cancel:
        coordinator.cancel(job.id)
        assert workspace.template_mask_file("shirt").read_bytes() == before
        coordinator = Preparations(workspace, runtime=runtime)
        coordinator.recover()
        assert coordinator.status(job.id).phase == "cancelled"
        job = coordinator.submit(
            "shirt",
            config_revision=revision,
            request_id="retry",
            action="retry",
            previous_job=job.id,
        )
        assert job.reset_masks_for_photo
    coordinator.start()
    result = wait_terminal(coordinator, job.id)
    coordinator.close()
    assert result.phase == "completed", result.error
    assert CalibrationStore(workspace).mask("shirt").edited != before
    artifacts = Artifacts(workspace)
    assert artifacts.readiness("shirt", artifacts.saved_inputs("shirt")).state == "ready"


@pytest.mark.parametrize("change", ["none", "edit", "photo"])
def test_photo_reset_partial_multiple_install_recovers_only_exact_inputs(workspace_root, change):
    import threading

    from etsy_listings.core.preparation.artifacts import Artifacts
    from etsy_listings.core.workspace.calibration import MaskEdit, Stroke

    from tests.support.marigold import PreparationRuntime

    workspace = multiple_template(workspace_root)
    runtime = PreparationRuntime()
    coordinator = Preparations(workspace, runtime=runtime)
    first = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="first",
    )
    coordinator.start()
    assert wait_terminal(coordinator, first.id).phase == "completed"
    coordinator.close()
    old_pointer = workspace.template_map_current("shirt").read_bytes()
    Image.new("RGB", (64, 64), "red").save(workspace.template_scene_image("shirt"))
    exited = threading.Event()

    def crash(identity, step):
        if step == "mask_committed":
            exited.set()
            raise ProcessExit()

    coordinator = Preparations(workspace, runtime=runtime, checkpoint=crash)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="reset",
        action="prepare_again",
        reset_masks_for_photo=True,
    )
    coordinator.start()
    wait_checkpoint(coordinator, job.id, exited)
    with pytest.raises(ProcessExit):
        coordinator.close()
    assert workspace.template_map_current("shirt").read_bytes() == old_pointer
    store = CalibrationStore(workspace)
    if change == "edit":
        current = store.read("shirt")
        store.save(
            "shirt",
            current.config,
            expected_revision=current.revision,
            request_id="edit",
            mask_edits=[
                MaskEdit(
                    placement_id="left",
                    operations=[
                        Stroke(type="stroke", mode="mask", diameter_px=5, points=[(30, 30)])
                    ],
                )
            ],
        )
    if change == "photo":
        Image.new("RGB", (64, 64), "green").save(workspace.template_scene_image("shirt"))
    preserved = workspace.template_mask_file("shirt", "left").read_bytes()
    restarted = Preparations(workspace, runtime=runtime)
    restarted.start()
    result = wait_terminal(restarted, job.id)
    restarted.close()
    assert result.phase == ("completed" if change == "none" else "superseded"), result.error
    if change != "none":
        assert workspace.template_mask_file("shirt", "left").read_bytes() == preserved
        assert workspace.template_map_current("shirt").read_bytes() == old_pointer
    else:
        artifacts = Artifacts(workspace)
        assert artifacts.readiness("shirt", artifacts.saved_inputs("shirt")).state == "ready"


def test_photo_reset_intent_preserves_same_photo_manual_mask(workspace_root):
    from etsy_listings.core.workspace.calibration import MaskEdit, Stroke

    workspace, runtime, coordinator, first = prepare_template(workspace_root)
    store = CalibrationStore(workspace)
    current = store.read("shirt")
    saved = store.save(
        "shirt",
        current.config,
        expected_revision=current.revision,
        request_id="manual",
        mask_edits=[
            MaskEdit(
                operations=[Stroke(type="stroke", mode="mask", diameter_px=5, points=[(30, 30)])]
            )
        ],
    )
    checksum = store.mask("shirt").checksum
    job = coordinator.submit(
        "shirt",
        config_revision=saved.revision,
        request_id="refresh",
        action="prepare_again",
        reset_masks_for_photo=True,
    )
    assert job.snapshot.placements[0].mask == checksum
    result = wait_terminal(coordinator, job.id)
    coordinator.close()
    assert result.phase == "completed", result.error
    assert store.mask("shirt").checksum == checksum


def test_checkpoint_wait_reports_terminal_model_failure(workspace_root):
    import threading

    from tests.support.marigold import PreparationRuntime, PreparationWorker

    workspace = template(workspace_root)
    runtime = PreparationRuntime()

    def failed_worker(root):
        worker = PreparationWorker(root)
        worker.failure = ValueError("diagnostic model refusal")
        return worker

    runtime.factory = failed_worker
    coordinator = Preparations(workspace, runtime=runtime)
    job = coordinator.submit(
        "shirt",
        config_revision=CalibrationStore(workspace).read("shirt").revision,
        request_id="failure",
    )
    coordinator.start()
    try:
        with pytest.raises(AssertionError, match="diagnostic model refusal"):
            wait_checkpoint(coordinator, job.id, threading.Event())
    finally:
        coordinator.close()
