from __future__ import annotations

import numpy as np
import pytest

from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.workspace import Workspace

from tests.support.marigold import material_maps, preparation_inputs


def test_complete_generation_roundtrips_and_renders_after_cache_removal(workspace_root) -> None:
    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    maps = material_maps()
    generation = store.publish("shirt", inputs, {None: maps}, current_inputs=lambda: inputs)
    assert store.readiness("shirt", inputs).state == "ready"
    with store.acquire("shirt", inputs) as acquired:
        assert acquired.manifest.generation_id == generation.generation_id
        np.testing.assert_array_equal(acquired.maps[None].material, maps.material)
        assert not acquired.maps[None].material.flags.writeable
        assert acquired.manifest.content_digest == generation.content_digest
    assert not Workspace.discover(root_override=workspace_root).cache().exists()
    with Artifacts(Workspace.discover(root_override=workspace_root)).acquire(
        "shirt", inputs
    ) as acquired:
        assert acquired.maps[None].size == (16, 16)


def test_cleanup_cannot_remove_a_generation_while_publication_is_validating(workspace_root) -> None:
    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    observed = []

    def checkpoint(phase):
        if phase == "validated":
            observed.extend(store.cleanup("shirt"))

    generation = store.publish(
        "shirt",
        inputs,
        {None: material_maps()},
        current_inputs=lambda: inputs,
        checkpoint=checkpoint,
    )
    assert observed == []
    assert store.readiness("shirt", inputs).state == "ready"
    assert generation.generation_id in store.workspace.template_map_generations("shirt")


@pytest.mark.parametrize("document", [None, [], "wrong"])
def test_malformed_manifest_structures_report_an_actionable_readiness(
    workspace_root, document
) -> None:
    import hashlib
    import json

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    generation = store.publish(
        "shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs
    )
    path = store.workspace.template_map_manifest("shirt", generation.generation_id)
    data = json.dumps(document).encode()
    path.write_bytes(data)
    pointer_path = store.workspace.template_map_current("shirt")
    pointer = json.loads(pointer_path.read_bytes())
    pointer["manifest_checksum"] = hashlib.sha256(data).hexdigest()
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    readiness = store.readiness("shirt", inputs)
    assert readiness.state == "out_of_date"
    assert readiness.reason == "invalid_artifact"
    assert "prepare" in readiness.message.lower()


def test_generation_identity_ignores_provenance_storage_names_and_placement_order(
    workspace_root,
) -> None:
    store = Artifacts(Workspace.discover(root_override=workspace_root))
    first_inputs = preparation_inputs(("left", "right"))
    reverse_inputs = preparation_inputs(("right", "left"))
    maps = {"left": material_maps(), "right": material_maps()}
    first = store.publish(
        "shirt", first_inputs, maps, current_inputs=lambda: first_inputs, provenance={"seconds": 1}
    )
    second = store.publish(
        "shirt",
        reverse_inputs,
        maps,
        current_inputs=lambda: reverse_inputs,
        provenance={"seconds": 99, "engine": "new"},
    )
    assert first.generation_id != second.generation_id
    assert first.content_digest == second.content_digest
    assert first_inputs.identity() == reverse_inputs.identity()
    assert store.readiness("shirt", first_inputs).can_render


def test_old_generation_is_retained_by_alias_readers_and_durable_job_references(
    workspace_root,
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    store = Artifacts(workspace)
    alias = Artifacts(Workspace.discover(root_override=workspace.root / ".." / workspace.root.name))
    inputs = preparation_inputs()
    first = store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs)
    with alias.acquire("shirt", inputs) as acquired:
        second = store.publish(
            "shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs
        )
        assert store.cleanup("shirt") == []
        assert acquired.manifest.generation_id == first.generation_id
    assert store.cleanup("shirt", retained_generations={first.generation_id}) == []
    assert store.cleanup("shirt") == [first.generation_id]
    assert second.generation_id in workspace.template_map_generations("shirt")


def test_stale_publication_and_crash_before_pointer_preserve_the_current_generation(
    workspace_root,
) -> None:
    from etsy_listings.core.preparation.artifacts import StalePreparation

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    first = store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs)
    changed = inputs.model_copy(
        update={"photo": inputs.photo.model_copy(update={"pixels": "d" * 64})}
    )
    with pytest.raises(StalePreparation):
        store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: changed)

    def crash(phase):
        if phase == "generation":
            raise RuntimeError("simulated process exit")

    with pytest.raises(RuntimeError, match="simulated"):
        store.publish(
            "shirt",
            inputs,
            {None: material_maps()},
            current_inputs=lambda: inputs,
            checkpoint=crash,
        )
    with Artifacts(store.workspace).acquire("shirt", inputs) as acquired:
        assert acquired.manifest.generation_id == first.generation_id
    assert len(store.cleanup("shirt")) == 2


