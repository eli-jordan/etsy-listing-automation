"""Interactive raster fidelity through the real HTTP composition boundary."""

import time
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from etsy_listings.core.render import load_template_config
from etsy_listings.core.workspace.calibration import AutomaticMask, CalibrationStore
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.server.api.app import create_app

from tests.support.marigold import PreparationRuntime, marigold_template


@pytest.mark.parametrize(
    ("photo_size", "expected_size"), [((2048, 2048), (1024, 1024)), ((2304, 2048), (1024, 910))]
)
def test_editor_resolves_fine_artwork_at_1024_without_changing_full_preview(
    workspace_root, photo_size, expected_size
):
    workspace = marigold_template(workspace_root)
    _full_photo_print(workspace, photo_size)
    artwork = _fine_artwork_png()
    runtime = PreparationRuntime()
    with TestClient(create_app(workspace, preparation_runtime=runtime)) as client:
        ready = client.get("/api/templates/shirt/preparation").json()
        created = client.post(
            "/api/preparation/jobs",
            json={
                "template": "shirt",
                "config_revision": ready["config_revision"],
                "request_id": "detail-fixture",
            },
        )
        assert created.status_code == 202, created.text
        _wait_completed(client, created.json()["id"])
        loaded = client.get("/api/templates/shirt/config")
        uploaded = client.post("/api/designs", files={"file": ("detail.png", artwork, "image/png")})
        body = {
            **loaded.json(),
            "design": uploaded.json()["id"],
            "calibration_revision": loaded.headers["etag"].strip(chr(34)),
        }
        full_before = client.post("/api/templates/shirt/preview", json=body)
        response = client.post("/api/templates/shirt/preview?scale=editor", json=body)
        assert response.status_code == 200, response.text
        editor = Image.open(BytesIO(response.content)).convert("RGB")
        assert editor.size == expected_size
        # Compare decoded detail with an independently rendered full-quality
        # reference, rather than trusting dimensions or map internals.
        reference = (
            Image.open(BytesIO(full_before.content))
            .convert("RGB")
            .resize(expected_size, Image.Resampling.LANCZOS)
        )
        editor.save(workspace_root.parent / "detail-editor.png")
        reference.save(workspace_root.parent / "detail-reference.png")
        actual = np.asarray(editor, dtype=float).mean(axis=2)
        expected = np.asarray(reference, dtype=float).mean(axis=2)
        ratio = 2048 / max(photo_size)
        for bounds in [(150, 220, 200, 800), (395, 450, 130, 650)]:
            y0, y1, x0, x1 = [round(v * ratio) for v in bounds]
            region = (slice(y0, y1), slice(x0, x1))
            target = expected[region]
            observed = actual[region]
            dark, light = target < 100, target > 230
            assert dark.sum() > 20, "Reference must contain fine ink strokes"
            contrast = observed[light].mean() - observed[dark].mean()
            assert contrast > 180, f"Fine lines/text must retain readable contrast: {contrast:.1f}"
            assert np.abs(observed - target).mean() < 35, (
                "Fine detail must follow the full-quality reference"
            )
        assert client.post("/api/templates/shirt/preview", json=body).content == full_before.content


def _full_photo_print(workspace, photo_size):
    """A flat, all-visible print over nearly the whole photo."""
    Image.new("RGB", photo_size, "navy").save(workspace.template_scene_image("shirt"))
    config = template_state(workspace, "shirt").require().model_dump(mode="json")
    # A nearly full-photo print exercises detail above the old artwork cap.
    config["bounding_box"] = [
        {"x": x, "y": y} for x, y in [(0, 0), (2046, 0), (2046, 2046), (0, 2046)]
    ]
    config["renderer"]["config"]["appearance"] = {
        "lighting_strength": 0,
        "fabric_texture": 0,
        "print_shine": 0,
    }
    CalibrationStore(workspace).write_config("shirt", load_template_config(config))
    store = CalibrationStore(workspace)
    store.install_automatic(
        "shirt",
        AutomaticMask(
            store.encode_mask(Image.new("L", photo_size, 255)),
            algorithm_version="all-visible-detail-test",
        ),
        expected_revision=store.read("shirt").revision,
    )


def _fine_artwork_png():
    artwork = Image.new("RGBA", (4200, 4800), "white")
    draw = ImageDraw.Draw(artwork)
    # 14-source-pixel strokes remain at least three editor pixels. A 512px artwork cap
    # averages them away even if the final frame is enlarged to 1024px.
    for x in range(600, 3600, 48):
        draw.rectangle((x, 600, x + 13, 1200), fill="black")
    # Text stems have the same few-pixel displayed width as the line target.
    draw.text((600, 1800), "Fine print 1024", font=ImageFont.load_default(size=240), fill="black")
    buffer = BytesIO()
    artwork.save(buffer, format="PNG")
    return buffer.getvalue()


def _wait_completed(client, identity):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = client.get(f"/api/preparation/jobs/{identity}").json()
        if job["phase"] in {"completed", "failed", "cancelled", "superseded"}:
            assert job["phase"] == "completed", job
            return
        time.sleep(0.02)
    pytest.fail("Detail fixture preparation did not complete")
