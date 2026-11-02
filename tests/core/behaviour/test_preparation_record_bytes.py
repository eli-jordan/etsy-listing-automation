"""The exact JSON preparation writes for its durable records.

Map pointers, generation manifests, prediction pointers and job journals
already on disk must keep loading, and generation identity must not move, so
these pin each record's keys, values and canonical serialisation."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from etsy_listings.core.application.preparation.coordinator import PreparationRequest, Preparations
from etsy_listings.core.application.preparation.models import Job
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.render import load_template_config
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore

from tests.support.marigold import PreparationRuntime, material_maps, preparation_inputs


def canonical(data: bytes) -> bytes:
    """``data`` re-serialised the way every one of these records is written."""
    document = json.loads(data)
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _template(root: Path) -> Workspace:
    workspace = Workspace.discover(root_override=root)
    workspace.template_dir("shirt").mkdir()
    photo = Image.new("RGB", (64, 64), "white")
    ImageDraw.Draw(photo).rectangle((8, 8, 55, 55), fill="navy")
    photo.save(workspace.template_scene_image("shirt"))
    box = [{"x": x, "y": y} for x, y in [(12, 12), (51, 12), (51, 51), (12, 51)]]
    workspace.save_template_config(
        "shirt",
        load_template_config(
            {"kind": "single", "bounding_box": box, "renderer": {"type": "marigold", "config": {}}}
        ),
    )
    return workspace


@pytest.fixture
def prepared(workspace_root: Path) -> tuple[Workspace, list[bytes]]:
    """A template prepared through the coordinator, and every journal it wrote."""
    workspace = _template(workspace_root)
    journals: list[bytes] = []
    coordinator = Preparations(workspace, runtime=PreparationRuntime())
    write = coordinator.store.write

    def recording(job: Job, **changes: object) -> Job:
        written = write(job, **changes)
        journals.append(workspace.preparation_job_file(written.id).read_bytes())
        return written

    coordinator.store.write = recording  # type: ignore[method-assign]  # -- observe each journal write
    revision = CalibrationStore(workspace).read("shirt").revision
    job = coordinator.submit(
        "shirt", PreparationRequest(config_revision=revision, request_id="prepare")
    )
    coordinator.start()
    deadline = time.monotonic() + 30
    while coordinator.status(job.id).phase not in {"completed", "failed"}:
        assert time.monotonic() < deadline, "Preparation did not finish"
        coordinator.events(job.id, after=0, wait=0.1)
    coordinator.close()
    assert coordinator.status(job.id).phase == "completed", coordinator.status(job.id).error
    return workspace, journals


def test_the_map_pointer_and_manifest_keep_their_keys_and_provenance(prepared) -> None:
    workspace, journals = prepared
    pointer_bytes = workspace.template_map_current("shirt").read_bytes()
    pointer = json.loads(pointer_bytes)
    manifest_bytes = workspace.template_map_manifest("shirt", pointer["generation_id"]).read_bytes()
    manifest = json.loads(manifest_bytes)
    job = json.loads(journals[-1])
    assert pointer_bytes == canonical(pointer_bytes)
    assert pointer == {
        "generation_id": manifest["generation_id"],
        "manifest_checksum": hashlib.sha256(manifest_bytes).hexdigest(),
        "schema_version": 2,
    }
    assert manifest_bytes == canonical(manifest_bytes)
    assert list(manifest) == [
        "content_digest",
        "generation_id",
        "placements",
        "preparation_inputs",
        "provenance",
        "schema_version",
        "semantics",
    ]
    assert manifest["provenance"] == {
        "engine_version": "1.0.0",
        "installation_id": "test",
        "job_id": job["id"],
    }


def test_a_generation_published_without_provenance_records_an_empty_one(workspace_root) -> None:
    artifacts = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    manifest = artifacts.publish(
        "shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs
    )
    data = artifacts.workspace.template_map_manifest("shirt", manifest.generation_id).read_bytes()
    assert b',"provenance":{},' in data
    assert data == canonical(data)


def test_the_prediction_pointer_is_the_retained_set_manifest(prepared) -> None:
    workspace, _ = prepared
    data = workspace.preparation_prediction_current("shirt").read_bytes()
    pointer = json.loads(data)
    assert data == canonical(data)
    assert list(pointer) == ["evidence", "id", "inputs", "job_order", "schema_version"]
    assert (pointer["schema_version"], pointer["job_order"]) == (1, 1)
    retained = workspace.preparation_prediction_set("shirt", pointer["id"]) / "manifest.json"
    assert retained.read_bytes() == data


def test_journals_keep_their_result_and_checkpoints_and_reload_byte_for_byte(prepared) -> None:
    _, journals = prepared
    checkpointed = next(data for data in journals if b'"cpu_checkpoints":{"":' in data)
    completed = journals[-1]
    checkpoint = json.loads(checkpointed)["cpu_checkpoints"][""]
    assert list(checkpoint) == ["arrays", "checksum", "extent", "id"]
    assert (checkpoint["extent"], checkpoint["id"]) == ([0, 0, 64, 64], None)
    result = json.loads(completed)["result"]
    assert list(result) == ["content_digest", "generation_id"]
    for data in journals:
        assert data == canonical(data)
        reloaded = Job.model_validate_json(data).model_dump(mode="json")
        assert canonical(json.dumps(reloaded).encode()) == data


def test_a_damaged_checkpoint_is_dropped_rather_than_losing_the_job(prepared) -> None:
    # A checkpoint only saves refitting a placement: one that no longer
    # validates is refitted, and the rest of the journal still reads.
    _, journals = prepared
    checkpointed = next(data for data in journals if b'"cpu_checkpoints":{"":' in data)
    document = json.loads(checkpointed)
    valid = document["cpu_checkpoints"][""]
    document["cpu_checkpoints"] = {"": valid, "damaged": {"checksum": "not hex"}}
    job = Job.model_validate_json(json.dumps(document))
    assert list(job.cpu_checkpoints) == [""]
    assert job.id == document["id"]
