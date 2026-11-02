"""``lease_scene``: the one path from accepted maps to a prepared scene."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from PIL import Image

from etsy_listings.core.preparation import scenes
from etsy_listings.core.preparation.artifacts import Artifacts, StalePreparationError
from etsy_listings.core.preparation.scene_cache import photo_digest
from etsy_listings.core.preparation.scenes import Composition, PreparedLayer, lease_scene
from etsy_listings.core.render import MarigoldAppearance, Point, load_template_base
from etsy_listings.core.render.identity import artwork_identity

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
            Composition(
                base=_base(workspace),
                layers=[PreparedLayer(_artwork(rgb))],
                appearance=MarigoldAppearance(),
            ),
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
        pytest.raises(StalePreparationError, match="out of date"),
        lease_scene(
            workspace,
            "shirt",
            Composition(
                base=_base(workspace),
                layers=[PreparedLayer(_artwork((200, 30, 30)))],
                appearance=MarigoldAppearance(),
            ),
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
            Composition(
                base=_base(workspace),
                layers=[PreparedLayer(_artwork((200, 30, 30)))],
                appearance=MarigoldAppearance(),
            ),
        ) as scene:
            scene.render()

    requests = scenes.MAX_CONCURRENT_RENDERS * 3
    with ThreadPoolExecutor(max_workers=requests) as pool:
        for future in [pool.submit(render) for _ in range(requests)]:
            future.result()

    assert peak == scenes.MAX_CONCURRENT_RENDERS


def _composition(workspace, artwork, **known) -> Composition:
    digest = known.get("digest")
    return Composition(
        base=_base(workspace),
        layers=[PreparedLayer(artwork, digest=digest)],
        appearance=MarigoldAppearance(),
        photo_pixels=known.get("photo_pixels"),
    )


def test_digests_the_caller_already_holds_are_not_computed_again(
    workspace_root, monkeypatch
) -> None:
    """A preview has hashed the photo and the design to look the scene up;
    hashing them again here was a third of a second per colour."""
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    artwork = _artwork((90, 140, 20))
    with lease_scene(workspace, "shirt", _composition(workspace, artwork)) as scene:
        expected = scene.identity
    known = {"digest": artwork_identity(artwork), "photo_pixels": photo_digest(_base(workspace))}

    def no_hashing(_pixels):
        raise AssertionError("hashed pixels whose digest was given")

    monkeypatch.setattr(scenes, "artwork_identity", no_hashing)
    monkeypatch.setattr(scenes, "photo_digest", no_hashing)
    with lease_scene(workspace, "shirt", _composition(workspace, artwork, **known)) as scene:
        assert scene.identity == expected


def test_a_design_composed_again_reuses_its_premultiplied_samples(
    workspace_root, monkeypatch
) -> None:
    """Every colour of a scene composes the same design; preparing its linear
    samples once per design, not per colour, is identical arithmetic."""
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    calls: list[int] = []
    real = scenes.prepare_material_artwork

    def counting(artwork):
        calls.append(1)
        return real(artwork)

    monkeypatch.setattr(scenes, "prepare_material_artwork", counting)
    artwork = _artwork((17, 99, 140))
    images = []
    for _ in range(2):
        with lease_scene(workspace, "shirt", _composition(workspace, artwork)) as scene:
            images.append(np.array(scene.render()))

    assert len(calls) == 1
    assert np.array_equal(images[0], images[1])
