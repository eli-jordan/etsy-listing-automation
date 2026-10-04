from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.render.config import load_template_config
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore

BOX = [{"x": 0, "y": 0}, {"x": 32, "y": 0}, {"x": 32, "y": 32}, {"x": 0, "y": 32}]


def make_store(root: Path) -> CalibrationStore:
    workspace = Workspace.discover(root_override=root)
    directory = workspace.template_dir("example")
    directory.mkdir(parents=True)
    Image.new("RGB", (32, 32), "white").save(directory / "scene.png")
    workspace.save_template_config(
        "example",
        load_template_config(
            {"kind": "single", "bounding_box": BOX, "renderer": {"type": "marigold", "config": {}}}
        ),
    )
    return CalibrationStore(workspace)


def test_save_commits_config_and_returns_stable_revision(workspace_root: Path) -> None:
    store = make_store(workspace_root)
    saved = store.read("example")
    result = store.save(
        "example", saved.config, expected_revision=saved.revision, request_id="first"
    )
    assert result.revision == saved.revision
    assert store.read("example").config == saved.config


def test_interrupted_save_rolls_forward_and_cli_refuses_mixed_state(
    workspace_root: Path, monkeypatch
) -> None:
    import os

    import pytest

    from etsy_listings.core.workspace.calibration import CalibrationRepairRequired

    store = make_store(workspace_root)
    saved = store.read("example")
    updated = load_template_config(
        {**saved.config.model_dump(mode="json"), "renderer": {"type": "photo-warp", "config": {}}}
    )
    replace = os.replace

    def interrupt(source, target):
        if Path(target) == store.workspace.template_config_file("example"):
            raise RuntimeError("power lost")
        return replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupt)
        with pytest.raises(RuntimeError, match="power lost"):
            store.save(
                "example", updated, expected_revision=saved.revision, request_id="interrupted"
            )
    with pytest.raises(CalibrationRepairRequired, match="transaction"):
        store.workspace.load_template_config("example")
    restarted = CalibrationStore(store.workspace)
    assert restarted.read("example").config == updated
    assert (
        restarted.save(
            "example", updated, expected_revision=saved.revision, request_id="interrupted"
        ).config
        == updated
    )


def test_mask_strokes_undo_restart_and_reset_after_cache_deletion(workspace_root: Path) -> None:
    import shutil
    from io import BytesIO

    import pytest

    from etsy_listings.core.workspace.calibration import (
        MaskEdit,
        MaskUnavailable,
        Reset,
        Stroke,
        Undo,
    )

    store = make_store(workspace_root)
    automatic = BytesIO()
    Image.new("L", (32, 32), 255).save(automatic, format="PNG")
    saved = store.read("example")
    saved = store.install_automatic(
        "example",
        automatic.getvalue(),
        algorithm_version="test-v1",
        expected_revision=saved.revision,
    )
    edit = MaskEdit(
        operations=[Stroke(type="stroke", mode="mask", diameter_px=8, points=[(16, 16)])]
    )
    painted = store.save(
        "example",
        saved.config,
        expected_revision=saved.revision,
        request_id="paint",
        mask_edits=[edit],
    )
    assert Image.open(BytesIO(store.mask("example").edited)).getpixel((16, 16)) == 0
    restarted = CalibrationStore(store.workspace)
    undone = restarted.save(
        "example",
        painted.config,
        expected_revision=painted.revision,
        request_id="undo",
        mask_edits=[MaskEdit(operations=[Undo(type="undo")])],
    )
    assert restarted.mask("example").edited == automatic.getvalue()
    painted = restarted.save(
        "example",
        undone.config,
        expected_revision=undone.revision,
        request_id="paint-again",
        mask_edits=[edit],
    )
    shutil.rmtree(store.workspace.cache("preparation"))
    assert restarted.mask("example").undo_count == 0
    with pytest.raises(MaskUnavailable, match="Undo"):
        restarted.save(
            "example",
            painted.config,
            expected_revision=painted.revision,
            request_id="lost-undo",
            mask_edits=[MaskEdit(operations=[Undo(type="undo")])],
        )
    restarted.save(
        "example",
        painted.config,
        expected_revision=painted.revision,
        request_id="reset",
        mask_edits=[MaskEdit(operations=[Reset(type="reset")])],
    )
    assert restarted.mask("example").edited == automatic.getvalue()


