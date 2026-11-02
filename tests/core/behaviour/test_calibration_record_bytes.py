"""The exact bytes calibration writes for its durable JSON records.

Saved masks, receipts and recovery manifests already on disk must keep
parsing, and the calibration revision must not move, so these pin each
record's keys, order and serialisation as the store writes them today."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from etsy_listings.core.render.config import load_template_config
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import (
    AutomaticMask,
    Calibration,
    CalibrationStore,
    MaskEdit,
    Stroke,
)

BOX = [{"x": 0, "y": 0}, {"x": 32, "y": 0}, {"x": 32, "y": 32}, {"x": 0, "y": 32}]
PHOTO = (
    '{"conversion":"pillow-rgb-v1","file":"scene.png","height":32,'
    '"pixels":"1a7493ff2f2bde5f78405d46eb01abfeaea9b0a95fa5b6cec211b05faa0cf1d3","width":32}'
)
AUTOMATIC = "e7bdc527afd649f51950b4524b0c15aecaf7f484448a6cdfcdc2ecd9bba0f5a7"
EDITED = "35c44bc8b1812acac6e36ad7a328d240aebce7772f5fdd8efc4ae86d61d10778"


def _store(root: Path) -> tuple[CalibrationStore, list[bytes]]:
    """A white 32px single Marigold template, and the transaction manifests
    its commits write, in order."""
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
    store = CalibrationStore(workspace)
    manifests: list[bytes] = []
    write = store.write_durable

    def recording(path: Path, data: bytes) -> None:
        if path.name == "manifest.json":
            manifests.append(data)
        write(path, data)

    store.write_durable = recording  # type: ignore[method-assign]  # -- observe the durable writes
    return store, manifests


def _install(store: CalibrationStore) -> Calibration:
    png = BytesIO()
    Image.new("L", (32, 32), 255).save(png, format="PNG")
    return store.install_automatic(
        "example",
        AutomaticMask(png.getvalue(), algorithm_version="v1"),
        expected_revision=store.read("example").revision,
    )


def _entry(index: int, checksum: str, destination: str) -> str:
    return (
        f'{{"backup":"backup-{index}","checksum":"{checksum}",'
        f'"destination":"{destination}","payload":"payload-{index}"}}'
    )


def _manifests(*entries: str) -> list[bytes]:
    """The intent manifest, then the same manifest marked complete."""
    files = ",".join(entries)
    return [
        f'{{"commit_intent":true,"files":[{files}],"schema_version":1}}'.encode(),
        f'{{"commit_intent":true,"complete":true,"files":[{files}],"schema_version":1}}'.encode(),
    ]


def test_installing_a_mask_writes_pinned_metadata_and_transaction(workspace_root: Path) -> None:
    store, manifests = _store(workspace_root)
    assert store.read("example").revision == (
        "0863c24e420af5e30b663b6cce1cb3cf987f8776c01315073fa8c3cdc00ca3c1"
    )
    installed = _install(store)
    assert installed.revision == "9e3d36f042b351f0c60c4442e41d46660725415aef16b0f4f4a6939e72faf684"
    metadata = store.workspace.template_mask_file("example", source="metadata").read_bytes()
    assert (
        metadata
        == (
            f'{{"algorithm_version":"v1","automatic_checksum":"{AUTOMATIC}",'
            f'"edited_checksum":"{AUTOMATIC}","photo":{PHOTO},"schema_version":1}}'
        ).encode()
    )
    assert manifests == _manifests(
        _entry(0, AUTOMATIC, "_renderer/masks/automatic.png"),
        _entry(1, AUTOMATIC, "_renderer/masks/edited.png"),
        _entry(
            2,
            "f61b7f28d0906602c526e2deb946378e072109487ab406e44a47de2b8b955c00",
            "_renderer/masks/metadata.json",
        ),
    )


def test_a_brush_save_writes_pinned_receipt_history_and_metadata(workspace_root: Path) -> None:
    store, manifests = _store(workspace_root)
    installed = _install(store)
    manifests.clear()
    stroke = Stroke(type="stroke", mode="mask", diameter_px=8, points=[(16, 16)])
    saved = store.save(
        "example",
        installed.config,
        expected_revision=installed.revision,
        request_id="stroke",
        mask_edits=[MaskEdit(operations=[stroke])],
    )
    workspace = store.workspace
    assert saved.revision == "58529c054662d7df411535795c49ea34b375a5b04eb24c2d0802d096fa1755f0"
    assert (
        workspace.template_mask_file("example", source="metadata").read_bytes()
        == (
            f'{{"algorithm_version":"v1","automatic_checksum":"{AUTOMATIC}",'
            f'"edited_checksum":"{EDITED}","photo":{PHOTO},"schema_version":1}}'
        ).encode()
    )
    assert workspace.template_calibration_receipt("example").read_bytes() == (
        b'{"config":{"bounding_box":[{"x":0.0,"y":0.0},{"x":32.0,"y":0.0},{"x":32.0,"y":32.0},'
        b'{"x":0.0,"y":32.0}],"colour":null,"kind":"single","renderer":{"config":{"appearance":'
        b'{"fabric_texture":0.25,"lighting_source":"estimated","lighting_strength":1.0,'
        b'"print_shine":0.0},"inference":{"ensemble_size":3,"num_inference_steps":10}},'
        b'"type":"marigold"}},"digest":"394466a387f05a8ff48be253bc930f387a33d12dad93f2f2a01d0782b8a0c86e",'
        b'"main_photo":"mockup-templates/example/scene.png","request_id":"stroke",'
        b'"revision":"58529c054662d7df411535795c49ea34b375a5b04eb24c2d0802d096fa1755f0"}'
    )
    assert workspace.template_brush_history("example").read_text(encoding="utf-8") == (
        "{\n"
        f'  "checksum": "{EDITED}",\n'
        '  "strokes": [\n'
        "    {\n"
        '      "before": "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAAAAABWESUoAAAAGUlEQVR4nGP8z4AfMBGQH1UwqmBUwbBVAACjPQE/b0XQuQAAAABJRU5ErkJggg==",\n'  # noqa: E501 -- the pinned PNG stays whole
        '      "operation": {\n'
        '        "type": "stroke",\n'
        '        "mode": "mask",\n'
        '        "diameter_px": 8.0,\n'
        '        "points": [\n'
        "          [\n"
        "            16.0,\n"
        "            16.0\n"
        "          ]\n"
        "        ]\n"
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    assert store.mask("example").undo_count == 1
    assert manifests == _manifests(
        _entry(0, EDITED, "_renderer/masks/edited.png"),
        _entry(
            1,
            "7305bc47a1a2bad13500728efcd00b0fda2fc0ab1b73d6e4e25b97e43ff22be8",
            "_renderer/masks/metadata.json",
        ),
        _entry(
            2,
            "a5eb991c03a2df0b55980b40f9ffb328a2df5ee92eb8d7d0ac4ca064b2836369",
            "_renderer/renderer-settings.json",
        ),
        _entry(
            3, "341b28fbb40f8948475c0c1c3aebefd16de1588b7dd1197ca3ca694249a73e95", "template.yaml"
        ),
        _entry(
            4,
            "c9e81bfab26aa42f73e513fae9130fe2cd90c74446f3f928c0ac353a43a77111",
            "_renderer/calibration-receipt.json",
        ),
    )
