"""``RenderStage.preview``/``apply`` promotion and pruning, ``snapshot()``'s
per-scene state, and ``engine.run.preview_listing`` (A32) -- through the real
engine (`build_plan`/`execute`) against the fixture workspace, the same way
``test_render_stage.py`` covers plan/apply. Byte-identity between a promoted
preview and a fresh render is the golden layer's job
(``tests/golden/test_preview_promotion.py``); this file is about which files
exist, which get reused, which get pruned, and what gets reported."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import etsy_listings.engine.stages.render as render_module
from etsy_listings.engine.apply import execute
from etsy_listings.engine.plan import StageState, build_plan
from etsy_listings.engine.run import RunObserver, preview_listing
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.render import RenderStage, _hash_token, scene_hash

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, edit_listing

COLOURS = ("black", "blue-jean", "ivory", "moss")


def _render_state(ctx, lock=None) -> StageState:
    planned = build_plan(ctx, LISTING, lock if lock is not None else a_lock(), STAGES)
    return next(s for s in planned.states if s.stage.name == "render")


def _preview_path(ctx, desired, work) -> Path:
    return ctx.workspace.preview_file(
        LISTING, work.template, work.colour, _hash_token(scene_hash(desired, work))
    )


def test_preview_renders_every_scene_on_a_first_plan(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    state = _render_state(ctx)
    stage = state.stage
    assert isinstance(stage, RenderStage)

    ready = stage.preview(ctx, state.desired, state.live)

    assert {work.key for work in ready} == set(state.desired.scenes)
    for work in state.desired.works:
        assert _preview_path(ctx, state.desired, work).is_file()


def test_preview_does_not_re_render_a_scene_already_current(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = a_context(workspace_root)
    state = _render_state(ctx)
    stage = state.stage
    assert isinstance(stage, RenderStage)
    stage.preview(ctx, state.desired, state.live)  # first call renders everything

    calls: list[None] = []
    monkeypatch.setattr(render_module, "render_scene", lambda *a, **k: calls.append(None))

    # Nothing changed -- a second plan resolves the same scenes at the same
    # hashes, so a second preview call must reuse every file it already wrote.
    second = _render_state(ctx)
    stage.preview(ctx, second.desired, second.live)

    assert calls == []


def test_preview_prunes_a_stale_file_when_a_photo_changes(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    state = _render_state(ctx)
    stage = state.stage
    assert isinstance(stage, RenderStage)
    stage.preview(ctx, state.desired, state.live)

    black = next(w for w in state.desired.works if w.colour == "black")
    old_file = _preview_path(ctx, state.desired, black)
    assert old_file.is_file()

    photo = workspace_root / "mockup-templates" / "flat-lay-01" / "black.png"
    photo.write_bytes(photo.read_bytes() + b"\x00")

    second = _render_state(ctx)
    second_black = next(w for w in second.desired.works if w.colour == "black")
    stage.preview(ctx, second.desired, second.live)

    assert not old_file.is_file()
    new_file = _preview_path(ctx, second.desired, second_black)
    assert new_file.is_file()
    assert new_file != old_file


def test_preview_skips_a_scene_that_is_already_cached(workspace_root: Path) -> None:
    """A mixed batch -- three scenes unchanged since the last apply, one
    edited -- previews only the one that actually needs it."""
    ctx = a_context(workspace_root)
    lock = execute(ctx, build_plan(ctx, LISTING, a_lock(), STAGES), a_lock())

    photo = workspace_root / "mockup-templates" / "flat-lay-01" / "black.png"
    photo.write_bytes(photo.read_bytes() + b"\x00")

    state = _render_state(ctx, lock)
    stage = state.stage
    assert isinstance(stage, RenderStage)
    by_scene = {s.scene: s.state for s in stage.snapshot(state.desired, state.live).scenes}
    assert by_scene["flat-lay-01/black"] == "stale"
    assert all(v == "cached" for k, v in by_scene.items() if k != "flat-lay-01/black")

    ready = stage.preview(ctx, state.desired, state.live)

    assert {work.key for work in ready} == {"flat-lay-01/black"}


def test_prune_removes_a_dropped_templates_whole_directory(workspace_root: Path) -> None:
    """A template no longer referenced by `media:` at all -- not just a colour
    within it -- has its entire preview subdirectory removed, not merely the
    files that used to match a scene."""
    ctx = a_context(workspace_root)
    state = _render_state(ctx)
    stage = state.stage
    assert isinstance(stage, RenderStage)
    stage.preview(ctx, state.desired, state.live)
    dropped_dir = ctx.workspace.preview_dir(LISTING) / "flat-lay-01"
    assert dropped_dir.is_dir()

    listing_path = workspace_root / "listings" / LISTING / "listing.yaml"
    text = listing_path.read_text(encoding="utf-8")
    media_block = text.split("media:\n", 1)[0] + "media:\n  - { template: colour-chart-01 }\n"
    listing_path.write_text(media_block, encoding="utf-8")

    second = _render_state(ctx)
    stage.preview(ctx, second.desired, second.live)

    assert not dropped_dir.exists()
    assert (ctx.workspace.preview_dir(LISTING) / "colour-chart-01").is_dir()


def test_prune_ignores_a_stray_file_in_the_preview_root(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    state = _render_state(ctx)
    stage = state.stage
    assert isinstance(stage, RenderStage)
    preview_root = ctx.workspace.preview_dir(LISTING)
    preview_root.mkdir(parents=True)
    stray = preview_root / "not-a-template-dir.txt"
    stray.write_text("stray", encoding="utf-8")

    stage.preview(ctx, state.desired, state.live)  # must not raise

    assert stray.is_file()


def test_apply_promotes_previews_without_rendering_again(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)
    state = next(s for s in planned.states if s.stage.name == "render")
    stage = state.stage
    assert isinstance(stage, RenderStage)
    stage.preview(ctx, state.desired, state.live)

    preview_paths = {
        work.key: _preview_path(ctx, state.desired, work) for work in state.desired.works
    }
    preview_bytes = {key: path.read_bytes() for key, path in preview_paths.items()}

    calls: list[None] = []
    monkeypatch.setattr(render_module, "render_scene", lambda *a, **k: calls.append(None))

    lock = execute(ctx, planned, a_lock())

    assert calls == [], "apply re-rendered a scene a valid preview already covered"
    assert lock.stages_completed == ["render"]
    for work in state.desired.works:
        assert not preview_paths[work.key].is_file(), "a promoted preview must be moved, not copied"
        rendered = ctx.workspace.render_file(LISTING, work.template, work.colour)
        assert rendered.read_bytes() == preview_bytes[work.key]


def test_snapshot_is_missing_then_cached_then_stale_for_only_the_edited_scene(
    workspace_root: Path,
) -> None:
    ctx = a_context(workspace_root)
    state = _render_state(ctx)
    stage = state.stage
    assert isinstance(stage, RenderStage)

    first = stage.snapshot(state.desired, state.live)
    assert {s.state for s in first.scenes} == {"missing"}
    assert {s.preview for s in first.scenes} == {False}

    lock = execute(ctx, build_plan(ctx, LISTING, a_lock(), STAGES), a_lock())

    second_state = _render_state(ctx, lock)
    second = stage.snapshot(second_state.desired, second_state.live)
    assert {s.state for s in second.scenes} == {"cached"}

    photo = workspace_root / "mockup-templates" / "flat-lay-01" / "black.png"
    photo.write_bytes(photo.read_bytes() + b"\x00")

    third_state = _render_state(ctx, lock)
    third = stage.snapshot(third_state.desired, third_state.live)
    by_scene = {s.scene: s.state for s in third.scenes}
    assert by_scene["flat-lay-01/black"] == "stale"
    assert all(v == "cached" for k, v in by_scene.items() if k != "flat-lay-01/black")


def test_preview_listing_emits_one_event_per_scene(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)

    events: list[tuple[str, str, str | None]] = []
    observer = RunObserver(
        on_preview_rendered=lambda listing, template, colour: events.append(
            (listing, template, colour)
        )
    )

    preview_listing(ctx, planned, observer)

    assert sorted(events) == sorted((LISTING, "flat-lay-01", colour) for colour in COLOURS)


def test_preview_listing_stops_before_any_scene_when_asked_to(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)

    events: list[tuple[str, str, str | None]] = []
    observer = RunObserver(
        on_preview_rendered=lambda listing, template, colour: events.append(
            (listing, template, colour)
        )
    )

    preview_listing(ctx, planned, observer, should_stop=lambda: True)

    assert events == []
    assert not any(ctx.workspace.preview_dir(LISTING).glob("**/*.png"))


def test_preview_listing_uses_the_default_observer_when_none_is_given(workspace_root: Path) -> None:
    """No caller cares yet in this PR -- the default `RunObserver`'s
    `on_preview_rendered` is a plain no-op -- but `preview_listing` must still
    render every scene when called bare, the way the CLI would."""
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)

    preview_listing(ctx, planned)  # no observer, no should_stop

    state = next(s for s in planned.states if s.stage.name == "render")
    for work in state.desired.works:
        assert _preview_path(ctx, state.desired, work).is_file()


def test_preview_listing_ignores_a_stage_that_only_shares_the_render_name(
    workspace_root: Path,
) -> None:
    """Defensive: `preview_listing` finds the render stage by *name*, so a
    stand-in that happens to share it but isn't a `RenderStage` -- and so has
    no `.preview` -- is skipped rather than crashing."""

    class NotARenderStage:
        name = "render"

    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)
    faked_states = tuple(
        replace(s, stage=NotARenderStage()) if s.stage.name == "render" else s
        for s in planned.states
    )
    faked_planned = replace(planned, states=faked_states)

    events: list[tuple[str, str, str | None]] = []
    observer = RunObserver(
        on_preview_rendered=lambda listing, template, colour: events.append(
            (listing, template, colour)
        )
    )

    preview_listing(ctx, faked_planned, observer)  # must not raise

    assert events == []


def test_preview_listing_does_nothing_when_render_is_blocked(workspace_root: Path) -> None:
    edit_listing(workspace_root, garment_profile="")
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)

    events: list[tuple[str, str, str | None]] = []
    observer = RunObserver(
        on_preview_rendered=lambda listing, template, colour: events.append(
            (listing, template, colour)
        )
    )

    preview_listing(ctx, planned, observer)  # must not raise

    assert events == []


def test_preview_listing_does_nothing_for_a_retract_only_plan(workspace_root: Path) -> None:
    edit_listing(workspace_root, lifecycle="deleted")
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)
    assert [s.stage.name for s in planned.states] == ["retract"]

    events: list[tuple[str, str, str | None]] = []
    observer = RunObserver(
        on_preview_rendered=lambda listing, template, colour: events.append(
            (listing, template, colour)
        )
    )

    preview_listing(ctx, planned, observer)  # must not raise

    assert events == []