def test_duplicate_save_returns_exact_response_and_conflicts_cannot_overwrite(
    workspace_root: Path,
) -> None:
    import pytest

    from etsy_listings.core.workspace.calibration import CalibrationConflict

    store = make_store(workspace_root)
    before = store.read("example")
    result = store.save(
        "example", before.config, expected_revision=before.revision, request_id="same"
    )
    assert (
        store.save("example", before.config, expected_revision=before.revision, request_id="same")
        == result
    )
    updated = load_template_config(
        {**before.config.model_dump(mode="json"), "renderer": {"type": "photo-warp", "config": {}}}
    )
    after = store.save("example", updated, expected_revision=result.revision, request_id="new")
    with pytest.raises(CalibrationConflict):
        store.save("example", before.config, expected_revision=before.revision, request_id="same")
    with pytest.raises(CalibrationConflict):
        store.save("example", before.config, expected_revision=before.revision, request_id="new")
    assert store.read("example") == after


def test_fresh_baseline_refresh_preserves_manual_corrections(workspace_root: Path) -> None:
    from io import BytesIO

    from etsy_listings.core.workspace.calibration import MaskEdit, Stroke

    store = make_store(workspace_root)

    def png(value: int) -> bytes:
        buffer = BytesIO()
        Image.new("L", (32, 32), value).save(buffer, format="PNG")
        return buffer.getvalue()

    saved = store.read("example")
    saved = store.install_automatic(
        "example", png(255), algorithm_version="v1", expected_revision=saved.revision
    )
    saved = store.install_automatic(
        "example", png(200), algorithm_version="v2", expected_revision=saved.revision, fresh=True
    )
    assert store.mask("example").automatic == png(200)
    saved = store.save(
        "example",
        saved.config,
        expected_revision=saved.revision,
        request_id="brush",
        mask_edits=[
            MaskEdit(
                operations=[Stroke(type="stroke", mode="mask", diameter_px=8, points=[(16, 16)])]
            )
        ],
    )
    edited = store.mask("example").edited
    store.install_automatic(
        "example", png(255), algorithm_version="v3", expected_revision=saved.revision, fresh=True
    )
    assert store.mask("example").automatic == png(200)
    assert store.mask("example").edited == edited


def test_renderer_settings_roundtrip_is_durable_and_not_revision_identity(
    workspace_root: Path,
) -> None:
    store = make_store(workspace_root)
    before = store.read("example")
    photo_warp = load_template_config(
        {
            **before.config.model_dump(mode="json"),
            "renderer": {"type": "photo-warp", "config": {"shade": {"opacity": 0.9}}},
        }
    )
    middle = store.save(
        "example", photo_warp, expected_revision=before.revision, request_id="photo"
    )
    store.save("example", before.config, expected_revision=middle.revision, request_id="marigold")
    restarted = CalibrationStore(store.workspace)
    assert restarted.renderer_settings("example")["photo-warp"]["shade"]["opacity"] == 0.9
    assert restarted.read("example").revision == before.revision


def test_main_photo_change_refuses_mask_reuse_until_explicit_reset(workspace_root: Path) -> None:
    from io import BytesIO

    import pytest

    from etsy_listings.core.workspace.calibration import MaskUnavailable

    store = make_store(workspace_root)
    png = BytesIO()
    Image.new("L", (32, 32), 255).save(png, format="PNG")
    saved = store.install_automatic(
        "example",
        png.getvalue(),
        algorithm_version="v1",
        expected_revision=store.read("example").revision,
    )
    Image.new("RGB", (32, 32), "black").save(store.workspace.template_main_photo("example"))
    changed = store.read("example")
    assert changed.revision != saved.revision
    with pytest.raises(MaskUnavailable, match="Main photo changed"):
        store.mask("example")
    with pytest.raises(MaskUnavailable):
        store.install_automatic(
            "example", png.getvalue(), algorithm_version="v1", expected_revision=changed.revision
        )
    store.install_automatic(
        "example",
        png.getvalue(),
        algorithm_version="v1",
        expected_revision=changed.revision,
        reset_for_photo=True,
    )
    assert store.mask("example").edited == png.getvalue()


def test_multiple_masks_follow_stable_ids_through_reorder(workspace_root: Path) -> None:
    from io import BytesIO

    import pytest

    from etsy_listings.core.workspace.calibration import MaskUnavailable

    store = make_store(workspace_root)
    config = load_template_config(
        {
            "kind": "multiple",
            "renderer": {"type": "marigold"},
            "placements": [
                {"id": "left-shirt", "colour": "Ivory", "bounding_box": BOX},
                {"id": "right-shirt", "colour": "Ivory", "bounding_box": BOX},
            ],
        }
    )
    store.workspace.save_template_config("example", config)
    saved = store.read("example")
    for placement_id, value in [("left-shirt", 100), ("right-shirt", 200)]:
        png = BytesIO()
        Image.new("L", (32, 32), value).save(png, format="PNG")
        saved = store.install_automatic(
            "example",
            png.getvalue(),
            algorithm_version="v1",
            expected_revision=saved.revision,
            placement_id=placement_id,
        )
    config = load_template_config(
        {
            **config.model_dump(mode="json"),
            "placements": list(reversed(config.model_dump(mode="json")["placements"])),
        }
    )
    store.save("example", config, expected_revision=saved.revision, request_id="reorder")
    assert Image.open(BytesIO(store.mask("example", "left-shirt").edited)).getpixel((16, 16)) == 100
    with pytest.raises(MaskUnavailable):
        store.mask("example")


