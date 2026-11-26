"""Pixel digests kept across a restart, for the Listing Images preview only.

A scene composed before a restart sits in the scene cache, but finding it
means knowing its files' pixel digests, which only this process's memory
held -- so the first view after a restart decoded the photo and every design
again. ``remembered_scene`` reads the digests kept on disk instead, and
``remembered_scene_was_wrong`` checks that answer afterwards. Render and
deploy go on computing them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.application.listing_reads import scene_artwork
from etsy_listings.core.application.scene_previews import (
    DISK_IMAGES,
    RenderedScene,
    SceneLayers,
    remembered_scene,
    remembered_scene_was_wrong,
    saved_scene,
)
from etsy_listings.core.engine import build_plan, execute
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.preparation.scene_cache import PIXEL_DIGESTS
from etsy_listings.core.workspace import Workspace, layout

from tests.support.builders import FIXTURE_LISTING, a_context, a_lock
from tests.support.marigold import listing_with_marigold

TEMPLATE = "flat-lay-01"


def _layers(workspace: Workspace) -> SceneLayers:
    return SceneLayers("black", scene_artwork(workspace, FIXTURE_LISTING))


def _shown(workspace: Workspace) -> RenderedScene:
    picture = remembered_scene(workspace, TEMPLATE, _layers(workspace), images=DISK_IMAGES)
    assert isinstance(picture, RenderedScene)
    return picture


def _saved(workspace: Workspace) -> RenderedScene:
    picture = saved_scene(workspace, TEMPLATE, _layers(workspace), size="full", images=DISK_IMAGES)
    assert isinstance(picture, RenderedScene)
    return picture


def _restart() -> None:
    PIXEL_DIGESTS.clear()


@pytest.fixture
def no_decoding(monkeypatch) -> None:
    def refuse(path, load=None):
        raise AssertionError(f"decoded {path}")

    monkeypatch.setattr(PIXEL_DIGESTS, "decode_photo", refuse)
    monkeypatch.setattr(PIXEL_DIGESTS, "decode_design", refuse)


@pytest.fixture
def decodes(monkeypatch) -> list[Path]:
    seen: list[Path] = []
    real = PIXEL_DIGESTS.decode_photo

    def counting(path, *args):
        seen.append(path)
        return real(path, *args)

    monkeypatch.setattr(PIXEL_DIGESTS, "decode_photo", counting)
    return seen


def test_after_a_restart_the_preview_finds_its_scene_without_decoding(
    workspace_root, request
) -> None:
    workspace = a_context(workspace_root).workspace
    first = _saved(workspace)
    _restart()
    request.getfixturevalue("no_decoding")

    shown = _shown(workspace)

    assert shown.png == first.png
    assert shown.render_identity == first.render_identity
    assert shown.remembered


def test_a_marigold_scene_after_a_restart_is_found_without_decoding(
    workspace_root, request
) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    layers = SceneLayers(None, lambda _colour: workspace.design_file("take-a-hike"))
    first = saved_scene(workspace, "shirt", layers, size="full", images=DISK_IMAGES)
    _restart()
    request.getfixturevalue("no_decoding")

    shown = remembered_scene(workspace, "shirt", layers, images=DISK_IMAGES)

    assert isinstance(shown, RenderedScene)
    assert isinstance(first, RenderedScene)
    assert shown.render_identity == first.render_identity
    assert shown.remembered


def test_a_saved_scene_after_a_restart_computes_its_digests(workspace_root, decodes) -> None:
    workspace = a_context(workspace_root).workspace
    _saved(workspace)
    _restart()
    decodes.clear()

    again = _saved(workspace)

    assert decodes, "a saved scene trusted a remembered digest"
    assert not again.remembered


def test_a_digest_this_process_computed_is_not_reported_as_remembered(workspace_root) -> None:
    workspace = a_context(workspace_root).workspace
    _saved(workspace)

    assert not _shown(workspace).remembered
    assert not remembered_scene_was_wrong(
        workspace, TEMPLATE, _layers(workspace), images=DISK_IMAGES
    )


def _forge_design_digest(workspace: Workspace, design: Path, digest: str) -> None:
    """Records ``digest`` against the design's *current* stamp: a remembered
    digest gone wrong while the file's stamp still matched."""
    current = PIXEL_DIGESTS.design(design)
    assert current is not None
    for entry in workspace.cache(layout.PIXEL_DIGESTS_DIR).glob("*.json"):
        content = json.loads(entry.read_bytes())
        if content["digest"] == current:
            content["digest"] = digest
            entry.write_bytes(json.dumps(content).encode())
            return
    raise AssertionError("the design's digest was not remembered")


def test_a_wrong_remembered_digest_is_reported_and_corrected(workspace_root) -> None:
    workspace = a_context(workspace_root).workspace
    design = workspace.design_file("take-a-hike")
    before = _saved(workspace)
    old_digest = PIXEL_DIGESTS.design(design)
    assert old_digest is not None
    Image.new("RGBA", (16, 16), "red").save(design)
    actual = _saved(workspace)
    _forge_design_digest(workspace, design, old_digest)
    _restart()

    assert _shown(workspace).render_identity == before.render_identity
    assert remembered_scene_was_wrong(workspace, TEMPLATE, _layers(workspace), images=DISK_IMAGES)

    _restart()
    corrected = _shown(workspace)
    assert corrected.render_identity == actual.render_identity
    assert corrected.remembered
    assert not remembered_scene_was_wrong(
        workspace, TEMPLATE, _layers(workspace), images=DISK_IMAGES
    )


def test_apply_renders_from_the_pixels_whatever_was_remembered(workspace_root) -> None:
    ctx = a_context(workspace_root)
    workspace = ctx.workspace
    design = workspace.design_file("take-a-hike")
    _saved(workspace)
    old_digest = PIXEL_DIGESTS.design(design)
    assert old_digest is not None
    Image.new("RGBA", (16, 16), "red").save(design)
    actual = _saved(workspace)
    _forge_design_digest(workspace, design, old_digest)
    _restart()

    execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (RenderStage(),)), a_lock())

    rendered = workspace.render_file(FIXTURE_LISTING, TEMPLATE, "black").read_bytes()
    assert rendered == actual.png
