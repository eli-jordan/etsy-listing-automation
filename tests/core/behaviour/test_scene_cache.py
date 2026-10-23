"""Composed Marigold scenes are kept by identity and composed once."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.application.prepared_previews import prepared_preview
from etsy_listings.core.engine import build_plan, execute
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.preparation import scenes
from etsy_listings.core.preparation.scene_cache import PIXEL_DIGESTS, SceneCache

from tests.support.builders import FIXTURE_LISTING, a_context, a_lock
from tests.support.marigold import listing_with_marigold


@pytest.fixture
def compositions(monkeypatch) -> list[int]:
    """Counts every composition, still composing for real."""
    calls: list[int] = []
    real = scenes.render_marigold_scene

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(scenes, "render_marigold_scene", counting)
    return calls


def _preview(workspace, design: Path):
    return prepared_preview(
        workspace, "shirt", config=None, colour=None, design=lambda _colour: design
    )


def _design(workspace) -> Path:
    return workspace.design_file("take-a-hike")


def test_viewing_a_scene_again_serves_the_same_bytes_without_decoding(
    workspace_root, compositions, monkeypatch
) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    first = _preview(workspace, _design(workspace))

    def no_decoding(path):
        raise AssertionError(f"a repeat view decoded {path}")

    monkeypatch.setattr(PIXEL_DIGESTS, "decode_photo", no_decoding)
    monkeypatch.setattr(PIXEL_DIGESTS, "decode_design", no_decoding)
    again = _preview(workspace, _design(workspace))

    assert len(compositions) == 1
    assert again.png == first.png
    assert again.render_identity == first.render_identity
    assert again.generation_id == first.generation_id


def test_a_design_written_since_is_composed_again(workspace_root, compositions) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    design = _design(workspace)
    first = _preview(workspace, design)

    Image.new("RGBA", (16, 16), "red").save(design)
    again = _preview(workspace, design)

    assert len(compositions) == 2
    assert again.render_identity != first.render_identity
    assert again.png != first.png


def test_apply_uses_a_scene_a_preview_already_composed(workspace_root, compositions) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    work = stage.desired(ctx, FIXTURE_LISTING, None).works[0]
    viewed = _preview(workspace, work.layers[0].design)

    execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,)), a_lock())

    assert len(compositions) == 1
    assert workspace.render_file(FIXTURE_LISTING, "shirt", None).read_bytes() == viewed.png


def test_a_preview_finds_what_apply_composed(workspace_root, compositions) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,)), a_lock())
    work = stage.desired(ctx, FIXTURE_LISTING, None).works[0]

    viewed = _preview(workspace, work.layers[0].design)

    assert len(compositions) == 1
    assert viewed.png == workspace.render_file(FIXTURE_LISTING, "shirt", None).read_bytes()


def test_past_its_budget_the_least_recently_read_scene_goes_first(workspace_root) -> None:
    workspace, _ = listing_with_marigold(workspace_root)
    cache = SceneCache(workspace, budget=20)
    old, read, new = (f"sha256:{digit * 64}" for digit in "abc")
    cache.store(old, b"0123456789")
    cache.store(read, b"0123456789")
    for age, identity in enumerate((read, old)):
        path = workspace.scene_cache_dir() / f"{identity.removeprefix('sha256:')}.png"
        os.utime(path, ns=(age * 10**9, age * 10**9))
    assert cache.read(read) is not None

    cache.store(new, b"0123456789")

    assert cache.read(old) is None
    assert cache.read(read) == b"0123456789"
    assert cache.read(new) == b"0123456789"


def test_an_identity_that_is_not_a_digest_names_no_file(workspace_root) -> None:
    workspace, _ = listing_with_marigold(workspace_root)

    with pytest.raises(ValueError, match="not a scene identity"):
        SceneCache(workspace).read("sha256:../../shop.yaml")


# ---------------------------------------------------------------- photo warp


@pytest.fixture
def warps(monkeypatch) -> list[int]:
    """Counts every photo-warp composition, preview's and the render stage's,
    still composing for real."""
    from etsy_listings.core.application import mockup_templates
    from etsy_listings.core.engine.stages import render

    calls: list[int] = []
    real = render.render_scene

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(render, "render_scene", counting)
    monkeypatch.setattr(mockup_templates, "render_scene", counting)
    return calls


def _warp_preview(workspace, colour: str = "black"):
    from etsy_listings.core.application.listing_reads import scene_artwork
    from etsy_listings.core.application.mockup_templates import saved_preview
    from etsy_listings.core.application.prepared_previews import photo_warp_preview
    from etsy_listings.core.render import load_design, load_template_base

    scene = saved_preview(
        workspace,
        "flat-lay-01",
        colour=colour,
        design=scene_artwork(workspace, FIXTURE_LISTING),
    )
    return photo_warp_preview(workspace, scene, base=load_template_base, design=load_design)


def test_a_photo_warp_scene_viewed_again_is_not_composed_or_decoded(
    workspace_root, warps, monkeypatch
) -> None:
    workspace = a_context(workspace_root).workspace
    first = _warp_preview(workspace)

    def no_decoding(path, load=None):
        raise AssertionError(f"a repeat view decoded {path}")

    monkeypatch.setattr(PIXEL_DIGESTS, "decode_photo", no_decoding)
    monkeypatch.setattr(PIXEL_DIGESTS, "decode_design", no_decoding)
    again = _warp_preview(workspace)

    assert len(warps) == 1
    assert again == first


def test_a_photo_warp_design_written_since_is_composed_again(workspace_root, warps) -> None:
    workspace = a_context(workspace_root).workspace
    first = _warp_preview(workspace)

    Image.new("RGBA", (16, 16), "red").save(workspace.design_file("take-a-hike"))
    again = _warp_preview(workspace)

    assert len(warps) == 2
    assert again.render_identity != first.render_identity


def test_photo_warp_preview_and_apply_share_their_scenes(workspace_root, warps) -> None:
    ctx = a_context(workspace_root)
    workspace = ctx.workspace
    viewed = _warp_preview(workspace, "black")

    execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (RenderStage(),)), a_lock())

    # Apply composed the three colours nobody viewed, and reused the one viewed.
    assert len(warps) == 4
    assert workspace.render_file(FIXTURE_LISTING, "flat-lay-01", "black").read_bytes() == viewed.png
    moss = _warp_preview(workspace, "moss")
    assert len(warps) == 4
    assert workspace.render_file(FIXTURE_LISTING, "flat-lay-01", "moss").read_bytes() == moss.png