def test_colour_matrix_main_photo_uses_ordinal_actual_filename(workspace_root: Path) -> None:
    store = make_store(workspace_root)
    for filename in ["ivory.png", "Pepper.png", "amber.png"]:
        Image.new("RGB", (32, 32), "white").save(store.workspace.template_dir("example") / filename)
    config = load_template_config(
        {"kind": "colour-matrix", "bounding_box": BOX, "renderer": {"type": "marigold"}}
    )
    store.workspace.save_template_config("example", config)
    assert store.workspace.template_main_photo("example").name == "Pepper.png"


@pytest.mark.parametrize(
    "checkpoint", ["intent", "settings", "edited", "metadata", "config", "receipt", "cleanup"]
)
def test_every_save_checkpoint_recovers_coherent_calibration(
    workspace_root: Path, monkeypatch, checkpoint: str
) -> None:
    import os
    from io import BytesIO

    from etsy_listings.core.workspace.calibration import MaskEdit, Stroke

    store = make_store(workspace_root)
    png = BytesIO()
    Image.new("L", (32, 32), 255).save(png, format="PNG")
    before = store.install_automatic(
        "example",
        png.getvalue(),
        algorithm_version="v1",
        expected_revision=store.read("example").revision,
    )
    config = load_template_config(
        {**before.config.model_dump(mode="json"), "renderer": {"type": "photo-warp", "config": {}}}
    )
    targets = {
        "intent": store.workspace.template_calibration_transaction("example") / "manifest.json",
        "settings": store.workspace.template_renderer_settings_file("example"),
        "edited": store.workspace.template_mask_file("example"),
        "metadata": store.workspace.template_mask_file("example", source="metadata"),
        "config": store.workspace.template_config_file("example"),
        "receipt": store.workspace.template_calibration_receipt("example"),
    }
    original_replace, original_rmdir = os.replace, os.rmdir

    def replace(source, destination):
        if checkpoint != "cleanup" and Path(destination) == targets[checkpoint]:
            raise RuntimeError("interrupted checkpoint")
        return original_replace(source, destination)

    def rmdir(path, *args, **kwargs):
        if Path(path) == store.workspace.template_calibration_transaction("example"):
            raise RuntimeError("interrupted checkpoint")
        return original_rmdir(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace)
        if checkpoint == "cleanup":
            patch.setattr(os, "rmdir", rmdir)
        with pytest.raises(RuntimeError, match="checkpoint"):
            store.save(
                "example",
                config,
                expected_revision=before.revision,
                request_id="recovery",
                mask_edits=[
                    MaskEdit(
                        operations=[
                            Stroke(type="stroke", mode="mask", diameter_px=8, points=[(16, 16)])
                        ]
                    )
                ],
            )
    restarted = CalibrationStore(store.workspace)
    restored = restarted.read("example")
    if checkpoint == "intent":
        assert restored == before
        assert restarted.mask("example").edited == png.getvalue()
    else:
        assert restored.config == config
        assert Image.open(BytesIO(restarted.mask("example").edited)).getpixel((16, 16)) == 0
        retried = restarted.save(
            "example",
            config,
            expected_revision=before.revision,
            request_id="recovery",
            mask_edits=[
                MaskEdit(
                    operations=[
                        Stroke(type="stroke", mode="mask", diameter_px=8, points=[(16, 16)])
                    ]
                )
            ],
        )
        assert retried == restored


@pytest.mark.parametrize("damage", ["payload", "manifest"])
def test_damaged_recovery_data_blocks_without_accepting_mixed_calibration(
    workspace_root: Path, monkeypatch, damage: str
) -> None:
    import json
    import os

    from etsy_listings.core.workspace.calibration import CalibrationRepairRequired

    store = make_store(workspace_root)
    before = store.read("example")
    config = load_template_config(
        {**before.config.model_dump(mode="json"), "renderer": {"type": "photo-warp"}}
    )
    original = os.replace

    def interrupt(source, destination):
        if Path(destination) == store.workspace.template_renderer_settings_file("example"):
            raise RuntimeError("interrupted")
        return original(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupt)
        with pytest.raises(RuntimeError):
            store.save("example", config, expected_revision=before.revision, request_id="damage")
    transaction = store.workspace.template_calibration_transaction("example")
    manifest = transaction / "manifest.json"
    if damage == "payload":
        payload = json.loads(manifest.read_bytes())["files"][0]["payload"]
        (transaction / payload).write_bytes(b"corrupted")
    else:
        manifest.write_bytes(b"corrupted")
    with pytest.raises(CalibrationRepairRequired, match="repair"):
        CalibrationStore(store.workspace).read("example")


