"""``lease_scene``: the one path from accepted maps to a prepared scene."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from PIL import Image

from etsy_listings.core.preparation import scenes
from etsy_listings.core.preparation.artifacts import Artifacts, StalePreparation
from etsy_listings.core.preparation.scenes import PreparedLayer, lease_scene
from etsy_listings.core.render import MarigoldAppearance, Point, load_template_base

from tests.support.marigold import listing_with_marigold


def _artwork(rgb: tuple[int, int, int]) -> np.ndarray:
    artwork = np.zeros((32, 32, 4), np.uint8)
    artwork[...] = (*rgb, 255)
    return artwork


def _base(workspace):
    return load_template_base(workspace.scene_photo("shirt", None).path)


def test_identity_names_the_artwork_and_the_scene_renders_at_the_photo_size(
    workspace_root,
) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    identities = []
    for rgb in [(200, 30, 30), (30, 30, 200)]:
        with lease_scene(
            workspace,
            "shirt",
            base=_base(workspace),
            layers=[PreparedLayer(_artwork(rgb))],
            appearance=MarigoldAppearance(),
        ) as scene:
            identities.append(scene.identity)
            assert scene.render().size == (64, 64)
    assert identities[0] != identities[1]


def test_inputs_changed_since_they_were_read_refuse_as_stale(workspace_root) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    planned = Artifacts(workspace).saved_inputs("shirt")
    config = workspace.load_template_config("shirt")
    workspace.save_template_config(
        "shirt",
        config.model_copy(update={"bounding_box": (Point(x=13, y=12), *config.bounding_box[1:])}),
    )

    with (
        pytest.raises(StalePreparation, match="out of date"),
        lease_scene(
            workspace,
            "shirt",
            base=_base(workspace),
            layers=[PreparedLayer(_artwork((200, 30, 30)))],
            appearance=MarigoldAppearance(),
            expected=planned,
        ),
    ):
        pass


def test_concurrent_renders_compose_at_most_the_cap_at_once(workspace_root, monkeypatch) -> None:
    """A gallery's worth of preview requests at once must queue rather than
    each holding a full-photo composition's memory (about 1 GB at 2048px)."""
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    active = 0
    peak = 0
    lock = threading.Lock()
    rendezvous = threading.Barrier(scenes.MAX_CONCURRENT_RENDERS)

    def slow_render(base, layers, *, appearance):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        # Hold the first arrivals until a full batch has entered. Decoding
        # photos under load can otherwise stagger requests beyond the sleep.
        rendezvous.wait(timeout=10)
        time.sleep(0.05)
        with lock:
            active -= 1
        return Image.new("RGB", (1, 1))

    monkeypatch.setattr(scenes, "render_marigold_scene", slow_render)

    def render() -> None:
        with lease_scene(
            workspace,
            "shirt",
            base=_base(workspace),
            layers=[PreparedLayer(_artwork((200, 30, 30)))],
            appearance=MarigoldAppearance(),
        ) as scene:
            scene.render()

    requests = scenes.MAX_CONCURRENT_RENDERS * 3
    with ThreadPoolExecutor(max_workers=requests) as pool:
        for future in [pool.submit(render) for _ in range(requests)]:
            future.result()

    assert peak == scenes.MAX_CONCURRENT_RENDERS