def test_shared_colour_dimensions_and_all_placement_completeness_are_mandatory(
    workspace_root,
) -> None:
    from etsy_listings.core.preparation.artifacts import ArtifactError

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs(("left", "right"))
    with pytest.raises(ArtifactError, match="exact"):
        store.publish("shirt", inputs, {"left": material_maps()}, current_inputs=lambda: inputs)
    store.publish(
        "shirt",
        inputs,
        {"left": material_maps(), "right": material_maps()},
        current_inputs=lambda: inputs,
    )
    assert (
        store.readiness("shirt", inputs, target_size=(15, 16)).reason == "incompatible_dimensions"
    )
    with store.acquire("shirt", inputs, target_size=(16, 16)) as acquired:
        assert set(acquired.maps) == {"left", "right"}


def test_saved_readiness_reuses_durable_evidence_identity_without_runtime_or_cache(
    workspace_root,
) -> None:
    from PIL import Image

    from etsy_listings.core.render import load_template_config
    from etsy_listings.core.workspace.workspace import remove_tree

    workspace = Workspace.discover(root_override=workspace_root)
    workspace.template_dir("shirt").mkdir()
    Image.new("RGB", (16, 16), "navy").save(workspace.template_scene_image("shirt"))
    config = load_template_config(
        {
            "kind": "single",
            "bounding_box": [
                {"x": 0, "y": 0},
                {"x": 15, "y": 0},
                {"x": 15, "y": 15},
                {"x": 0, "y": 15},
            ],
            "renderer": {"type": "marigold", "config": {}},
        }
    )
    workspace.save_template_config("shirt", config)
    store = Artifacts(workspace)
    inputs = store.saved_inputs("shirt", evidence={None: "c" * 64})
    store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs)
    workspace.cache().mkdir(exist_ok=True)
    remove_tree(workspace.cache())
    assert store.saved_inputs("shirt").identity() == inputs.identity()
    assert store.readiness("shirt", store.saved_inputs("shirt")).can_render
    changed = config.model_copy(
        update={
            "bounding_box": tuple(
                point.model_copy(update={"x": point.x + 1}) for point in config.bounding_box
            )
        }
    )
    workspace.save_template_config("shirt", changed)
    assert store.readiness("shirt", store.saved_inputs("shirt")).reason == "placement_changed"