def test_damaged_brush_history_is_discarded_without_losing_mask(workspace_root: Path) -> None:
    import json
    from io import BytesIO

    from etsy_listings.core.workspace.calibration import MaskEdit, MaskUnavailable, Stroke, Undo

    store = make_store(workspace_root)
    png = BytesIO()
    Image.new("L", (32, 32), 255).save(png, format="PNG")
    before = store.install_automatic(
        "example",
        png.getvalue(),
        algorithm_version="v1",
        expected_revision=store.read("example").revision,
    )
    saved = store.save(
        "example",
        before.config,
        expected_revision=before.revision,
        request_id="stroke",
        mask_edits=[
            MaskEdit(
                operations=[Stroke(type="stroke", mode="mask", diameter_px=8, points=[(16, 16)])]
            )
        ],
    )
    painted = store.mask("example")
    store.workspace.template_brush_history("example").write_text(
        json.dumps({"checksum": painted.checksum, "strokes": [{}]}), encoding="utf-8"
    )
    assert store.mask("example").undo_count == 0
    with pytest.raises(MaskUnavailable, match="Undo"):
        store.save(
            "example",
            saved.config,
            expected_revision=saved.revision,
            request_id="undo-corrupt",
            mask_edits=[MaskEdit(operations=[Undo(type="undo")])],
        )
    assert store.mask("example").edited == painted.edited


def test_concurrent_saves_share_one_template_lock_and_one_revision_wins(
    workspace_root: Path,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from etsy_listings.core.workspace.calibration import CalibrationConflict

    store = make_store(workspace_root)
    before = store.read("example")

    def save(opacity: float) -> str:
        other = CalibrationStore(store.workspace)
        config = load_template_config(
            {
                **before.config.model_dump(mode="json"),
                "renderer": {"type": "photo-warp", "config": {"shade": {"opacity": opacity}}},
            }
        )
        try:
            return other.save(
                "example", config, expected_revision=before.revision, request_id=f"save-{opacity}"
            ).revision
        except CalibrationConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, [0.2, 0.8]))
    assert results.count("conflict") == 1
    assert store.read("example").revision in results


def test_switching_back_restores_last_saved_renderer_settings(workspace_root: Path) -> None:
    store = make_store(workspace_root)
    original = store.read("example")
    configured = load_template_config(
        {
            **original.config.model_dump(mode="json"),
            "renderer": {"type": "photo-warp", "config": {"shade": {"opacity": 0.9}}},
        }
    )
    first = store.save(
        "example", configured, expected_revision=original.revision, request_id="configure-photo"
    )
    marigold = store.select_renderer(
        "example", "marigold", expected_revision=first.revision, request_id="select-marigold"
    )
    photo = store.select_renderer(
        "example", "photo-warp", expected_revision=marigold.revision, request_id="select-photo"
    )
    assert photo.config == configured


def test_missing_automatic_baseline_does_not_overwrite_saved_edits(workspace_root: Path) -> None:
    from io import BytesIO

    from etsy_listings.core.workspace.calibration import CalibrationRepairRequired, MaskEdit, Stroke

    store = make_store(workspace_root)
    png = BytesIO()
    Image.new("L", (32, 32), 255).save(png, format="PNG")
    before = store.install_automatic(
        "example",
        png.getvalue(),
        algorithm_version="v1",
        expected_revision=store.read("example").revision,
    )
    store.save(
        "example",
        before.config,
        expected_revision=before.revision,
        request_id="stroke",
        mask_edits=[
            MaskEdit(
                operations=[Stroke(type="stroke", mode="mask", diameter_px=8, points=[(16, 16)])]
            )
        ],
    )
    edited = store.mask("example").edited
    store.workspace.template_mask_file("example", source="automatic").unlink()
    with pytest.raises(CalibrationRepairRequired, match="baseline"):
        store.install_automatic(
            "example",
            png.getvalue(),
            algorithm_version="v2",
            expected_revision=store.read("example").revision,
        )
    assert store.workspace.template_mask_file("example").read_bytes() == edited