@pytest.mark.parametrize(
    "damage", ["unsupported_schema", "extent", "placement_set", "numerical_checksum"]
)
def test_invalid_generations_are_refused_as_one_complete_set(workspace_root, damage) -> None:
    import hashlib
    import json

    from tests.support.marigold import rewrite_map_manifest

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    generation = store.publish(
        "shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs
    )
    path = store.workspace.template_map_manifest("shirt", generation.generation_id)
    document = json.loads(path.read_bytes())
    if damage == "unsupported_schema":
        document["schema_version"] = 2
    elif damage == "extent":
        document["placements"][0]["extent"][2] = 15
    elif damage == "placement_set":
        document["placements"] = []
    else:
        archive = store.workspace.template_map_file("shirt", generation.generation_id, None)
        maps = material_maps()
        maps.material[0, 0, 0] = 0.1
        with np.load(archive, allow_pickle=False) as old:
            arrays = {key: old[key] for key in old.files}
        arrays["material"] = maps.material
        np.savez_compressed(archive, **arrays)
        document["placements"][0]["checksum"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    rewrite_map_manifest(store.workspace, "shirt", generation.generation_id, document)
    state = store.readiness("shirt", inputs)
    assert not state.can_render
    assert state.reason == (
        "unsupported_schema" if damage == "unsupported_schema" else "invalid_artifact"
    )


def test_malicious_array_headers_are_rejected_before_numpy_can_allocate(
    workspace_root, monkeypatch
) -> None:
    import hashlib
    import io
    import json
    import zipfile

    from tests.support.marigold import rewrite_map_manifest

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    generation = store.publish(
        "shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs
    )
    archive = store.workspace.template_map_file("shirt", generation.generation_id, None)
    with zipfile.ZipFile(archive) as old:
        members = {name: old.read(name) for name in old.namelist()}
    malicious = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        malicious, {"descr": "<f4", "fortran_order": False, "shape": (2**40, 2**40, 2)}
    )
    members["material.npy"] = malicious.getvalue()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as new:
        for name, data in members.items():
            new.writestr(name, data)
    document = json.loads(
        store.workspace.template_map_manifest("shirt", generation.generation_id).read_bytes()
    )
    document["placements"][0]["checksum"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    rewrite_map_manifest(store.workspace, "shirt", generation.generation_id, document)

    def allocation_forbidden(*args, **kwargs):
        raise AssertionError("np.load must not see unsafe headers")

    monkeypatch.setattr(np, "load", allocation_forbidden)
    assert store.readiness("shirt", inputs).reason == "invalid_artifact"


@pytest.mark.parametrize(
    "field,value",
    [
        ("material", np.nan),
        ("visibility", 1.1),
        ("estimated", 1.8),
        ("photographic", 0.0),
        ("texture", 1.2),
        ("residual", 0.04),
        ("patch_ids", 101),
    ],
)
def test_publication_refuses_nonfinite_or_out_of_bounds_maps(workspace_root, field, value) -> None:
    from etsy_listings.core.preparation.artifacts import ArtifactError

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    maps = material_maps()
    getattr(maps, field).flat[0] = value
    with pytest.raises(ArtifactError):
        store.publish("shirt", inputs, {None: maps}, current_inputs=lambda: inputs)
    assert store.readiness("shirt", inputs).state == "needs_preparation"


def test_prepared_rendering_in_a_fresh_cpu_process_cannot_import_models(workspace_root) -> None:
    import json
    import subprocess
    import sys

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs)
    probe = """
import sys, importlib.abc, json
class CpuOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        models={'torch','diffusers'}
        workers={'runtime','installation','worker_client'}
        if fullname.split('.')[0] in models or (
            fullname.startswith('etsy_listings.core.preparation.')
            and fullname.rsplit('.',1)[-1] in workers
        ):
            raise AssertionError('CPU render attempted inference import '+fullname)
sys.meta_path.insert(0,CpuOnly())
import numpy as np
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.preparation.artifacts import Artifacts, PreparationInputs
from etsy_listings.core.render.material import MaterialLayer, render_marigold_scene
from pathlib import Path
store=Artifacts(Workspace.discover(root_override=Path(sys.argv[1])))
inputs=PreparationInputs.model_validate(json.loads(sys.argv[2]))
with store.acquire('shirt',inputs,target_size=(16,16)) as acquired:
    image=render_marigold_scene(np.zeros((16,16,3),np.uint8),[MaterialLayer(np.full((16,16,4),255,np.uint8),acquired.maps[None])])
    assert image.size==(16,16)
assert 'torch' not in sys.modules
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            probe,
            str(workspace_root),
            json.dumps(inputs.model_dump(mode="json")),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("phase", ["validated", "generation", "pointer"])
def test_restart_at_each_publication_checkpoint_exposes_one_complete_generation(
    workspace_root, phase
) -> None:
    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    first = store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs)

    def crash(step):
        if step == phase:
            raise InterruptedError("crash")

    with pytest.raises(InterruptedError):
        store.publish(
            "shirt",
            inputs,
            {None: material_maps()},
            current_inputs=lambda: inputs,
            checkpoint=crash,
        )
    restarted = Artifacts(store.workspace)
    with restarted.acquire("shirt", inputs) as acquired:
        assert (acquired.manifest.generation_id == first.generation_id) == (phase != "pointer")
        assert acquired.maps[None].size == (16, 16)
    assert len(restarted.cleanup("shirt")) == 1


def test_reader_lease_releases_after_the_renderer_raises_its_own_error(workspace_root) -> None:
    store = Artifacts(Workspace.discover(root_override=workspace_root))
    inputs = preparation_inputs()
    first = store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs)
    error = ValueError("artwork failure")
    with pytest.raises(ValueError) as caught, store.acquire("shirt", inputs):
        store.publish("shirt", inputs, {None: material_maps()}, current_inputs=lambda: inputs)
        raise error
    assert caught.value is error
    assert store.cleanup("shirt") == [first.generation_id]


def test_small_placement_on_a_large_photo_prepares_and_publishes_invisible_coordinates_safely(
    workspace_root,
) -> None:
    from etsy_listings.core.preparation.numerics import (
        Evidence,
        EvidenceIdentity,
        plan_crop,
        prepare,
    )

    store = Artifacts(Workspace.discover(root_override=workspace_root))
    box = np.array([[240, 240], [272, 240], [272, 272], [240, 272]], np.float32)
    crop = plan_crop(box, (512, 512))
    width, height = crop.prediction_size
    normals = np.zeros((height, width, 3), np.float32)
    normals[..., 2] = 1
    evidence = Evidence(
        crop,
        EvidenceIdentity("p", "m", "i", "v"),
        normals,
        np.full((height, width, 3), 0.5, np.float32),
        np.full((height, width, 3), 0.4, np.float32),
        np.zeros((height, width, 3), np.float32),
        np.full((height, width), 0.5, np.float32),
    )
    prepared = prepare(
        np.full((512, 512, 3), 128, np.uint8), box, evidence, mask=np.ones((512, 512), np.float32)
    )
    assert prepared.maps.visibility[0, 0] == 0
    assert prepared.maps.visibility[256, 256] == 1
    np.testing.assert_allclose(prepared.maps.material[240, 240], [0, 0], atol=1e-6)
    np.testing.assert_allclose(prepared.maps.material[272, 272], [1, 1], atol=1e-6)
    inputs = preparation_inputs(size=(512, 512))
    placement = inputs.placements[0].model_copy(
        update={"quad": tuple(tuple(float(v) for v in point) for point in box)}
    )
    inputs = inputs.model_copy(update={"placements": (placement,)})
    store.publish("shirt", inputs, {None: prepared.maps}, current_inputs=lambda: inputs)
    with store.acquire("shirt", inputs) as acquired:
        assert acquired.maps[None].size == (512, 512)
